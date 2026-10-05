#!/usr/bin/env python3
import argparse
import re


def main():
    parser = argparse.ArgumentParser(description="Parse UART RESEARCH_STATS output")
    parser.add_argument("serial_log")
    args = parser.parse_args()

    values = {}
    pattern = re.compile(r"^([a-z0-9_]+)=0x([0-9a-fA-F]+)$")
    with open(args.serial_log, encoding="utf-8", errors="replace") as stream:
        for raw_line in stream:
            match = pattern.match(raw_line.strip())
            if match:
                values[match.group(1)] = int(match.group(2), 16)

    host_bytes = values.get("host_logical_write_bytes", 0)
    page_bytes = values.get("nand_page_bytes", 0)
    host_pages = values.get("host_nand_program_pages", 0)
    gc_pages = values.get("gc_nand_program_pages", 0)
    timer_hz = values.get("timer_counts_per_second", 0)
    gc_cycles = values.get("gc_execution_cycles", 0)

    for name in sorted(values):
        print(f"{name}={values[name]}")

    if host_bytes:
        wa = (host_pages + gc_pages) * page_bytes / host_bytes
        print(f"write_amplification={wa:.6f}")
    if timer_hz:
        print(f"gc_execution_seconds={gc_cycles / timer_hz:.9f}")
