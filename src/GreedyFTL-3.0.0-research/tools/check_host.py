#!/usr/bin/env python3
"""Host-only verification. Does not build an ARM ELF or access any SSD."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"], cwd=ROOT, check=True)
    cc = os.environ.get("CC") or shutil.which("cc") or shutil.which("clang")
    if not cc:
        raise RuntimeError("A host C compiler is required (cc/clang/gcc).")
    files = ["ftl_config.c", "address_translation.c", "request_allocation.c", "request_schedule.c",
             "research_stats.c", "garbage_collection.c", "data_buffer.c", "request_transform.c",
             "nvme/nvme_io_cmd.c", "nvme/nvme_admin_cmd.c"]
    for policy in ("CHANNEL_FIRST", "WAY_FIRST", "PAGE_FIRST"):
        subprocess.run([cc, "-std=gnu99", "-fsyntax-only", "-Itests/bsp_stubs",
                        "-Wno-int-to-pointer-cast", "-Wno-pointer-to-int-cast",
                        f"-DALLOCATION_POLICY_{policy}", *files], cwd=ROOT, check=True)
    print("PASS: modified firmware C syntax for all policies (BSP stubs; not an ARM build)")
    with tempfile.TemporaryDirectory() as tmp:
        executable = str(Path(tmp) / "telemetry")
        for level in (0, 1, 2):
            subprocess.run([cc, "-std=c99", "-Wall", "-Wextra", "-DRESEARCH_HOST_TEST",
                            f"-DRESEARCH_TRACE_LEVEL={level}", "research_stats.c", "tests/test_research.c", "-o", executable], cwd=ROOT, check=True)
            result = subprocess.run([executable], capture_output=True, text=True, check=True)
            print(result.stdout.splitlines()[-1] + f" (trace level {level})")
        for channels, ways in ((1, 1), (2, 3), (8, 8)):
            for policy in ("CHANNEL_FIRST", "WAY_FIRST", "PAGE_FIRST"):
                subprocess.run([cc, "-std=c99", "-Wall", "-Wextra", f"-DUSER_CHANNELS={channels}",
                                f"-DUSER_WAYS={ways}", f"-DALLOCATION_POLICY_{policy}",
                                "tests/test_allocation.c", "-o", executable], cwd=ROOT, check=True)
                result = subprocess.run([executable], capture_output=True, text=True, check=True)
                print(f"{channels}Ch/{ways}Way {policy}: {result.stdout.strip()}")


if __name__ == "__main__":
    main()
