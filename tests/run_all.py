#!/usr/bin/env python3
"""跑完所有不需要產生世界的測試。

不含 tools/ 底下那幾支 —— 它們要先有存檔才驗得了，見 README「驗證」。

用法: ./.venv/bin/python tests/run_all.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = ["test_architecture.py", "test_geometry.py", "test_alignment.py",
         "test_rails.py", "test_landmarks.py", "test_walk.py",
         "test_concourse.py", "test_exits.py", "test_tunnel_layers.py",
         "test_side_station.py", "test_transfer.py", "test_elevated_exits.py",
         "test_ground_gate.py", "test_stacked.py"]


def main():
    failed = []
    for t in TESTS:
        # flush 是必要的：接管道時父行程是 block buffered、子行程直接寫，
        # 少了它 CI log 裡標題會跟該支測試的輸出對不起來。
        print(f"\n{'=' * 60}\n{t}\n{'=' * 60}", flush=True)
        r = subprocess.run([sys.executable, os.path.join(HERE, t)])
        if r.returncode != 0:
            failed.append(t)

    print(f"\n{'=' * 60}", flush=True)
    if failed:
        print(f"{len(failed)} 支失敗: {', '.join(failed)}")
        return 1
    print(f"{len(TESTS)} 支測試全部通過")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
