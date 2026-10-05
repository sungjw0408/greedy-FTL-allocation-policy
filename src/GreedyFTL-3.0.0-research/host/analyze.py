#!/usr/bin/env python3
"""Export genuine per-window P99/P99.9 and overlay policy time series."""
import argparse
import csv
import json
from pathlib import Path
from collections import defaultdict
import warnings

from telemetry import (derived_stats, empirical_percentile, fio_percentile,
                       gc_intervals, parse_stats, parse_trace)


def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def load_latency(run_dir, window_seconds, latency_unit="ns"):
    factor = {"ns": 1e-6, "us": 1e-3, "ms": 1}[latency_unit]
    files = sorted(run_dir.glob("probe_clat.*.log"))
    if not files:
        raise ValueError(f"No per-request probe_clat.*.log in {run_dir}")
    buckets, samples = defaultdict(list), []
    for path in files:
        with path.open() as stream:
            for line in stream:
                if not line.strip():
                    continue
                row = line.split(",")
                if len(row) < 4:
                    raise ValueError(f"Malformed fio latency row: {path}")
                if int(row[2]) != 0:
                    continue  # read probe only
                t, value = float(row[0]) / 1000, float(row[1]) * factor
                if int(row[3]) == 0:
                    raise ValueError("Averaged/windowed fio samples detected. Cannot calculate P99 from averages.")
                bucket = int(t // window_seconds)
                buckets[bucket].append(value)
                samples.append(value)
    windows = []
    if buckets:
        for index in range(max(buckets) + 1):
            values = buckets.get(index, [])
            windows.append({"start_s": index * window_seconds, "end_s": (index + 1) * window_seconds,
                            "count": len(values), "mean_ms": sum(values) / len(values) if values else None,
                            "p99_ms": empirical_percentile(values, 99),
                            "p99_9_ms": empirical_percentile(values, 99.9),
                            "max_ms": max(values) if values else None})
    if not samples:
        raise ValueError(f"No read samples in {run_dir}")
    return windows, samples


def analyze_run(run_dir, out, window_seconds, latency_unit):
    manifest = json.loads((run_dir / "manifest.json").read_text())
    if not manifest.get("valid"):
        raise ValueError(f"Run is not validated: {run_dir}; {manifest.get('error', 'plan/prepare only')}")
    policy = manifest["policy"]
    tag = f"{policy}-{manifest['mode']}-r{manifest['repeat']}"
    if manifest.get("synthetic"):
        tag = "SYNTHETIC-" + tag
    report = json.loads((run_dir / "fio.json").read_text())
    summary = {"policy": policy, "mode": manifest["mode"], "repeat": manifest["repeat"],
               "synthetic": manifest.get("synthetic", False), "run": str(run_dir)}
    for job in report["jobs"]:
        if job.get("error", 0):
            raise ValueError(f"fio job failed: {job['jobname']}")
        prefix = "probe" if job["jobname"].startswith("latency-probe") else "writer"
        for direction in ("read", "write"):
            op = job.get(direction, {})
            if not op.get("total_ios", 0):
                continue
            for key in ("iops", "bw_bytes", "total_ios", "io_bytes"):
                summary[f"{prefix}_{direction}_{key}"] = op.get(key)
            for q in (50, 99, 99.9):
                summary[f"{prefix}_{direction}_p{str(q).replace('.', '_')}_ms"] = fio_percentile(op, q)
    window = derived_stats(parse_stats((run_dir / "window.stats.txt").read_text()))
    drained = derived_stats(parse_stats((run_dir / "drained.stats.txt").read_text()))
    summary.update({f"window_{k}": v for k, v in window.items()})
    summary.update({f"drained_{k}": v for k, v in drained.items()})
    events = parse_trace((run_dir / "trace.txt").read_text(), drained)
    intervals, unmatched = gc_intervals(events, drained["timer_counts_per_second"])
    summary["unmatched_gc_starts"] = unmatched
    if drained.get("trace_dropped", 0):
        warnings.warn(f"{tag}: trace overflow; event timelines are incomplete. Counters remain usable.")
    write_csv(out / f"{tag}-events.csv", events)
    write_csv(out / f"{tag}-gc-intervals.csv", intervals)
    windows, samples = load_latency(run_dir, window_seconds, latency_unit)
    write_csv(out / f"{tag}-latency-windows.csv", windows)
    summary["probe_raw_sample_count"] = len(samples)
    summary["probe_raw_p99_ms"] = empirical_percentile(samples, 99)
    summary["probe_raw_p99_9_ms"] = empirical_percentile(samples, 99.9)
    return summary, windows, samples, tag


def plot_curves(results, out, metric):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = {"channel-first": "#1769aa", "way-first": "#db7a18", "page-first": "#27865b"}
    styles = {"channel-first": "-", "way-first": "--", "page-first": "-."}
    fig, ax = plt.subplots(figsize=(11, 4.8), constrained_layout=True)
    for summary, windows, _, tag in results:
        policy = summary["policy"]
        ax.plot([(w["start_s"] + w["end_s"]) / 2 for w in windows],
                [w[metric + "_ms"] if w[metric + "_ms"] is not None else float("nan") for w in windows],
                color=colors[policy], linestyle=styles[policy], linewidth=1.4, label=tag)
    ax.set(xlabel="Elapsed time in each independent run (s)",
           ylabel=f"Window {metric.replace('_', '.').upper()} read completion latency (ms)",
           title="Allocation policy and Host read latency over time")
    if any(r[0]["synthetic"] for r in results):
        ax.set_title("SYNTHETIC EXAMPLE — not measured on OpenSSD")
    ax.set_ylim(bottom=0)
    ax.grid(alpha=.22)
    ax.legend(fontsize=8)
    for ext in ("png", "svg"):
        fig.savefig(out / f"latency-timeseries-{metric}.{ext}", dpi=200)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(7, 4.5), constrained_layout=True)
    for summary, _, samples, tag in results:
        ordered = sorted(samples)
        n = len(ordered)
        # Draw at most ~10k samples, retaining endpoints; omit probability 0 on log axis.
        indices = sorted(set(range(0, n - 1, max(1, n // 10000))) | {max(0, n - 2)})
        ax.plot([ordered[i] for i in indices], [(n - i - 1) / n for i in indices],
                color=colors[summary["policy"]], linestyle=styles[summary["policy"]], label=tag)
    ax.set(xlabel="Read completion latency (ms)", ylabel="Fraction above latency", title="Host read latency CCDF")
    if any(r[0]["synthetic"] for r in results):
        ax.set_title("SYNTHETIC CCDF — not measured on OpenSSD")
    ax.set_yscale("log")
    ax.grid(alpha=.22)
    ax.legend(fontsize=8)
    for ext in ("png", "svg"):
        fig.savefig(out / f"latency-ccdf.{ext}", dpi=200)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("runs", nargs="+", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--window-seconds", type=float, default=1)
    p.add_argument("--metric", choices=("p99", "p99_9", "max", "mean"), default="p99")
    p.add_argument("--latency-unit", choices=("ns", "us", "ms"), default="ns")
    p.add_argument("--no-plot", action="store_true")
    args = p.parse_args()
    if args.window_seconds <= 0:
        p.error("window-seconds must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    results = [analyze_run(run.resolve(), args.output, args.window_seconds, args.latency_unit) for run in args.runs]
    tags = [r[3] for r in results]
    if len(set(tags)) != len(tags):
        p.error("Duplicate policy/mode/repeat tags; use distinct repeat labels.")
    write_csv(args.output / "summary.csv", [r[0] for r in results])
    if not args.no_plot:
        plot_curves(results, args.output, args.metric)
    print(f"Results: {args.output.resolve()}")


if __name__ == "__main__":
    main()
