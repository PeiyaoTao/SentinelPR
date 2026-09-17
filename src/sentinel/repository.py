"""Read a bounded working-directory snapshot without importing or executing its code."""

import ast
import io
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tokenize

from sentinel.agents.triage import classify_trust_zone, is_ignored_file
from sentinel.config import SentinelConfig
from sentinel.state import ASTSymbolScope, PRReviewState, RepositoryInventory


EXCLUDED_DIRECTORIES = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "vendor",
    "dist", "build", "__pycache__", ".pytest_cache", ".mypy_cache", ".tox",
}
OTHER_SOURCE_SUFFIXES = {
    ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".rb", ".php",
    ".c", ".h", ".cpp", ".cs", ".swift", ".kt", ".sh", ".sql", ".vue",
}
CONTEXT_NAMES = {
    "pyproject.toml", "setup.cfg", "setup.py", "package.json", "Dockerfile",
    "Makefile", "tox.ini", "pytest.ini", ".gitlab-ci.yml", "Jenkinsfile",
}


def is_test_file(path: str) -> bool:
    item = Path(path)
    return "tests" in item.parts or item.name.startswith("test_") or item.name.endswith("_test.py")


def is_context_file(path: str) -> bool:
    item = Path(path)
    return (
        item.name in CONTEXT_NAMES
        or item.name.lower().startswith(("readme", "license", "contributing"))
        or (item.name.startswith("requirements") and item.suffix == ".txt")
        or (path.startswith(".github/workflows/") and item.suffix in {".yml", ".yaml"})
    )


def _is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _list_files(root: Path) -> list[str]:
    """Git honors ignore rules; plain folders use the documented built-in exclusions."""
    if shutil.which("git"):
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )
        if result.returncode == 0:
            listed_files = subprocess.run(
                ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "."],
                capture_output=True, check=True,
            )
            return sorted(set(os.fsdecode(p) for p in listed_files.stdout.split(b"\0") if p))
        if "not a git repository" not in result.stderr.lower():
            raise RuntimeError(f"Cannot inspect repository: {result.stderr.strip()}")
    elif any((parent / ".git").exists() for parent in (root, *root.parents)):
        raise RuntimeError("Git is required to honor this repository's ignore rules.")

    paths: list[str] = []
    def fail_walk(error: OSError) -> None:
        raise error
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=fail_walk):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRECTORIES and not _is_link(Path(directory) / d))
        paths.extend((Path(directory) / name).relative_to(root).as_posix() for name in files)
    return sorted(paths)


def collect_repository(path: str | Path, config: SentinelConfig) -> tuple[RepositoryInventory, dict[str, str]]:
    root = Path(path).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"Repository path must be a directory: {root}")
    inventory = RepositoryInventory(root=str(root), files=_list_files(root))
    contents: dict[str, str] = {}
    total_bytes = 0
    for name in inventory.files:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Repository entry escapes the selected directory: {name}")
        if any(part in EXCLUDED_DIRECTORIES for part in relative.parts):
            inventory.excluded_files[name] = "generated, dependency, or repository metadata"
            continue
        if relative.name.startswith(".env") or relative.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}:
            inventory.excluded_files[name] = "credential/configuration secret file"
            continue
        if is_ignored_file(name, config.ignored_file_patterns):
            inventory.excluded_files[name] = "configured noise filter"
            continue
        source = relative.suffix == ".py"
        context = is_context_file(name)
        if not source and not context:
            if relative.suffix.lower() in OTHER_SOURCE_SUFFIXES:
                inventory.uninspected_files[name] = "language has no repository analyzer"
            else:
                inventory.excluded_files[name] = "outside Python source and project context scope"
            continue
        target = root / relative
        try:
            if any(_is_link(part) for part in (target, *target.parents) if part != root and root in part.parents):
                inventory.uninspected_files[name] = "symbolic link or junction is not followed"
                continue
            resolved = target.resolve(strict=True)
            if not resolved.is_relative_to(root):
                inventory.uninspected_files[name] = "file resolves outside selected directory"
                continue
            if not resolved.is_file():
                inventory.uninspected_files[name] = "not a regular file"
                continue
            if len(contents) >= config.repository_max_files:
                inventory.uninspected_files[name] = "repository file budget exceeded"
                continue
            with resolved.open("rb") as handle:
                raw = handle.read(config.repository_max_file_bytes + 1)
            if len(raw) > config.repository_max_file_bytes:
                inventory.uninspected_files[name] = "per-file byte budget exceeded"
                continue
            if total_bytes + len(raw) > config.repository_max_total_bytes:
                inventory.uninspected_files[name] = "repository byte budget exceeded"
                continue
            if source:
                encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
                content = raw.decode(encoding)
                ast.parse(content, filename=name)
            else:
                content = raw.decode("utf-8-sig")
        except (OSError, UnicodeError, SyntaxError, ValueError, LookupError) as error:
            inventory.uninspected_files[name] = f"{type(error).__name__}: {error}"
            continue
        contents[name] = content
        total_bytes += len(raw)
        if source:
            inventory.analyzed_files.append(name)
        else:
            inventory.context_files.append(name)
    return inventory, contents


def repository_symbols(path: str, content: str) -> list[ASTSymbolScope]:
    """Non-overlapping top-level scopes preserve decorators and exact source offsets."""
    tree = ast.parse(content, filename=path)
    lines = content.splitlines()
    imports = [segment for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)) if (segment := ast.get_source_segment(content, n)) is not None]
    scopes = []
    for node in tree.body:
        decorators = getattr(node, "decorator_list", [])
        start = min([node.lineno, *(d.lineno for d in decorators)])
        end = node.end_lineno
        assert end is not None, "Parsed statements have an end line"
        snippet = "\n".join(lines[start - 1:end])
        scopes.append(ASTSymbolScope(
            symbol_name=getattr(node, "name", "module_scope"),
            symbol_type="class" if isinstance(node, ast.ClassDef) else "function" if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else "module",
            file_path=path, start_line=start, end_line=end, code_snippet=snippet,
            trust_zone=classify_trust_zone(path, snippet), imports=imports,
        ))
    return scopes


def repository_triage_node(state: PRReviewState) -> dict:
    inventory = state["repository_inventory"]
    return {"symbols": [scope for name in inventory.analyzed_files for scope in repository_symbols(name, state["head_files"][name])]}
