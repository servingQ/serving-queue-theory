"""The import direction of `src/`: `theory` computes the expected values
without serQ (the checked party does not compute its own), `sim` runs serQ
and does not know the checks, and nothing imports `report`."""

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
STDLIB = set(sys.stdlib_module_names)
THEORY = STDLIB | {"numpy", "fmt", "constants", "theory"}
LEAF = STDLIB | {"numpy"}


def modules():
    """`(module, [(imported module, line)])` for every module under `src/`."""
    for path in sorted(SRC.rglob("*.py")):
        parts = path.relative_to(SRC).with_suffix("").parts
        name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        imports = []
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            if isinstance(node, ast.Import):
                imports += [(a.name, node.lineno) for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                imports.append(("." * node.level + (node.module or ""), node.lineno))
        yield name, imports


def violations() -> list[str]:
    out = []
    for name, imports in modules():
        layer = name.split(".")[0]
        for imported, line in imports:
            top = imported.split(".")[0]
            if imported.startswith("."):
                why = "a relative import (use `from theory.dist import ...`)"
            elif top == "report":
                why = "nothing imports report"
            elif layer == "theory" and top not in THEORY:
                why = "theory imports only the standard library, numpy, fmt, constants and theory"
            elif layer == "sim" and top == "checks":
                why = "sim does not import checks"
            elif layer in ("fmt", "constants") and top not in LEAF:
                why = f"{layer} is a leaf"
            else:
                continue
            out.append(f"{name} (line {line}) imports {imported}: {why}")
    return out


def test_modules_are_found():
    names = {name for name, _ in modules()}
    assert {"theory.dist", "sim.serq", "checks", "report.paper_tables"} <= names


def test_imports_follow_the_layers():
    bad = violations()
    assert not bad, "\n".join(bad)
