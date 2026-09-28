#!/usr/bin/env python3
"""Dependency rule check: an inner layer must not import an outer one.

The layers themselves are only directory names and stop nobody; this test is what
actually holds the architecture up. Without it, a line such as
`from mrt.infrastructure import mcworld` could one day appear in domain unnoticed, and
the layering would degrade into nothing more than moving files around.

Usage: ./.venv/bin/python tests/test_architecture.py
"""
import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt import config

# Which layers each layer may import (config is configuration every layer may use, so it is
# not listed)
ALLOWED = {
    "ports":          set(),
    "domain":         {"domain", "ports"},
    "application":    {"domain", "ports", "application"},
    "infrastructure": {"ports", "infrastructure"},
    "adapters":       {"domain", "ports", "infrastructure", "adapters"},
}

LAYERS = set(ALLOWED)


def layer_of(rel):
    """mrt/domain/rails.py -> "domain" """
    parts = rel.split(os.sep)
    return parts[1] if len(parts) > 1 and parts[1] in LAYERS else None


def imported_layers(path):
    """Return the layers this file imports."""
    tree = ast.parse(open(path, encoding="utf-8").read(), path)
    found = set()
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module]
        for n in names:
            bits = n.split(".")
            if bits[0] == "mrt" and len(bits) > 1 and bits[1] in LAYERS:
                found.add((bits[1], n))
    return found


def main():
    root = config.ROOT
    bad = []
    checked = 0
    for dirpath, _, files in os.walk(os.path.join(root, "mrt")):
        for fn in sorted(files):
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, root)
            layer = layer_of(rel)
            if layer is None:
                continue
            checked += 1
            for other, full in sorted(imported_layers(path)):
                if other not in ALLOWED[layer]:
                    bad.append(f"  {rel}  ({layer}) -> {full}  ({other})")

    print(f"Checked {checked} modules")
    for layer in sorted(ALLOWED):
        allowed = ", ".join(sorted(ALLOWED[layer])) or "(standard library only)"
        print(f"  {layer:<15} may import: {allowed}")

    if bad:
        print("\nDependency rule violations:")
        print("\n".join(bad))
        return 1
    print("\nAll dependencies point the right way: no inner layer imports an outer one")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
