"""Shared Python index. Resolution is conservative and never imports target modules."""

import ast
from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath

from sentinel.quality.models import SourceLocation


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def scoped_nodes(node):
    """Walk one lexical scope, excluding nested functions, classes and lambdas."""
    yield node
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            yield from scoped_nodes(child)


@dataclass(frozen=True)
class Symbol:
    id: str
    name: str
    qualified_name: str
    module: str
    location: SourceLocation
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


@dataclass(frozen=True)
class Dependency:
    source: str
    target: str
    location: SourceLocation


class RepositoryIndex:
    def __init__(self, files: dict[str, str]):
        self.files = {p: text for p, text in sorted(files.items()) if p.endswith(".py")}
        self.hashes = {p: digest(text) for p, text in self.files.items()}
        self.snapshot_id = digest(json.dumps(self.hashes, sort_keys=True))
        self.trees = {}
        self.symbols: dict[str, Symbol] = {}
        self.modules: dict[str, str] = {}
        self.module_names: dict[str, str] = {}
        self.dependencies: list[Dependency] = []
        self.bindings: dict[str, dict[str, str]] = {}
        self.calls: dict[str, set[str]] = {}
        self.unresolved_calls = 0
        self.errors: dict[str, str] = {}
        self.limitations = []
        ambiguous = set()
        for path, text in self.files.items():
            try:
                self.trees[path] = ast.parse(text, filename=path)
            except (SyntaxError, ValueError) as error:
                self.errors[path] = str(error)
                continue
            parts = list(PurePosixPath(path).with_suffix("").parts)
            if len(parts) > 1 and parts[0] == "src":
                parts.pop(0)
            if parts[-1] == "__init__":
                parts.pop()
            module = ".".join(parts)
            self.module_names[path] = module
            if module in self.modules:
                ambiguous.add(module)
            self.modules[module] = path
            self._index_symbols(path, module, self.trees[path])
        for name in ambiguous:
            del self.modules[name]
            self.limitations.append(f"Ambiguous module name {name!r}; imports to it were not resolved.")
        for path, tree in self.trees.items():
            self._index_imports(path, tree)
        self._index_calls()

    def _index_symbols(self, path, module, tree):
        def visit(node, parents=()):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    qualified = ".".join((*parents, child.name))
                    sid = f"{path}::{qualified}@{child.lineno}"
                    start = min([child.lineno, *(d.lineno for d in child.decorator_list)])
                    assert child.end_lineno is not None
                    self.symbols[sid] = Symbol(sid, child.name, qualified, module,
                        SourceLocation(file_path=path, start_line=start, end_line=child.end_lineno), child)
                    visit(child, (*parents, child.name))
                else:
                    visit(child, parents)
        visit(tree)

    def _index_imports(self, path, tree):
        bindings: dict[str, str] = {}
        self.bindings[path] = bindings
        module = self.module_names[path]
        package = module if path.endswith("/__init__.py") else module.rpartition(".")[0]
        # Only unconditional module-level imports support definite dependency edges.
        for node in tree.body:
            imported = []
            if isinstance(node, ast.Import):
                for alias in node.names:
                    bindings[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]
                    imported.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    parents = package.split(".") if package else []
                    if node.level > len(parents):
                        self.limitations.append(f"Unresolved relative import at {path}:{node.lineno}.")
                        continue
                    prefix = parents[:len(parents) - node.level + 1]
                    base = ".".join([*prefix, *([base] if base else [])])
                imported.append(base)
                for alias in node.names:
                    if alias.name != "*":
                        full = f"{base}.{alias.name}" if base else alias.name
                        bindings[alias.asname or alias.name] = full
                        imported.append(full)
            for name in dict.fromkeys(imported):
                target = self.modules.get(name)
                if target and target != path:
                    self.dependencies.append(Dependency(path, target,
                        SourceLocation(file_path=path, start_line=node.lineno, end_line=node.end_lineno)))
        # Rebound module names cannot be treated as their original import binding.
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bindings.pop(node.name, None)
                continue
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                for child in scoped_nodes(node):
                    if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                        bindings.pop(child.id, None)

    def call_name(self, path, node: ast.Call, symbol: Symbol) -> str | None:
        parts: list[str] = []
        value = node.func
        while isinstance(value, ast.Attribute):
            parts.insert(0, value.attr)
            value = value.value
        if not isinstance(value, ast.Name):
            return None
        parts.insert(0, value.id)
        assert isinstance(symbol.node, (ast.FunctionDef, ast.AsyncFunctionDef))
        args = symbol.node.args
        shadows = {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
        shadows.update(a.arg for a in (args.vararg, args.kwarg) if a)
        shadows.update(n.id for n in scoped_nodes(symbol.node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store))
        shadows.update(n.name for n in ast.walk(symbol.node)
                       if n is not symbol.node and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
        if parts[0] in shadows:
            return None
        binding = self.bindings[path].get(parts[0])
        return ".".join([binding or parts[0], *parts[1:]])

    def _index_calls(self):
        targets: dict[str, list[str]] = {}
        for symbol in self.symbols.values():
            if isinstance(symbol.node, (ast.FunctionDef, ast.AsyncFunctionDef)) and "." not in symbol.qualified_name:
                targets.setdefault(f"{symbol.module}.{symbol.name}", []).append(symbol.id)
        for symbol in self.functions():
            self.calls[symbol.id] = set()
            for node in scoped_nodes(symbol.node):
                if not isinstance(node, ast.Call):
                    continue
                name = self.call_name(symbol.location.file_path, node, symbol)
                candidates = targets.get(name, []) if name is not None else []
                if not candidates and name and "." not in name:
                    candidates = targets.get(f"{symbol.module}.{name}", [])
                if len(candidates) == 1:
                    self.calls[symbol.id].add(candidates[0])
                else:
                    self.unresolved_calls += 1

    def functions(self):
        return [s for s in self.symbols.values() if isinstance(s.node, (ast.FunctionDef, ast.AsyncFunctionDef))]

    def get_symbol(self, symbol_id: str) -> Symbol:
        return self.symbols[symbol_id]

    def get_callers(self, symbol_id: str) -> list[Symbol]:
        self.get_symbol(symbol_id)
        return [self.symbols[s] for s, targets in self.calls.items() if symbol_id in targets]

    def get_callees(self, symbol_id: str) -> list[Symbol]:
        self.get_symbol(symbol_id)
        return [self.symbols[s] for s in sorted(self.calls.get(symbol_id, set()))]

    def get_module_dependencies(self, path: str) -> list[str]:
        return sorted({edge.target for edge in self.dependencies if edge.source == path})

    def get_related_tests(self, symbol_id: str) -> list[str]:
        from sentinel.repository import is_test_file
        path = self.get_symbol(symbol_id).location.file_path
        return sorted({edge.source for edge in self.dependencies if edge.target == path and is_test_file(edge.source)})

    def get_source(self, path: str, start_line: int, end_line: int) -> str:
        lines = self.files[path].splitlines()
        if not 1 <= start_line <= end_line <= len(lines):
            raise ValueError(f"Source range out of bounds: {path}:{start_line}-{end_line}")
        return "\n".join(lines[start_line - 1:end_line])
