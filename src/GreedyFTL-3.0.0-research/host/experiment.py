#!/usr/bin/env python3
"""Linux fio/NVMe runner. Default: generate plans only, never touch a device."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import threading
import time

POLICIES = ("channel-first", "way-first", "page-first")


def command(argv, output=None, timeout=None):
    started = time.monotonic_ns()
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if output:
        Path(output).write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {argv}\n{result.stderr}")
    return result.stdout, (started, time.monotonic_ns())


def children(node):
    yield node
    for child in node.get("children", []):
        yield from children(child)


def validate_device(namespace, controller, allow_device, expected_pci_id="10ee:7028"):
    """No automatic unmount, format, discard, partitioning, or firmware upload."""
    if sys.platform != "linux":
        raise RuntimeError("Execution requires a Linux host connected to Cosmos+.")
    ns = Path(namespace).resolve()
    ctl = Path(controller).resolve()
    match = re.fullmatch(r"nvme(\d+)n(\d+)", ns.name)
    if not match or ctl != Path("/dev") / f"nvme{match[1]}":
        raise RuntimeError("Use a whole /dev/nvmeXnY namespace and its /dev/nvmeX controller.")
    if allow_device != str(ns):
        raise RuntimeError(f"Execution requires --allow-device {ns} (contents will be overwritten).")
    if not stat.S_ISBLK(ns.stat().st_mode):
        raise RuntimeError("The namespace is not a block device.")
    if os.geteuid() != 0:
        raise RuntimeError("Execution needs root access to the test namespace and NVMe admin commands.")
    pci = Path("/sys/class/nvme") / ctl.name / "device"
    try:
        actual_pci_id = ":".join((pci / name).read_text().strip().lower().removeprefix("0x")
                                 for name in ("vendor", "device"))
    except OSError as exc:
        raise RuntimeError("Cannot verify PCI identity of the NVMe controller.") from exc
    if actual_pci_id != expected_pci_id.lower():
        raise RuntimeError(f"Controller PCI ID {actual_pci_id} != expected Cosmos+ {expected_pci_id}; "
                           "do not use an OS/commercial SSD as DUT.")
    tree = json.loads(command(["lsblk", "--json", "--paths", "--output", "NAME,MOUNTPOINTS", str(ns)])[0])
    nodes = [n for top in tree["blockdevices"] for n in children(top)]
    swap_devices = {str(Path(line.split()[0]).resolve()) for line in
                    Path("/proc/swaps").read_text().splitlines()[1:]}
    for node in nodes:
        if any(node.get("mountpoints") or []):
            raise RuntimeError(f"Mounted target/partition: {node['name']}")
        if str(Path(node["name"]).resolve()) in swap_devices:
            raise RuntimeError(f"Target/partition is swap: {node['name']}")
        holders = Path("/sys/class/block") / Path(node["name"]).name / "holders"
        if holders.exists() and any(holders.iterdir()):
            raise RuntimeError(f"Target/partition has device-mapper/RAID holders: {node['name']}")
    return int(command(["blockdev", "--getsize64", str(ns)])[0])


def generate_job(args, phase, run_dir):
    base = ["[global]", f"filename={args.namespace}", "ioengine=libaio", "direct=1",
            f"thread={int(args.worker_model == 'threads')}",
            f"size={args.size_bytes}", "offset=0", "randrepeat=1", f"randseed={args.seed}",
            "group_reporting=1", "clat_percentiles=1", "lat_percentiles=0",
            "percentile_list=50:95:99:99.9:99.99", "exitall_on_error=1"]
    if phase == "fill":
        return "\n".join(base + ["[fill]", "rw=write", "bs=16k", "numjobs=1", "iodepth=32"]) + "\n"
    if phase == "precondition":
        return "\n".join(base + ["[overwrite]", "rw=randwrite", "bs=16k", "numjobs=1", "iodepth=32",
                                  f"io_size={args.size_bytes * args.overwrite_passes}"]) + "\n"
    if phase in ("verify-write", "verify-read", "allocation"):
        # Must exceed the DRAM data cache when used for physical-media validation.
        base = [line for line in base if not line.startswith("size=")]
        base += [f"size={min(args.size_bytes, 64 * 1024 * 1024)}", "[integrity]", "bs=16k",
                 "numjobs=1", "iodepth=16"]
        if phase == "allocation":
            return "\n".join(base + ["rw=write"]) + "\n"
        base += ["verify=crc32c", "verify_fatal=1"]
        if phase == "verify-write":
            base += ["rw=write", "do_verify=0"]
        else:
            # verify_only replaces a write workload with verification reads.
            base += ["rw=write", "verify_only=1"]
        return "\n".join(base) + "\n"
    duration = args.warmup_seconds if phase == "warmup" else args.runtime
    base += ["time_based=1", f"runtime={duration}", "ramp_time=0"]
    if args.mode == "gc":
        base += ["[gc-writer]", "rw=randwrite", "bs=16k", f"numjobs={args.writer_jobs}",
                 f"iodepth={args.writer_qd}"]
        if args.writer_iops:
            base.append(f"rate_iops={args.writer_iops}")  # per writer job
    base += ["[latency-probe]", "rw=randread", "bs=4k", "numjobs=1",
             f"iodepth={args.probe_qd}", f"rate_iops={args.probe_iops}"]
    if args.mode == "gc":
        base += ["new_group=1"]  # belongs to probe; separate reporting, concurrent execution
    if phase == "measure":
        prefix = run_dir / "probe"
        # Individual samples: computing P99 from interval MEANS is invalid.
        base += [f"write_lat_log={prefix}", "log_avg_msec=0", "log_offset=1",
                 "per_job_logs=1", f"log_entries={args.log_entries}"]
    return "\n".join(base) + "\n"


class SerialCapture:
    def __init__(self, port, baud, destination):
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("Install host/requirements.txt for UART capture.") from exc
        self.device = serial.serial_for_url(port, baudrate=baud, timeout=.1)
        self.output = open(destination, "wb")
        self.lock = threading.Condition()
        self.transcript = bytearray()
        self.stopped = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        try:
            while not self.stopped.is_set():
                data = self.device.read(4096)
                if data:
                    self.output.write(data)
                    self.output.flush()
                    with self.lock:
                        self.transcript.extend(data)
                        self.lock.notify_all()
        except Exception as exc:
            self.error = exc
            with self.lock:
                self.lock.notify_all()

    def position(self):
        with self.lock:
            return len(self.transcript)

    def wait_block(self, start, end, timeout, begin=None):
        deadline = time.monotonic() + timeout
        with self.lock:
            while True:
                payload = bytes(self.transcript[start:])
                if end.encode() in payload:
                    if begin:
                        payload = payload[payload.index(begin.encode()):]
                    return payload[:payload.index(end.encode()) + len(end)].decode(errors="replace")
                if self.error:
                    raise RuntimeError(f"UART capture failed: {self.error}")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(f"UART missing {end}; check firmware/baud/serial connection.")
                self.lock.wait(min(.2, remaining))

    def close(self):
        self.stopped.set()
        self.thread.join(2)
        self.device.close()
        self.output.close()


def admin(args, opcode, name, run_dir, cdw10=None):
    argv = ["nvme", "admin-passthru", args.controller, f"--opcode={opcode}",
            f"--timeout={args.uart_timeout * 1000}"]
    if cdw10 is not None:
        argv.append(f"--cdw10={cdw10}")
    _, bracket = command(argv, run_dir / f"{name}.admin.txt", timeout=args.uart_timeout + 5)
    return bracket


def flush(args, run_dir, name):
    return command(["nvme", "flush", args.namespace], run_dir / f"{name}.flush.txt", timeout=180)[1]


def snapshot(args, capture, run_dir, name):
    start = capture.position()
    deadline = time.monotonic() + 30
    while True:
        try:
            admin(args, "0xc1", name, run_dir)
            break
        except RuntimeError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.05)  # only after fio stopped; pending NAND work may drain
    data = capture.wait_block(start, "=== RESEARCH_STATS_END ===", args.uart_timeout,
                              "=== RESEARCH_STATS_BEGIN ===")
    (run_dir / f"{name}.stats.txt").write_text(data + "\n", encoding="utf-8")
    sys.path.insert(0, str(Path(__file__).parent))
    from telemetry import parse_stats
    values = parse_stats(data)
    if values.get("research_schema") != 2:
        raise RuntimeError("Firmware schema 2 is required. Build/upload this updated firmware first.")
    if values.get("allocation_policy") != args.policy:
        raise RuntimeError(f"Firmware policy {values.get('allocation_policy')} != requested {args.policy}")
    if values.get("allocation_trace_count") and args.phase not in ("inspect", "allocation"):
        raise RuntimeError("Set ALLOCATION_TRACE_COUNT=0 for latency experiments.")
    return values


def execute(args, run_dir, manifest):
    capacity = validate_device(args.namespace, args.controller, args.allow_device, args.expected_pci_id)
    if args.size_bytes > capacity:
        raise RuntimeError("size-bytes exceeds namespace capacity.")
    manifest["namespace_capacity_bytes"] = capacity
    for tool in ("fio", "nvme", "uname"):
        argv = [tool, "--version"] if tool != "uname" else ["uname", "-a"]
        manifest[f"{tool}_version"] = command(argv)[0].strip()
    # Parse-only does not issue I/O. Fail on unsupported fio options before FLUSH.
    for phase in ("fill", "precondition", "warmup", "measure", "verify-write", "verify-read", "allocation"):
        command(["fio", "--parse-only", str(run_dir / f"{phase}.fio")],
                run_dir / f"{phase}.parse.txt")
    manifest["identify_controller"] = json.loads(command(["nvme", "id-ctrl", args.controller, "-o", "json"])[0])
    capture = SerialCapture(args.serial, args.baud, run_dir / "uart.log")
    try:
        # Verify firmware before any data write. No unrelated software may access DUT.
        flush(args, run_dir, "initial")
        initial = snapshot(args, capture, run_dir, "initial")
        if args.phase == "inspect":
            manifest["firmware_inspected"] = True
            print(json.dumps(initial, indent=2))
            return
        if args.phase == "allocation":
            if not initial.get("allocation_trace_count"):
                raise RuntimeError("Allocation validation needs ALLOCATION_TRACE_COUNT > 0.")
            command(["fio", str(run_dir / "allocation.fio"), "--output-format=json+",
                     f"--output={run_dir / 'allocation.json'}"], run_dir / "allocation.console.txt")
            flush(args, run_dir, "allocation")
            counts = snapshot(args, capture, run_dir, "allocation")
            if counts["gc_failed_req_count"] or counts["host_failed_req_count"]:
                raise RuntimeError("NAND failures during allocation validation.")
            manifest["allocation_generated"] = True
            return
        if args.phase == "verify":
            command(["fio", str(run_dir / "verify-write.fio"), "--output-format=json+",
                     f"--output={run_dir / 'verify-write.json'}"], run_dir / "verify-write.console.txt")
            flush(args, run_dir, "verify")
            command(["fio", str(run_dir / "verify-read.fio"), "--output-format=json+",
                     f"--output={run_dir / 'verify-read.json'}"], run_dir / "verify-read.console.txt")
            verification = snapshot(args, capture, run_dir, "verify")
            if verification["gc_failed_req_count"] or verification["host_failed_req_count"]:
                raise RuntimeError("NAND failures during verification; inspect UART.")
            manifest["integrity_verified"] = True
            return
        if args.phase in ("prepare", "all"):
            for phase in ("fill", "precondition"):
                command(["fio", str(run_dir / f"{phase}.fio"), "--output-format=json+",
                         f"--output={run_dir / (phase + '.json')}"], run_dir / f"{phase}.console.txt")
                flush(args, run_dir, phase)
        if args.phase == "prepare":
            manifest["prepared"] = True
            return
        if args.warmup_seconds:
            command(["fio", str(run_dir / "warmup.fio"), "--output-format=json+",
                     f"--output={run_dir / 'warmup.json'}"], run_dir / "warmup.console.txt")
        flush(args, run_dir, "before_reset")
        manifest["reset_bracket_ns"] = admin(args, "0xc0", "reset", run_dir)
        manifest["start_marker_bracket_ns"] = admin(args, "0xc2", "start_marker", run_dir, 1)
        # Record host launch bounds; fio's own zero origin is slightly later.
        launch = time.monotonic_ns()
        command(["fio", str(run_dir / "measure.fio"), "--output-format=json+",
                 f"--output={run_dir / 'fio.json'}"], run_dir / "measure.console.txt")
        manifest["fio_launch_ns"] = launch
        manifest["fio_return_ns"] = time.monotonic_ns()
        manifest["end_marker_bracket_ns"] = admin(args, "0xc2", "end_marker", run_dir, 2)
        # Window includes already-created requests drained after fio returns; dirty
        # buffers are not drained yet. Separate WA accounting includes final FLUSH.
        window = snapshot(args, capture, run_dir, "window")
        flush(args, run_dir, "after_measure")
        drained = snapshot(args, capture, run_dir, "drained")
        start = capture.position()
        admin(args, "0xc3", "trace", run_dir)
        trace = capture.wait_block(start, "=== RESEARCH_TRACE_END ===", args.uart_timeout,
                                   "=== RESEARCH_TRACE_BEGIN ===")
        (run_dir / "trace.txt").write_text(trace + "\n", encoding="utf-8")
        if drained["gc_failed_req_count"] or drained["host_failed_req_count"]:
            raise RuntimeError("NAND failures invalidate this measurement; inspect UART.")
        if args.mode == "gc" and window["gc_count"] == 0:
            raise RuntimeError("No GC during measurement. Increase preconditioning/range/runtime.")
        if args.mode == "baseline" and window["gc_count"]:
            raise RuntimeError("GC occurred in baseline; this is not a No-GC control.")
        manifest["trace_complete"] = drained["trace_dropped"] == 0
        manifest["valid"] = True
    finally:
        capture.close()


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--namespace", required=True)
    p.add_argument("--controller", required=True)
    p.add_argument("--expected-pci-id", default="10ee:7028", help="Verified board PCI vendor:device ID")
    p.add_argument("--serial", default="/dev/ttyUSB0",
                   help="Local UART or socket://laptop-ip:port (trusted LAN only)")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--policy", choices=POLICIES, required=True)
    p.add_argument("--mode", choices=("gc", "baseline"), default="gc")
    p.add_argument("--phase", choices=("all", "prepare", "measure", "verify", "inspect", "allocation"), default="all")
    p.add_argument("--size-bytes", type=int, required=True)
    p.add_argument("--overwrite-passes", type=int, default=2)
    p.add_argument("--runtime", type=int, default=120)
    p.add_argument("--warmup-seconds", type=int, default=30)
    p.add_argument("--writer-jobs", type=int, default=4)
    p.add_argument("--worker-model", choices=("threads", "processes"), default="threads",
                   help="fio worker implementation; keep identical across policies")
    p.add_argument("--writer-qd", type=int, default=8)
    p.add_argument("--writer-iops", type=int, default=0, help="Per-job rate cap; 0 = uncapped")
    p.add_argument("--probe-iops", type=int, default=1000)
    p.add_argument("--probe-qd", type=int, default=1)
    p.add_argument("--seed", type=int, default=20261002)
    p.add_argument("--repeat", type=int, default=1, help="Label for an independently prepared run")
    p.add_argument("--log-entries", type=int, default=1000000)
    p.add_argument("--uart-timeout", type=int, default=120)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--firmware-elf", type=Path, help="Hash the exact uploaded ELF (not uploaded by script)")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--allow-device", help="Explicit real namespace path acknowledging overwrite")
    return p


def main():
    p = parser()
    args = p.parse_args()
    positive = (args.runtime, args.size_bytes, args.writer_jobs, args.writer_qd,
                args.probe_iops, args.probe_qd, args.repeat, args.log_entries, args.uart_timeout)
    if min(positive) <= 0 or min(args.overwrite_passes, args.warmup_seconds, args.writer_iops) < 0:
        p.error("Positive counts/rates required; warmup/overwrite/rate cap may be zero.")
    if args.size_bytes % 16384:
        p.error("size-bytes must be a multiple of the 16 KiB FTL slice.")
    if not re.fullmatch(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{4}", args.expected_pci_id):
        p.error("expected-pci-id must be four hex digits:four hex digits")
    if any(c in args.namespace for c in "\n\r"):
        p.error("Invalid namespace path")
    if args.phase in ("all", "prepare") and args.overwrite_passes == 0:
        p.error("Use at least one overwrite pass for preparation.")
    run_dir = args.output.resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    for phase in ("fill", "precondition", "warmup", "measure", "verify-write", "verify-read", "allocation"):
        (run_dir / f"{phase}.fio").write_text(generate_job(args, phase, run_dir), encoding="utf-8")
    manifest = {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}
    manifest.update({"schema": 2, "valid": False, "dry_run": not args.execute,
                     "note": "Latency is Host read completion latency; normal writes acknowledge DRAM DMA."})
    if args.firmware_elf:
        manifest["firmware_sha256"] = hashlib.sha256(args.firmware_elf.read_bytes()).hexdigest()
    try:
        if args.execute:
            execute(args, run_dir, manifest)
        else:
            print(f"Plan created: {run_dir}\nNo device commands executed. Review .fio files before --execute.")
    except Exception as exc:
        manifest["error"] = str(exc)
        raise
    finally:
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if args.execute:
        print(f"Completed phase={args.phase}; measurement_valid={manifest['valid']}; output={run_dir}")


if __name__ == "__main__":
    main()
