"""Narrow, independently testable specialists. All quality findings are advisory."""

import ast
from collections import defaultdict

from sentinel.quality.index import RepositoryIndex, digest, scoped_nodes
from sentinel.quality.models import Evidence, QualityFinding, SourceLocation
from sentinel.repository import is_test_file


def _finding(index, rule, category, title, explanation, recommendation, subject, locations,
             *, priority="medium", hypothesis=False, trigger="The observed structure is present in the indexed snapshot."):
    return QualityFinding(
        rule_id=rule, category=category, title=title, explanation=explanation,
        recommendation=recommendation, subject=subject, priority=priority,
        trigger_conditions=trigger, verification_status="hypothesis" if hypothesis else "observed",
        confidence="medium" if hypothesis else "high",
        fingerprint=digest(rule + "|" + subject),
        evidence=[Evidence(kind="dependency" if category == "architecture" else "pattern" if hypothesis else "ast",
            description=explanation, location=location, source_hash=index.hashes[location.file_path]) for location in locations],
    )


def _location(path, node):
    return SourceLocation(file_path=path, start_line=node.lineno, end_line=node.end_lineno)


def _functions(index, config):
    return [s for s in index.functions() if config.quality_include_tests or not is_test_file(s.location.file_path)]


def architecture(index: RepositoryIndex, config):
    findings = []
    edges = {(e.source, e.target): e for e in index.dependencies
             if config.quality_include_tests or not is_test_file(e.source)}
    graph = defaultdict(set)
    for source, target in edges:
        graph[source].add(target)
        source_module, target_module = index.module_names[source], index.module_names[target]
        for layer, forbidden in config.quality_forbidden_dependencies.items():
            if source_module == layer or source_module.startswith(layer + "."):
                for destination in forbidden:
                    if target_module == destination or target_module.startswith(destination + "."):
                        findings.append(_finding(index, "architecture.forbidden-import", "architecture",
                            "Configured dependency boundary crossed",
                            f"{source_module} imports {target_module}; policy forbids dependencies from {layer} to {destination}.",
                            "Move the shared contract to an allowed layer or revise the explicitly configured architecture rule.",
                            f"{source}->{target}", [edges[source, target].location], priority="high"))
    # Iterative DFS emits witnessed cycles, never assumes every SCC has the same cycle.
    visited = set()
    for root in sorted(graph):
        if root in visited:
            continue
        path, positions = [root], {root: 0}
        stack = [(root, iter(sorted(graph[root])))]
        visited.add(root)
        while stack:
            source, children = stack[-1]
            next_target = next(children, None)
            if next_target is None:
                stack.pop()
                positions.pop(path.pop())
            elif next_target in positions:
                cycle = path[positions[next_target]:] + [next_target]
                links = list(zip(cycle, cycle[1:]))
                findings.append(_finding(index, "architecture.import-cycle", "architecture",
                    "Module dependency cycle",
                    " -> ".join(cycle),
                    "Inspect initialization order and responsibility boundaries; extract a shared contract if the coupling is unnecessary. A cycle alone does not prove an import failure.",
                    "|".join(sorted(f"{a}->{b}" for a, b in links)), [edges[pair].location for pair in links]))
            elif next_target not in visited:
                visited.add(next_target)
                positions[next_target] = len(path)
                path.append(next_target)
                stack.append((next_target, iter(sorted(graph[next_target]))))
    return findings


def redundancy(index: RepositoryIndex, config):
    findings, groups = [], defaultdict(list)
    for symbol in _functions(index, config):
        node = symbol.node
        body = [n for n in node.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))]
        count = sum(isinstance(n, ast.stmt) for statement in body for n in scoped_nodes(statement))
        if count >= config.quality_duplicate_min_statements:
            canonical = ast.dump(node.args, include_attributes=False) + "|" + "|".join(ast.dump(n, include_attributes=False) for n in body)
            groups[canonical].append(symbol)
        for block in scoped_nodes(node):
            for field in ("body", "orelse", "finalbody"):
                statements = getattr(block, field, [])
                if not isinstance(statements, list):
                    continue
                for position, statement in enumerate(statements[:-1]):
                    if isinstance(statement, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                        unreachable = statements[position + 1]
                        findings.append(_finding(index, "redundancy.unreachable", "redundancy",
                            "Unreachable statements after unconditional control transfer",
                            f"Statements after {type(statement).__name__.lower()} in this block cannot execute.",
                            "Remove the unreachable code or correct the misplaced control transfer.",
                            f"{symbol.location.file_path}::{symbol.qualified_name}:{ast.dump(unreachable, include_attributes=False)}",
                            [_location(symbol.location.file_path, unreachable)], priority="low"))
                        break
    for members in groups.values():
        if len(members) < 2:
            continue
        names = sorted(f"{s.location.file_path}::{s.qualified_name}" for s in members)
        findings.append(_finding(index, "redundancy.duplicate-function", "redundancy",
            "Matching function implementations",
            f"{len(members)} functions have identical argument and body ASTs (excluding docstrings and formatting). Their runtime environments may differ.",
            "Check whether these implementations share a contract before extracting a common helper; retain intentional duplication where responsibilities differ.",
            "|".join(names), [s.location for s in members]))
    return findings


def _nesting(node, depth=0):
    maximum = depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        increment = isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.Match))
        maximum = max(maximum, _nesting(child, depth + int(increment)))
    return maximum


def readability(index: RepositoryIndex, config):
    findings = []
    for symbol in _functions(index, config):
        length = symbol.node.end_lineno - symbol.node.lineno + 1
        depth = _nesting(symbol.node)
        subject = f"{symbol.location.file_path}::{symbol.qualified_name}"
        if length > config.quality_max_function_lines:
            findings.append(_finding(index, "readability.long-function", "readability",
                "Long function warrants a responsibility review",
                f"Function spans {length} source lines; configured threshold is {config.quality_max_function_lines}.",
                "Identify separable responsibilities and extract named operations where that improves comprehension. Length alone is not a defect.",
                subject, [symbol.location], priority="low"))
        if depth > config.quality_max_nesting:
            findings.append(_finding(index, "readability.deep-nesting", "readability",
                "Deeply nested control flow",
                f"Control-flow nesting reaches {depth}; configured threshold is {config.quality_max_nesting}.",
                "Consider guard clauses or named helper operations while preserving behavior and exception handling.",
                subject, [symbol.location], priority="low"))
    return findings


def maintainability(index: RepositoryIndex, config):
    findings = []
    for symbol in _functions(index, config):
        complexity = 1
        for node in scoped_nodes(symbol.node):
            if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.comprehension)):
                complexity += 1
            elif isinstance(node, ast.BoolOp):
                complexity += len(node.values) - 1
        if complexity > config.quality_max_complexity:
            related = index.get_related_tests(symbol.id)
            findings.append(_finding(index, "maintainability.branch-complexity", "maintainability",
                "Function has many decision paths",
                f"Static branch-complexity estimate is {complexity}; threshold is {config.quality_max_complexity}. {len(related)} test module(s) directly import its module; this is not coverage evidence.",
                "Add behavioral cases for distinct outcomes and consider separating independent policies before changing control flow.",
                f"{symbol.location.file_path}::{symbol.qualified_name}", [symbol.location]))
    return findings


def performance(index: RepositoryIndex, config):
    findings = []
    for symbol in _functions(index, config):
        path = symbol.location.file_path
        seen = set()
        for loop in scoped_nodes(symbol.node):
            if not isinstance(loop, (ast.For, ast.AsyncFor, ast.While)):
                continue
            for statement in loop.body:
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                for node in scoped_nodes(statement):
                    if not isinstance(node, ast.Call) or node.lineno in seen:
                        continue
                    name = index.call_name(path, node, symbol)
                    regex = name == "re.compile" and node.args and all(isinstance(arg, ast.Constant) for arg in node.args) and not node.keywords
                    query = isinstance(node.func, ast.Attribute) and node.func.attr in {"execute", "executemany"}
                    if not regex and not query:
                        continue
                    seen.add(node.lineno)
                    explanation = "A constant regular expression is compiled inside a loop." if regex else "A query-like execute call appears inside a loop. The receiver and runtime query count have not been verified."
                    findings.append(_finding(index,
                        "performance.regex-in-loop" if regex else "performance.query-in-loop", "performance",
                        "Repeated regex compilation" if regex else "Potential per-item query overhead",
                        explanation,
                        "Measure the loop's workload; move invariant work out of the loop or consider batching after confirming semantics and transaction requirements.",
                        f"{path}::{symbol.qualified_name}:{ast.dump(node, include_attributes=False)}",
                        [_location(path, loop), _location(path, node)], hypothesis=True,
                        trigger="The loop runs repeatedly and this operation contributes material cost; caching or batching may already reduce it."))
    return findings


def security(index: RepositoryIndex, config):
    findings = []
    for symbol in _functions(index, config):
        path = symbol.location.file_path
        args = symbol.node.args
        parameters = {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
        # Reassigned parameters require actual data-flow analysis; do not invent a trace.
        parameters -= {n.id for n in scoped_nodes(symbol.node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
        for node in scoped_nodes(symbol.node):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = index.call_name(path, node, symbol)
            builtin_shadowed = name in {s.name for s in index.symbols.values() if s.location.file_path == path}
            dynamic = name in {"eval", "exec"} and not builtin_shadowed
            shell = name in {"subprocess.run", "subprocess.Popen", "subprocess.call", "subprocess.check_output"} and any(
                k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords)
            expression = node.args[0]
            direct_expression = all(isinstance(n, (ast.Name, ast.Load, ast.Constant, ast.BinOp, ast.Add, ast.Mod, ast.JoinedStr, ast.FormattedValue)) for n in ast.walk(expression))
            used = parameters & {n.id for n in ast.walk(expression) if isinstance(n, ast.Name)}
            if (dynamic or shell) and direct_expression and used:
                findings.append(_finding(index, "security.parameter-to-execution", "security",
                    "Function parameter reaches a dynamic execution operation",
                    f"Parameter(s) {', '.join(sorted(used))} appear directly in the input to {name}. This establishes a local syntactic path, not attacker control.",
                    "Inspect callers and perimeter validation. If untrusted data reaches this operation, replace dynamic execution with a constrained API.",
                    f"{path}::{symbol.qualified_name}:{ast.dump(node, include_attributes=False)}",
                    [symbol.location, _location(path, node)], priority="high", hypothesis=True,
                    trigger="A caller can supply attacker-controlled text and no effective validation or authorization prevents its execution."))
    return findings


SPECIALISTS = {
    "architecture": architecture, "redundancy": redundancy, "performance": performance,
    "readability": readability, "maintainability": maintainability, "security": security,
}
