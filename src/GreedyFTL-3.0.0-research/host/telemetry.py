"""Pure parsers for schema-2 UART statistics and buffered events."""
import math
import re
from collections import defaultdict, deque


def parse_stats(text):
    blocks = re.findall(r"=== RESEARCH_STATS_BEGIN ===(.*?)=== RESEARCH_STATS_END ===", text, re.S)
    if not blocks:
        raise ValueError("No complete RESEARCH_STATS block")
    values = {}
    for line in blocks[-1].splitlines():
        match = re.fullmatch(r"([a-z0-9_]+)=(\S+)", line.strip())
        if match:
            key, value = match.groups()
            values[key] = int(value, 16) if value.startswith("0x") else value
    return values


def derived_stats(values):
    out = dict(values)
    hz = values.get("timer_counts_per_second", 0)
    host = values.get("host_nand_req_count", 0)
    count = values.get("gc_count", 0)
    if hz:
        for key, value in values.items():
            if key.endswith("_cycles"):
                out[key[:-7] + "_seconds"] = value / hz
        for prefix in ("gc_die", "gc_channel"):
            n = values.get(prefix + "_blocked_req_count", 0)
            if n:
                out[prefix + "_queue_wait_mean_us"] = values[prefix + "_blocked_cycles"] / hz / n * 1e6
        if host:
            out["host_queue_wait_mean_us"] = values["host_queue_wait_cycles"] / hz / host * 1e6
    if count:
        out["migration_pages_per_gc"] = values["gc_migration_pages"] / count
        if hz:
            out["gc_mean_ms"] = values["gc_execution_cycles"] / hz / count * 1e3
            out["gc_max_ms"] = values["gc_max_execution_cycles"] / hz * 1e3
    if host:
        out["pending_gc_host_ratio"] = (values.get("gc_die_blocked_req_count", 0) +
                                         values.get("gc_channel_blocked_req_count", 0)) / host
        out["same_die_gc_issue_overlap_ratio"] = values.get("host_same_die_gc_issue_overlap_req_count", 0) / host
    logical = values.get("host_logical_write_bytes", 0)
    if logical:
        out["write_amplification"] = ((values["host_nand_program_pages"] + values["gc_nand_program_pages"]) *
                                       values["nand_page_bytes"] / logical)
    return out


def parse_trace(text, values):
    hz = values["timer_counts_per_second"]
    epoch = values["stats_epoch_ticks"]
    if hz <= 0:
        raise ValueError("Invalid timer frequency")
    names = {1: "GC_START", 2: "GC_END", 3: "HOST_ISSUE", 4: "PHASE_START", 5: "PHASE_END", 6: "MARK"}
    events = []
    for line in text.splitlines():
        if not line.startswith("TRACE,"):
            continue
        parts = line.strip().split(",")
        if len(parts) != 7:
            raise ValueError(f"Malformed TRACE row: {line}")
        kind, ch, way = map(int, parts[1:4])
        tick, a, b = (int(x, 16) for x in parts[4:])
        events.append({"type": names.get(kind, f"UNKNOWN_{kind}"), "ch": ch, "way": way,
                       "tick": tick, "time_since_reset_s": (tick - epoch) / hz, "a": a, "b": b})
    return events


def gc_intervals(events, hz):
    active, intervals = defaultdict(deque), []
    for e in events:
        resource = (e["ch"], e["way"])
        if e["type"] == "GC_START":
            active[resource].append(e)
        elif e["type"] == "GC_END":
            start = active[resource].popleft() if active[resource] else None
            if start:
                intervals.append({"ch": e["ch"], "way": e["way"], "victim_block": start["a"],
                                  "start_since_reset_s": start["time_since_reset_s"],
                                  "end_since_reset_s": e["time_since_reset_s"],
                                  "migration_pages": e["a"], "duration_ms": e["b"] / hz * 1e3})
    return intervals, sum(map(len, active.values()))


def empirical_percentile(samples, percentile):
    """Nearest-rank empirical quantile; never average per-window percentiles."""
    if not samples:
        return None
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(percentile / 100 * len(ordered)) - 1)]


def fio_percentile(operation, percentile):
    for unit, factor in (("clat_ns", 1e-6), ("clat_us", 1e-3), ("clat_ms", 1)):
        latency = operation.get(unit)
        if latency:
            for key, value in latency.get("percentile", {}).items():
                if abs(float(key) - percentile) < 1e-7:
                    return value * factor
    return None
