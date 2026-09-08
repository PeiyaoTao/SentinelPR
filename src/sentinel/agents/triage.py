"""
Triage Agent: Diff parsing, noise pre-filtering, full-file AST slicing, and trust zone tagging.
"""

import ast
import fnmatch
import re
from typing import Any, Dict, List, Set, Tuple

from sentinel.config import default_config
from sentinel.state import ASTSymbolScope, DiffHunk, PRReviewState, TrustZone


def parse_diff_hunks(diff_text: str) -> List[DiffHunk]:
    """
    Parses unified diff text into structured DiffHunk objects.
    Extracts hunk line ranges (@@ -old_start,old_lines +new_start,new_lines @@).
    """
    hunks: List[DiffHunk] = []
    current_file: str = ""
    hunk_header_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

    current_hunk_lines: List[str] = []
    current_old_start = 0
    current_old_lines = 0
    current_new_start = 0
    current_new_lines = 0

    lines = diff_text.splitlines()
    for line in lines:
        if line.startswith("diff --git"):
            # Save any previous hunk
            if current_hunk_lines and current_file:
                hunks.append(
                    DiffHunk(
                        file_path=current_file,
                        old_start=current_old_start,
                        old_lines=current_old_lines,
                        new_start=current_new_start,
                        new_lines=current_new_lines,
                        content="\n".join(current_hunk_lines),
                    )
                )
                current_hunk_lines = []
            # Extract destination file: +++ b/path/to/file
            continue
        elif line.startswith("+++ b/"):
            current_file = line[6:].strip()
            continue
        elif line.startswith("--- a/"):
            continue

        match = hunk_header_re.match(line)
        if match:
            if current_hunk_lines and current_file:
                hunks.append(
                    DiffHunk(
                        file_path=current_file,
                        old_start=current_old_start,
                        old_lines=current_old_lines,
                        new_start=current_new_start,
                        new_lines=current_new_lines,
                        content="\n".join(current_hunk_lines),
                    )
                )
                current_hunk_lines = []

            current_old_start = int(match.group(1))
            current_old_lines = int(match.group(2)) if match.group(2) else 1
            current_new_start = int(match.group(3))
            current_new_lines = int(match.group(4)) if match.group(4) else 1
            current_hunk_lines.append(line)
        elif current_hunk_lines or match:
            current_hunk_lines.append(line)

    # Append trailing hunk
    if current_hunk_lines and current_file:
        hunks.append(
            DiffHunk(
                file_path=current_file,
                old_start=current_old_start,
                old_lines=current_old_lines,
                new_start=current_new_start,
                new_lines=current_new_lines,
                content="\n".join(current_hunk_lines),
            )
        )

    return hunks


def is_ignored_file(file_path: str, patterns: List[str]) -> bool:
    """Checks whether the file matches any ignore pattern (lockfiles, assets, minified)."""
    norm_path = file_path.replace("\\", "/")
    filename = norm_path.split("/")[-1]
    for pattern in patterns:
        if fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(norm_path, pattern):
            return True
    return False


def extract_changed_line_numbers(hunks: List[DiffHunk]) -> Dict[str, Set[int]]:
    """
    Computes the set of modified line numbers in the *head* file for each changed file.
    """
    file_lines: Dict[str, Set[int]] = {}
    for hunk in hunks:
        if hunk.file_path not in file_lines:
            file_lines[hunk.file_path] = set()

        current_line = hunk.new_start
        for line in hunk.content.splitlines():
            if line.startswith("@@"):
                continue
            elif line.startswith("+"):
                file_lines[hunk.file_path].add(current_line)
                current_line += 1
            elif line.startswith("-"):
                # Deleted line from base; doesn't advance new file line counter
                continue
            else:
                # Context line
                current_line += 1

    return file_lines


def classify_trust_zone(file_path: str, code_snippet: str) -> TrustZone:
    """
    Classifies symbol into PERIMETER, INTERNAL_CORE, or INTER_MODULE based on path and annotations.
    """
    norm_path = file_path.replace("\\", "/").lower()

    # Perimeter indicators
    if any(p in norm_path for p in ["api/", "routes/", "controllers/", "views/", "endpoints/", "cli/"]):
        return TrustZone.PERIMETER
    if any(decorator in code_snippet for decorator in ["@app.route", "@router.", "@get(", "@post(", "@click.command"]):
        return TrustZone.PERIMETER

    # Inter-module indicators
    if any(m in norm_path for m in ["clients/", "adapters/", "integrations/", "external/"]):
        return TrustZone.INTER_MODULE

    # Default to internal domain core
    return TrustZone.INTERNAL_CORE


def slice_ast_symbols(file_path: str, full_code: str, changed_lines: Set[int]) -> List[ASTSymbolScope]:
    """
    Parses the full head file into an AST, extracts enclosing symbols (functions, classes)
    that intersect with changed lines, and attaches relevant file-level imports.
    """
    symbols: List[ASTSymbolScope] = []
    if not full_code.strip():
        return symbols

    # Extract top-level imports first to provide context
    imports: List[str] = []
    try:
        tree = ast.parse(full_code)
    except SyntaxError:
        # If standard AST fails (e.g. non-python or syntax error), create a fallback scope
        return [
            ASTSymbolScope(
                symbol_name=file_path.split("/")[-1],
                symbol_type="file",
                file_path=file_path,
                start_line=min(changed_lines) if changed_lines else 1,
                end_line=max(changed_lines) if changed_lines else len(full_code.splitlines()),
                code_snippet=full_code,
                trust_zone=classify_trust_zone(file_path, full_code),
                imports=[],
            )
        ]

    lines = full_code.splitlines()

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            start = node.lineno - 1
            end = node.end_lineno if hasattr(node, "end_lineno") and node.end_lineno else node.lineno
            imports.append("\n".join(lines[start:end]))

    # Traverse functions, async functions, and classes
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start_line = node.lineno
            end_line = node.end_lineno if hasattr(node, "end_lineno") and node.end_lineno else start_line
            # Check if this node encompasses any changed lines
            node_range = set(range(start_line, end_line + 1))
            if node_range.intersection(changed_lines):
                snippet = "\n".join(lines[start_line - 1 : end_line])
                symbol_type = "class" if isinstance(node, ast.ClassDef) else "function"
                trust_zone = classify_trust_zone(file_path, snippet)

                symbols.append(
                    ASTSymbolScope(
                        symbol_name=node.name,
                        symbol_type=symbol_type,
                        file_path=file_path,
                        start_line=start_line,
                        end_line=end_line,
                        code_snippet=snippet,
                        trust_zone=trust_zone,
                        imports=imports,
                    )
                )

    # If changes occurred outside any function/class (e.g., top-level script statements),
    # construct a module-level symbol
    if not symbols and changed_lines:
        start_line = min(changed_lines)
        end_line = max(changed_lines)
        symbols.append(
            ASTSymbolScope(
                symbol_name="module_scope",
                symbol_type="module",
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                code_snippet="\n".join(lines[max(0, start_line - 5) : min(len(lines), end_line + 5)]),
                trust_zone=classify_trust_zone(file_path, full_code),
                imports=imports,
            )
        )

    return symbols


def triage_agent_node(state: PRReviewState) -> Dict[str, Any]:
    """
    LangGraph node: Ingests raw diff and head files, filters noise,
    extracts hunks, and produces scoped AST symbols.
    """
    diff_text = state.get("diff", "")
    head_files = state.get("head_files", {})
    all_hunks = parse_diff_hunks(diff_text)

    # Filter out ignored files (lockfiles, assets, minified)
    filtered_hunks = [
        hunk for hunk in all_hunks
        if not is_ignored_file(hunk.file_path, default_config.ignored_file_patterns)
    ]

    changed_lines_map = extract_changed_line_numbers(filtered_hunks)
    all_symbols: List[ASTSymbolScope] = []

    for file_path, changed_lines in changed_lines_map.items():
        content = head_files.get(file_path, "")
        if content:
            file_symbols = slice_ast_symbols(file_path, content, changed_lines)
            all_symbols.extend(file_symbols)

    changed_files = list(changed_lines_map.keys())

    return {
        "changed_files": changed_files,
        "hunks": filtered_hunks,
        "symbols": all_symbols,
        "candidate_findings": [],  # initialize empty list for reducers
        "repro_tests": {},
        "verified_findings": [],
    }
