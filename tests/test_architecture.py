#!/usr/bin/env python3
"""相依規則檢查：內層不准引用外層。

分層本身只是目錄名稱，擋不住任何人 —— 真正讓架構站得住的是這支測試。
少了它，某天 domain 裡多一行 `from mrt.infrastructure import mcworld`
也不會有人發現，分層就退化成純粹的檔案搬家。

用法: ./.venv/bin/python tests/test_architecture.py
"""
import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mrt import config

# 每一層可以引用哪些層（config 是所有層都能用的組態，不列入）
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
    """這個檔案 import 了哪幾層。"""
    tree = ast.parse(open(path).read(), path)
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

    print(f"檢查 {checked} 個模組")
    for layer in sorted(ALLOWED):
        allowed = ", ".join(sorted(ALLOWED[layer])) or "（只能用標準函式庫）"
        print(f"  {layer:<15} 可引用: {allowed}")

    if bad:
        print("\n違反相依規則:")
        print("\n".join(bad))
        return 1
    print("\n相依方向全部正確：沒有內層引用外層")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
