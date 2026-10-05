#!/usr/bin/env python3
"""Compare ACTUAL board ALLOC traces with the expected policy sequence."""
import argparse
import re
import sys
from pathlib import Path


def validate(text, policy, channels, ways, pages):
    rows = [tuple(map(int, match.groups())) for match in re.finditer(
        r"ALLOC n=(\d+) ch=(\d+) way=(\d+) block=(\d+) page=(\d+)", text)]
    if not rows:
        raise ValueError("No ALLOC traces; validation needs ALLOCATION_TRACE_COUNT > 0.")
    if rows[0][0] != 0:
        raise ValueError("Missing beginning of allocation trace")
    per_die = {}
    for i, (n, ch, way, block, page) in enumerate(rows):
        if n != i:
            raise ValueError("Missing, duplicate, or restarted trace; use one complete boot log.")
        cursor = i // pages if policy == "page-first" else i
        expected = ((cursor // ways) % channels, cursor % ways) if policy == "way-first" else (
            cursor % channels, (cursor // channels) % ways)
        if (ch, way) != expected:
            raise ValueError(f"ALLOC {n}: expected ch/way {expected}, got {(ch, way)}")
        if not 0 <= page < pages:
            raise ValueError(f"ALLOC {n}: invalid page {page}")
        previous = per_die.get((ch, way))
        if previous:
            pb, pp = previous
            if pp + 1 < pages and (block != pb or page != pp + 1):
                raise ValueError(f"ALLOC {n}: unexpected block/page advancement")
            if pp + 1 == pages and (block == pb or page != 0):
                raise ValueError(f"ALLOC {n}: invalid block rollover")
        elif page != 0:
            raise ValueError(f"ALLOC {n}: first observed page on die is not zero")
        per_die[(ch, way)] = (block, page)
    if policy == "page-first" and len(rows) <= pages:
        raise ValueError("Trace too short to verify Page-first die rollover")
    return len(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("uart_log", type=Path)
    p.add_argument("--policy", required=True, choices=("channel-first", "way-first", "page-first"))
    p.add_argument("--channels", type=int)
    p.add_argument("--ways", type=int)
    p.add_argument("--pages-per-block", type=int)
    p.add_argument("--stats", type=Path, help="Use actual firmware geometry from this complete stats block")
    args = p.parse_args()
    if args.stats:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "host"))
        from telemetry import parse_stats
        stats = parse_stats(args.stats.read_text(errors="replace"))
        if stats.get("allocation_policy") != args.policy:
            p.error("Stats firmware policy differs from requested trace policy")
        for name, key in (("channels", "user_channels"), ("ways", "user_ways"),
                          ("pages_per_block", "user_pages_per_block")):
            value = stats.get(key)
            if value is None:
                p.error(f"Stats missing {key}; use updated firmware or specify geometry without --stats")
            if getattr(args, name) is not None and getattr(args, name) != value:
                p.error(f"Explicit {name} differs from firmware geometry")
            setattr(args, name, value)
    elif args.channels is None or args.ways is None:
        p.error("Specify --stats or both --channels and --ways")
    if args.pages_per_block is None:
        args.pages_per_block = 128
    if min(args.channels, args.ways, args.pages_per_block) <= 0:
        p.error("Geometry must be positive")
    n = validate(args.uart_log.read_text(errors="replace"), args.policy, args.channels, args.ways, args.pages_per_block)
    print(f"PASS: {n} actual board allocations match {args.policy}")


if __name__ == "__main__":
    main()
