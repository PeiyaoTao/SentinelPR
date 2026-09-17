"""Read Git blobs at immutable revisions, without consulting the working tree."""
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess

MAX_BLOB = 2_000_000
MAX_TOTAL = 32_000_000
MAX_FILES = 5000


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, timeout=60).stdout


def commit(root: Path, revision: str) -> str:
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", revision):
        raise ValueError("Expected a full immutable commit SHA")
    return git(root, "rev-parse", "--verify", revision + "^{commit}").decode().strip()


def tree(root: Path, sha: str) -> dict[str, tuple[str, str]]:
    entries = {}
    for entry in git(root, "ls-tree", "-r", "-z", sha).split(b"\0"):
        if not entry:
            continue
        metadata, name = entry.split(b"\t", 1)
        mode, kind, oid = metadata.decode().split()
        path = name.decode("utf-8")
        if kind == "blob":
            entries[path] = (mode, oid)
        else:
            entries[path] = (mode, "")
    return entries


def read_tree(root: Path, entries: dict[str, tuple[str, str]]) -> tuple[dict[str, bytes], list[str]]:
    contents: dict[str, bytes] = {}
    omitted = []
    total = 0
    for path, (mode, oid) in entries.items():
        relative = Path(path)
        if mode not in ("100644", "100755") or relative.is_absolute() or ".." in relative.parts or any(p.lower() == ".git" for p in relative.parts) or "\\" in path or ":" in path:
            omitted.append(path)
            continue
        size = int(git(root, "cat-file", "-s", oid))
        if size > MAX_BLOB or total + size > MAX_TOTAL or len(contents) >= MAX_FILES:
            omitted.append(path)
            continue
        data = git(root, "cat-file", "blob", oid)
        total += len(data)
        contents[path] = data
    return contents, omitted


@dataclass
class PRSnapshot:
    head_sha: str
    base_sha: str
    merge_base: str
    diff: str
    head_files: dict[str, str]
    base_files: dict[str, str]
    uninspected: list[str]


def load_pr_snapshot(root: Path, base_sha: str, head_sha: str) -> PRSnapshot:
    head = commit(root, head_sha)
    base = commit(root, base_sha)
    merge_base = git(root, "merge-base", base, head).decode().strip()
    diff = git(root, "diff", "--no-ext-diff", "--no-textconv", "--no-renames", merge_base, head, "--").decode("utf-8", errors="replace")
    changed = [p.decode("utf-8") for p in git(root, "diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only", "-z", merge_base, head, "--").split(b"\0") if p]
    head_tree, base_tree = tree(root, head), tree(root, merge_base)
    heads, head_omitted = read_tree(root, {p: head_tree[p] for p in changed if p in head_tree})
    bases, base_omitted = read_tree(root, {p: base_tree[p] for p in changed if p in base_tree})
    def decode(files):
        result = {}
        skipped = []
        for path, data in files.items():
            try:
                if b"\0" in data:
                    raise ValueError("Binary file")
                result[path] = data.decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                skipped.append(path)
        return result, skipped
    head_text, head_binary = decode(heads)
    base_text, base_binary = decode(bases)
    return PRSnapshot(head, base, merge_base, diff, head_text, base_text, sorted(set(head_omitted + base_omitted + head_binary + base_binary)))


def materialize_commit(root: Path, sha: str, destination: Path) -> list[str]:
    entries = tree(root, commit(root, sha))
    contents, omitted = read_tree(root, entries)
    for relative, data in contents.items():
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o755 if entries[relative][0] == "100755" else 0o644)
    return omitted
