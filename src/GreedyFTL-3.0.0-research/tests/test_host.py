import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
sys.path.insert(0, str(ROOT / "tools"))
from experiment import generate_job, parser, main, validate_device
from telemetry import derived_stats, parse_stats, parse_trace, gc_intervals
from analyze import load_latency
from check_allocation_trace import validate


class HostTests(unittest.TestCase):
    def test_dry_run_never_issues_device_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "plan"
            argv = ["experiment.py", "--namespace", "/dev/nvme0n1", "--controller", "/dev/nvme0",
                    "--policy", "channel-first", "--size-bytes", "65536", "--output", str(destination)]
            with patch("sys.argv", argv), patch("experiment.command", side_effect=AssertionError("device command")), \
                    patch("experiment.validate_device", side_effect=AssertionError("device access")):
                main()
            manifest = json.loads((destination / "manifest.json").read_text())
            self.assertTrue(manifest["dry_run"])
            self.assertFalse(manifest["valid"])
            self.assertTrue((destination / "measure.fio").exists())

    def test_device_authority_guards_before_device_access(self):
        with patch("experiment.sys.platform", "darwin"):
            with self.assertRaisesRegex(RuntimeError, "Linux"):
                validate_device("/dev/nvme0n1", "/dev/nvme0", "/dev/nvme0n1")
        with patch("experiment.sys.platform", "linux"):
            with self.assertRaisesRegex(RuntimeError, "whole"):
                validate_device("/dev/nvme0n1p1", "/dev/nvme0", "/dev/nvme0n1p1")
            with self.assertRaisesRegex(RuntimeError, "allow-device"):
                validate_device("/dev/nvme0n1", "/dev/nvme0", None)

    def test_stats_latest_complete_not_mixed(self):
        text = "=== RESEARCH_STATS_BEGIN ===\ngc_count=0x01\n=== RESEARCH_STATS_END ===\n"
        text += "=== RESEARCH_STATS_BEGIN ===\ngc_count=0x02\nallocation_policy=way-first\n=== RESEARCH_STATS_END ===\n"
        text += "=== RESEARCH_STATS_BEGIN ===\ngc_count=0xff\n"
        self.assertEqual(parse_stats(text)["gc_count"], 2)
        self.assertEqual(parse_stats(text)["allocation_policy"], "way-first")

    def test_samples_not_interval_means(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "probe_clat.5.log"
            log.write_text("0,1000000,0,4096\n100,2000000,0,4096\n900,5000000,0,4096\n2000,9000000,0,4096\n")
            windows, samples = load_latency(Path(tmp), 1)
            self.assertEqual(windows[0]["p99_ms"], 5)
            self.assertEqual(windows[1]["count"], 0)
            self.assertEqual(windows[2]["p99_ms"], 9)
            self.assertEqual(len(samples), 4)
            log.write_text("0,1000000,0,0\n")
            with self.assertRaises(ValueError):
                load_latency(Path(tmp), 1)

    def test_trace_and_time_units(self):
        stats = {"timer_counts_per_second": 1000, "stats_epoch_ticks": 100}
        events = parse_trace("TRACE,1,0,1,0x64,0x12,0x0\nTRACE,2,0,1,0xc8,0x3,0x64\n", stats)
        intervals, unmatched = gc_intervals(events, 1000)
        self.assertEqual(unmatched, 0)
        self.assertEqual(intervals[0]["duration_ms"], 100)
        self.assertEqual(intervals[0]["migration_pages"], 3)

    def test_wa_bytes_and_denominator(self):
        stats = {"host_logical_write_bytes": 16384, "host_nand_program_pages": 1,
                 "gc_nand_program_pages": 1, "nand_page_bytes": 16384}
        self.assertEqual(derived_stats(stats)["write_amplification"], 2)

    def test_concurrent_probe_reporting(self):
        args = parser().parse_args(["--namespace", "/dev/nvme0n1", "--controller", "/dev/nvme0",
                                   "--policy", "way-first", "--size-bytes", "65536", "--output", "unused"])
        job = generate_job(args, "measure", Path("/results"))
        self.assertIn("new_group=1", job)
        self.assertIn("new_group=1", job.split("[latency-probe]")[1])
        self.assertNotIn("new_group=1", job.split("[latency-probe]")[0])
        self.assertNotIn("stonewall", job)
        self.assertIn("log_avg_msec=0", job)
        self.assertIn("ramp_time=0", job)
        self.assertIn("log_entries=1000000", job)
        self.assertIn("thread=1", job)
        args.worker_model = "processes"
        self.assertIn("thread=0", generate_job(args, "measure", Path("/results")))
        self.assertFalse(args.execute)

    def test_board_trace_detects_wrong_policy(self):
        text = "\n".join(f"ALLOC n={i} ch={i%2} way={(i//2)%2} block=1 page=0" for i in range(4))
        self.assertEqual(validate(text, "channel-first", 2, 2, 4), 4)
        with self.assertRaises(ValueError):
            validate(text, "way-first", 2, 2, 4)
        with self.assertRaises(ValueError):
            validate("ALLOC n=0 ch=0 way=0 block=1 page=0", "page-first", 2, 2, 4)


if __name__ == "__main__":
    unittest.main()
