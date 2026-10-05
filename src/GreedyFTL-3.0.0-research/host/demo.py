#!/usr/bin/env python3
"""Generate explicitly SYNTHETIC fixtures to test analysis without a board."""
import argparse
import json
import math
from pathlib import Path
import random
import subprocess
import sys

from telemetry import empirical_percentile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    runs = []
    for policy, amplitude in (("channel-first", 7), ("way-first", 4), ("page-first", 5)):
        run = args.output / policy
        run.mkdir()
        runs.append(str(run))
        manifest = {"policy": policy, "mode": "gc", "repeat": 1, "valid": True,
                    "synthetic": True, "note": "FAKE TEST FIXTURE, NOT AN OPENSSD EXPERIMENT"}
        (run / "manifest.json").write_text(json.dumps(manifest))
        rng = random.Random(7)
        samples = []
        with (run / "probe_clat.5.log").open("w") as stream:
            for t in range(120000):
                seconds = t / 1000
                spike = sum(amplitude * math.exp(-.5 * ((seconds - c) / 1.2) ** 2) for c in (24, 55, 87, 108))
                latency = .45 + rng.random() * .2 + (spike if rng.random() < .08 else 0)
                samples.append(latency)
                stream.write(f"{t},{int(latency * 1e6)},0,4096,0,0,0\n")
        op = {"io_bytes": 120000 * 4096, "total_ios": 120000, "iops": 1000,
              "bw_bytes": 4096000, "clat_ns": {"percentile": {
                  f"{q:.6f}": empirical_percentile(samples, q) * 1e6 for q in (50, 99, 99.9)}}}
        (run / "fio.json").write_text(json.dumps({"jobs": [{"jobname": "latency-probe", "error": 0, "read": op}]}))
        stats = {"research_schema": 2, "gc_count": 4, "gc_migration_pages": 80,
                 "gc_execution_cycles": 16000000, "gc_max_execution_cycles": 4000000,
                 "gc_read_pages": 80, "gc_erase_count": 4, "gc_failed_req_count": 0,
                 "host_failed_req_count": 0, "gc_die_blocked_req_count": 50,
                 "gc_die_blocked_cycles": 100000, "gc_channel_blocked_req_count": 20,
                 "gc_channel_blocked_cycles": 20000, "host_nand_req_count": 100000,
                 "host_queue_wait_cycles": 500000, "host_logical_write_bytes": 163840000,
                 "host_nand_program_pages": 10000, "gc_nand_program_pages": 80,
                 "nand_page_bytes": 16384, "timer_counts_per_second": 1000000,
                 "stats_epoch_ticks": 0, "trace_dropped": 0}
        block = "=== RESEARCH_STATS_BEGIN ===\n" + "\n".join(f"{k}=0x{v:016x}" for k, v in stats.items())
        block += f"\nallocation_policy={policy}\n=== RESEARCH_STATS_END ===\n"
        (run / "window.stats.txt").write_text(block)
        (run / "drained.stats.txt").write_text(block)
        events = ["=== RESEARCH_TRACE_BEGIN ==="]
        for start in (22, 53, 85, 106):
            events += [f"TRACE,1,0,0,0x{start * 1000000:x},0x1,0x0",
                       f"TRACE,2,0,0,0x{(start+4)*1000000:x},0x14,0x3d0900"]
        events += ["=== RESEARCH_TRACE_END ==="]
        (run / "trace.txt").write_text("\n".join(events))
    subprocess.run([sys.executable, str(Path(__file__).with_name("analyze.py")), *runs,
                    "--output", str(args.output / "figures")], check=True)
    print("SYNTHETIC demo only; policy ordering is deliberately invented.")


if __name__ == "__main__":
    main()
