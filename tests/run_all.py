#!/usr/bin/env python3
"""Run every test that does not need a generated world.

The scripts under tools/ are not included: they need a world save before they can check
anything; see docs/verification.md.

Usage: ./.venv/bin/python tests/run_all.py
"""
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = ["test_architecture.py", "test_geometry.py", "test_alignment.py",
         "test_rails.py", "test_landmarks.py", "test_walk.py",
         "test_concourse.py", "test_exits.py", "test_tunnel_layers.py",
         "test_side_station.py", "test_transfer.py", "test_elevated_exits.py",
         "test_ground_gate.py", "test_stacked.py", "test_network.py",
         "test_heightmap.py", "test_spawn.py", "test_datapack.py",
         "test_signage.py", "test_attractions.py"]
# Each attraction's own test (one per module under application/attractions/) is collected
# automatically, so adding an attraction does not require editing this list
TESTS += sorted(os.path.basename(p) for p in glob.glob(os.path.join(HERE, "test_attr_*.py")))


def main():
    failed = []
    for t in TESTS:
        # The flush is required: when piped, the parent process is block-buffered while the
        # child writes directly, and without it the headings in the CI log do not line up
        # with each test's output.
        print(f"\n{'=' * 60}\n{t}\n{'=' * 60}", flush=True)
        r = subprocess.run([sys.executable, os.path.join(HERE, t)])
        if r.returncode != 0:
            failed.append(t)

    print(f"\n{'=' * 60}", flush=True)
    if failed:
        print(f"{len(failed)} failed: {', '.join(failed)}")
        return 1
    print(f"All {len(TESTS)} tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
