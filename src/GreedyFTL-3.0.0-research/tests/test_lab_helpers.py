import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host"))
sys.path.insert(0, str(ROOT / "tools"))
from experiment import SerialCapture, generate_job, parser, snapshot
from uart_bridge import forward_once, permitted
from apply_sdk_sources import main as apply_main
from check_allocation_trace import main as trace_main


class LabHelperTests(unittest.TestCase):
    def test_bridge_read_only_payload_and_client_filter(self):
        class Device:
            in_waiting = 5
            def read(self, n):
                return b"GC\r\n!"
            def write(self, data):
                raise AssertionError("Bridge must never write UART")
        class Client:
            data = b""
            def sendall(self, data):
                self.data += data
        client = Client()
        self.assertEqual(forward_once(Device(), client), 5)
        self.assertEqual(client.data, b"GC\r\n!")
        self.assertTrue(permitted("192.168.1.20", "192.168.1.20", False))
        self.assertFalse(permitted("192.168.1.21", "192.168.1.20", False))
        self.assertFalse(permitted("192.168.1.20", "192.168.1.20", True))

    def test_capture_opens_url_and_reassembles_stats(self):
        payload = b"noise\r\n=== RESEARCH_STATS_BEGIN ===\r\ngc_count=0x1\r\n=== RESEARCH_STATS_END ==="
        class Device:
            closed = False
            chunks = [payload[:40], payload[40:]]
            def read(self, n):
                if self.chunks:
                    return self.chunks.pop(0)
                import time
                time.sleep(.01)
                return b""
            def close(self):
                self.closed = True
        device = Device()
        opener = unittest.mock.Mock(return_value=device)
        with tempfile.TemporaryDirectory() as tmp, \
                patch.dict(sys.modules, {"serial": types.SimpleNamespace(serial_for_url=opener)}):
            capture = SerialCapture("socket://192.168.1.10:8765", 115200, Path(tmp) / "uart.log")
            try:
                text = capture.wait_block(0, "=== RESEARCH_STATS_END ===", 1,
                                          "=== RESEARCH_STATS_BEGIN ===")
                self.assertTrue(text.startswith("=== RESEARCH_STATS_BEGIN ==="))
                self.assertIn("gc_count=0x1", text)
            finally:
                capture.close()
            self.assertEqual(opener.call_args.args[0], "socket://192.168.1.10:8765")
            self.assertTrue(device.closed)

    def test_verification_and_allocation_jobs(self):
        args = parser().parse_args(["--namespace", "/dev/nvme0n1", "--controller", "/dev/nvme0",
                                   "--policy", "channel-first", "--size-bytes", "67108864",
                                   "--output", "unused", "--phase", "allocation"])
        verify = generate_job(args, "verify-read", Path("/results"))
        self.assertIn("rw=write", verify)
        self.assertIn("verify_only=1", verify)
        self.assertNotIn("time_based", verify)
        allocation = generate_job(args, "allocation", Path("/results"))
        self.assertIn("rw=write", allocation)
        self.assertNotIn("verify=", allocation)
        self.assertNotIn("log_issue_time", generate_job(args, "measure", Path("/results")))

    def test_sdk_preview_then_apply_preserves_hardware_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = base / "sdk-src"
            (target / "nvme").mkdir(parents=True)
            for name in ("address_translation.c", "ftl_config.h", "main.c", "nvme/nvme_io_cmd.c"):
                (target / name).write_text("BOARD_ORIGINAL\n")
            with patch("sys.argv", ["apply", "--sdk-src", str(target), "--report", str(base / "preview")]):
                apply_main()
            self.assertEqual((target / "address_translation.c").read_text(), "BOARD_ORIGINAL\n")
            with patch("sys.argv", ["apply", "--sdk-src", str(target), "--report", str(base / "backup"),
                                    "--apply", "--confirm-reviewed-diff"]):
                apply_main()
            self.assertEqual((target / "address_translation.c").read_bytes(), (ROOT / "address_translation.c").read_bytes())
            self.assertEqual((target / "ftl_config.h").read_text(), "BOARD_ORIGINAL\n")
            self.assertEqual((target / "main.c").read_text(), "BOARD_ORIGINAL\n")
            self.assertEqual((base / "backup/originals/address_translation.c").read_text(), "BOARD_ORIGINAL\n")
            self.assertTrue(json.loads((base / "backup/manifest.json").read_text())["applied"])

    def test_trace_uses_firmware_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            trace, stats = base / "uart.log", base / "stats.txt"
            trace.write_text("\n".join(f"ALLOC n={i} ch={i%2} way={(i//2)%2} block=1 page=0" for i in range(4)))
            stats.write_text("=== RESEARCH_STATS_BEGIN ===\nallocation_policy=channel-first\n"
                             "user_channels=0x2\nuser_ways=0x2\nuser_pages_per_block=0x4\n"
                             "=== RESEARCH_STATS_END ===\n")
            argv = ["trace", str(trace), "--policy", "channel-first", "--stats", str(stats)]
            with patch("sys.argv", argv):
                trace_main()
            with patch("sys.argv", argv + ["--channels", "8"]), patch("sys.stderr"):
                with self.assertRaises(SystemExit):
                    trace_main()


if __name__ == "__main__":
    unittest.main()
