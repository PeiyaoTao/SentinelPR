"""Bounded snapshots and offline containers; no project code runs on the host."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import subprocess
import tempfile
import tarfile
import uuid
from typing import cast

from sentinel.checks.models import CHECK_NAMES, CheckName, CheckIssue, CheckResult, ValidationReport

EXCLUDED = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache", "dist", "build", ".tox"}
MAX_FILE = 2_000_000
MAX_TOTAL = 32_000_000
MAX_FILES = 5000
# Deliberately narrow: no entropy-only guesses or literal values in output.
SECRET_PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    "github-token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{50,255})\b"),
    "aws-access-key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "slack-token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,200}\b"),
}


def snapshot(root: Path, destination: Path) -> tuple[str, list[str]]:
    """Git-visible files (including tracked secrets), or a plain-directory walk.

    Ignore rules apply to untracked files only. Never follow links or junctions.
    """
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Check target must be a directory")
    omitted: list[str] = []
    proc = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True, timeout=30)
    if proc.returncode == 0:
        listed = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"], capture_output=True, timeout=30, check=True)
        paths = sorted(set(os.fsdecode(p) for p in listed.stdout.split(b"\0") if p))
    else:
        if b"not a git repository" not in proc.stderr.lower():
            raise RuntimeError("Git could not enumerate the target; refusing to bypass ignore rules")
        paths = []
        def fail_walk(error: OSError) -> None:
            raise error
        for parent, directories, files in os.walk(root, followlinks=False, onerror=fail_walk):
            omitted.extend((Path(parent) / d).relative_to(root).as_posix() for d in directories if d not in EXCLUDED and _link(Path(parent) / d))
            directories[:] = [d for d in directories if d not in EXCLUDED and not _link(Path(parent) / d)]
            paths.extend((Path(parent) / f).relative_to(root).as_posix() for f in files)
        paths.sort()
    total = 0
    copied = 0
    digest = hashlib.sha256()
    for relative in paths:
        path = Path(relative)
        if any(part in EXCLUDED for part in path.parts):
            continue
        source = root / path
        if path.is_absolute() or ".." in path.parts or any(_link(p) for p in [source, *source.parents] if p != root and root in p.parents):
            omitted.append(relative)
            continue
        try:
            size = source.stat().st_size
            if size > MAX_FILE or total + size > MAX_TOTAL or copied >= MAX_FILES:
                omitted.append(relative)
                continue
            data = source.read_bytes()
            if len(data) > MAX_FILE or total + len(data) > MAX_TOTAL:
                omitted.append(relative)
                continue
        except OSError:
            omitted.append(relative)
            continue
        total += len(data)
        copied += 1
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o755 if source.stat().st_mode & 0o111 else 0o644)
        digest.update(relative.encode("utf-8", errors="surrogateescape") + b"\0" + hashlib.sha256(data).digest())
    return digest.hexdigest(), omitted


def _link(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400) if path.exists() or path.is_symlink() else False


def scan_secrets(root: Path) -> CheckResult:
    issues = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        source = data.decode("utf-8", errors="replace")
        for rule, pattern in SECRET_PATTERNS.items():
            for match in pattern.finditer(source):
                issues.append(CheckIssue(rule=rule, message="Potential credential detected; verify and rotate if real. Value redacted.", path=path.relative_to(root).as_posix(), line=source.count("\n", 0, match.start()) + 1))
    return CheckResult(name="secrets", status="failed" if issues else "passed", summary=f"{len(issues)} potential credentials. Scans the current snapshot, not Git history.", issues=issues)


# This constant script is executed only inside the disposable container.
# Stream the bounded snapshot into tmpfs; no host directory or socket is mounted.
BOOTSTRAP = """import os, subprocess, sys, tarfile
os.mkdir('/tmp/project')
with tarfile.open(fileobj=sys.stdin.buffer, mode='r|') as archive:
    archive.extractall('/tmp/project', filter='data')
os.chdir('/tmp/project')
# Check the prepared environment without installing or importing target packages.
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
from packaging.requirements import Requirement, InvalidRequirement
import re, tomllib
try:
    requirements = []
    lock = Path(sys.argv[1])
    if lock.is_file():
        for row in lock.read_text().splitlines():
            row = row.partition('#')[0].strip()
            if not row:
                continue
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9][A-Za-z0-9.!+_-]*', row):
                sys.exit(78)
            requirements.append(Requirement(row))
    if Path('pyproject.toml').is_file():
        project = tomllib.loads(Path('pyproject.toml').read_text())
        requirements.extend(Requirement(row) for row in project.get('project', {}).get('dependencies', []))
        requirements.extend(Requirement(row) for row in project.get('build-system', {}).get('requires', []))
    for requirement in requirements:
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        if requirement.url or version(requirement.name) not in requirement.specifier:
            sys.exit(78)
except (PackageNotFoundError, InvalidRequirement, ValueError):
    sys.exit(78)
os.environ.update(HOME='/tmp', PYTHONDONTWRITEBYTECODE='1', SENTINEL_LLM_PROVIDER='heuristics', PYTHONPATH='/tmp/project/src:/tmp/project')
with open('/tmp/tool-output', 'w+b') as output:
    code = subprocess.call(sys.argv[2:], stdout=output, stderr=subprocess.STDOUT)
    size = output.tell()
    output.seek(0)
    sys.stdout.buffer.write(output.read(1_000_000))
sys.exit(124 if size > 1_000_000 else code)
"""
COMMANDS = {
    "lint": ["python", "-I", "-m", "ruff", "check", "--output-format", "json", "."],
    "types": ["python", "-I", "-m", "mypy", "--no-incremental", "--show-error-codes", "."],
    "tests": ["python", "-m", "pytest", "--tb=no", "-q"],
    "build": ["python", "-I", "-m", "build", "--no-isolation", "--outdir", "/tmp/dist"],
}


def container_check(name: CheckName, root: Path, image: str, timeout: int, requirements: str = "requirements-audit.txt") -> CheckResult:
    container_name = "sentinel-check-" + uuid.uuid4().hex
    command = ["docker", "run", "--rm", "-i", "--pull=never", "--name", container_name,
               "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
               "--pids-limit=128", "--memory=1g", "--cpus=1", "--user=65534:65534",
               "--tmpfs=/tmp:rw,nosuid,size=512m,mode=1777", "--log-driver=none",
               "--entrypoint=python", image, "-I", "-c", BOOTSTRAP, requirements, *COMMANDS[name]]
    try:
        # Capture to disk, not unbounded RAM. Raw logs are never exported: tests
        # and tools may print credentials, source lines, or arbitrary target data.
        with tempfile.TemporaryFile() as archive_file, tempfile.TemporaryFile() as output:
            with tarfile.open(fileobj=archive_file, mode="w") as archive:
                for path in sorted(root.rglob("*")):
                    archive.add(path, arcname=path.relative_to(root).as_posix(), recursive=False)
            archive_file.seek(0)
            proc = subprocess.run(command, stdin=archive_file, stdout=output, stderr=subprocess.STDOUT, timeout=timeout)
            output.seek(0)
            raw = output.read(1_000_001)
    except FileNotFoundError:
        return CheckResult(name=name, status="incomplete", summary="Docker is not installed; no host fallback was used.")
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, timeout=30)
        return CheckResult(name=name, status="incomplete", summary="Check timed out; disposable container removed.")
    return classify_container_result(name, proc.returncode, raw)


def classify_container_result(name: CheckName, code: int, raw: bytes) -> CheckResult:
    """Interpret status independently of transport; never expose raw logs."""
    text = raw.decode("utf-8", errors="replace")
    if code != 0 and text.lstrip().lower().startswith(("failed to connect to the docker api", "docker: error during connect", "error during connect", "cannot connect to the docker daemon")):
        return CheckResult(name=name, status="incomplete", summary="Docker engine is unavailable; no target check ran and no host fallback was used.")
    if code in (125, 126, 127) or (code != 0 and ("No module named" in text or "Unmet dependencies" in text)):
        return CheckResult(name=name, status="incomplete", summary="Container, tool, or prepared dependency environment unavailable. Verify the check image.")
    if code == 78:
        return CheckResult(name=name, status="incomplete", summary="Prepared image does not satisfy target dependency pins or declared requirements; rebuild the trusted image.")
    if code == 124:
        return CheckResult(name=name, status="incomplete", summary="Tool output exceeded the diagnostic budget.")
    if code == 0:
        return CheckResult(name=name, status="passed", summary="Tool completed successfully in an offline container.")
    if name in ("lint", "types") and code == 1:
        return parse_code_diagnostics(name, raw, text)
    if name == "tests" and code == 1:
        return CheckResult(name=name, status="failed", summary="The project test suite reported failures. Raw test output is withheld to protect credentials.")
    if name == "tests" and code in (2, 3, 4, 5):
        return CheckResult(name=name, status="incomplete", summary="Tests did not complete: collection, configuration, interruption, or no tests collected.")
    if name == "build" and code == 1:
        return CheckResult(name=name, status="failed", summary="The project failed to build an sdist and wheel in the prepared environment.")
    return CheckResult(name=name, status="error", summary=f"Tool could not complete (exit {code}); check tool configuration and the prepared image.")



def parse_code_diagnostics(name: CheckName, raw: bytes, text: str) -> CheckResult:
    """Export tool codes and locations only."""
    issues = []
    if name == "lint" and len(raw) <= 1_000_000:
        try:
            diagnostics = json.loads(text)
            for item in diagnostics:
                # Only retain code/location; messages may embed secrets.
                rule = item.get("code") or "syntax"
                file = PurePosixPath(item["filename"]).relative_to("/tmp/project").as_posix()
                issues.append(CheckIssue(rule=str(rule), message="Lint violation; run Ruff locally for details.", path=file, line=int(item["location"]["row"])))
        except (ValueError, TypeError, KeyError, AttributeError):
            return CheckResult(name=name, status="error", summary="Linter returned malformed diagnostics.")
    if name == "types":
        for match in re.finditer(r"^(.+?):(\d+)(?::\d+)?: error: .*?\[([a-z-]+)\]$", text, re.MULTILINE):
            file, line, rule = match.groups()
            file = file.removeprefix("/tmp/project/")
            if not PurePosixPath(file).is_absolute() and ".." not in PurePosixPath(file).parts:
                issues.append(CheckIssue(rule=rule, message="Type-checking diagnostic; run mypy locally for details.", path=file, line=int(line)))
    return CheckResult(name=name, status="failed", summary="Tool reported code diagnostics. Run the tool locally for details; raw output is withheld to protect credentials.", issues=issues)

def audit_dependencies(root: Path, requirements: str, timeout: int) -> CheckResult:
    """Audit exact pins only; never resolve/install dependencies or execute metadata.

    The online auditor runs outside the target directory, with a sanitized input
    containing only package names and versions. It never imports target code.
    """
    path = root / requirements
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        return CheckResult(name="dependencies", status="incomplete", summary="A fully pinned requirements file is required for dependency auditing.")
    lines = []
    for row in path.read_text(encoding="utf-8").splitlines():
        row = row.partition("#")[0].strip()
        if not row:
            continue
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9][A-Za-z0-9.!+_-]*", row):
            return CheckResult(name="dependencies", status="incomplete", summary="Audit input must contain exact name==version pins, including transitive dependencies; URLs, options, ranges, and markers are unsupported.")
        lines.append(row)
    if not lines:
        return CheckResult(name="dependencies", status="incomplete", summary="Dependency audit input contains no pinned packages.")
    with tempfile.TemporaryDirectory(prefix="sentinel-audit-") as directory:
        safe_input = Path(directory) / "requirements.txt"
        safe_input.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            proc = subprocess.run([sys.executable, "-I", "-m", "pip_audit", "--disable-pip", "--no-deps", "--progress-spinner", "off", "--format", "json", "-r", str(safe_input)], cwd=directory, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return CheckResult(name="dependencies", status="incomplete", summary="Vulnerability database query timed out.")
    if b"No module named pip_audit" in proc.stderr:
        return CheckResult(name="dependencies", status="incomplete", summary="Install the SentinelPR checks extra to provide pip-audit.")
    if proc.returncode not in (0, 1):
        return CheckResult(name="dependencies", status="error", summary="Dependency auditor failed; verify network access and tool configuration.")
    try:
        payload = json.loads(proc.stdout)
        packages = payload["dependencies"]
        if not isinstance(packages, list) or len(packages) != len(set(lines)):
            raise ValueError("Incomplete audit")
        if any("skip_reason" in p for p in packages):
            return CheckResult(name="dependencies", status="incomplete", summary="The vulnerability service could not audit every pinned dependency.")
        issues = [CheckIssue(rule=v["id"], message=f"{p['name']} {p['version']}: known vulnerability; fixed versions: {', '.join(v.get('fix_versions', [])) or 'not reported'}") for p in packages for v in p["vulns"]]
    except (ValueError, TypeError, KeyError):
        return CheckResult(name="dependencies", status="error", summary="Dependency auditor returned invalid or incomplete JSON.")
    if proc.returncode == 1 and not issues:
        return CheckResult(name="dependencies", status="error", summary="Dependency audit failed without vulnerability evidence.")
    return CheckResult(name="dependencies", status="failed" if issues else "passed", summary=f"{len(issues)} known vulnerabilities in the supplied pins. Lock completeness is the caller's responsibility.", issues=issues)


def run_checks(root: str | Path, names: list[str], image: str = "sentinel-checks:local", timeout: int = 300, requirements: str = "requirements-audit.txt") -> ValidationReport:
    if not names or any(name not in CHECK_NAMES for name in names):
        raise ValueError("Unknown or empty validation check selection")
    if timeout < 1 or not image or image.startswith("-"):
        raise ValueError("Check timeout and container image must be valid")
    with tempfile.TemporaryDirectory(prefix="sentinel-checks-") as directory:
        staged = Path(directory) / "source"
        staged.mkdir()
        digest, omitted = snapshot(Path(root), staged)
        results = []
        for name in dict.fromkeys(names):
            if name == "secrets":
                result = scan_secrets(staged)
            elif name == "dependencies":
                result = audit_dependencies(staged, requirements, timeout)
            else:
                result = container_check(cast(CheckName, name), staged, image, timeout, requirements)
            if omitted:
                if result.status == "passed":
                    result.status = "incomplete"
                result.summary += f" Snapshot omitted {len(omitted)} unreadable, linked, or over-budget files."
            results.append(result)
        return ValidationReport(results=results, snapshot_id=digest)
