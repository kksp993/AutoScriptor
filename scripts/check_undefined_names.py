"""Find names a module reads but never defines.

A static import scan answers "is this imported and unused". It cannot answer the
reverse, which is the one that breaks at runtime: a name that is *used* but no
longer imported, defined, or built in. `symtable` gives per-scope symbol tables,
so globals read by a function can be checked against the module namespace and
the builtins.

Usage:

    .venv\\Scripts\\python.exe -X utf8 scripts\\check_undefined_names.py [paths...]

Exits 1 and prints `path:line name` for every unresolved global read.
"""
from __future__ import annotations

import ast
import builtins
import pathlib
import symtable
import sys


DEFAULT_PATHS = ("backend", "orchestrator", "tasks", "ZmxyOL", "AutoScriptor")
SKIP_PARTS = {"__pycache__", ".venv", ".venv-gpu-ocr", "refs", "vendor", "node_modules"}


def has_star_import(tree: ast.Module) -> bool:
    """`from x import *` binds names symtable cannot enumerate, at any scope."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if any(alias.name == "*" for alias in node.names):
                return True
    return False


def walk(table: symtable.SymbolTable):
    yield table
    for child in table.get_children():
        yield from walk(child)


def collect_unresolved(source: str, filename: str) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(source, filename)
    except SyntaxError as error:
        return [(error.lineno or 0, f"<syntax error: {error.msg}>")]

    if has_star_import(tree):
        # Scripts reach the authoring API through `from AutoScriptor import *`, so
        # any name may be bound at runtime. Those modules are counted as skipped
        # rather than reported as broken.
        return []

    try:
        top = symtable.symtable(source, filename, "exec")
    except SyntaxError as error:
        return [(error.lineno or 0, f"<syntax error: {error.msg}>")]

    module_names = {symbol.get_name() for symbol in top.get_symbols()}
    builtin_names = set(dir(builtins))
    unresolved: list[tuple[int, str]] = []

    for table in walk(top):
        if table.get_type() == "module":
            continue
        # free variables of a nested scope belong to the enclosing function, which
        # symtable already marks there; only true globals are checked here
        for symbol in table.get_symbols():
            if not symbol.is_global():
                continue
            name = symbol.get_name()
            if name.startswith("__") and name.endswith("__"):
                continue
            if name in module_names or name in builtin_names:
                continue
            # Symbol carries no line in 3.10; the enclosing scope's line is enough
            # to find the reference.
            unresolved.append((table.get_lineno() or 0, name))

    return unresolved


def main(argv: list[str]) -> int:
    root = pathlib.Path(__file__).resolve().parents[1]
    targets = argv[1:] or list(DEFAULT_PATHS)

    files: list[pathlib.Path] = []
    for target in targets:
        path = root / target
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(path.rglob("*.py")))

    problems = 0
    skipped = 0
    for path in files:
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        try:
            source = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        try:
            if has_star_import(ast.parse(source, str(path))):
                skipped += 1
                continue
        except SyntaxError:
            pass
        for line, name in collect_unresolved(source, str(path)):
            print(f"{path.relative_to(root)}:{line}  {name}")
            problems += 1

    print(f"\nscanned {len(files)} files, {problems} unresolved name(s), {skipped} skipped (star import)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
