#!/usr/bin/env python3
import argparse
import json


def percentile(operation, key):
    lat = operation.get("clat_ns", operation.get("lat_ns", {}))
    return lat.get("percentile", {}).get(key)


def main():
    parser = argparse.ArgumentParser(description="Print fio P99/P99.9 completion latency")
    parser.add_argument("fio_json")
    args = parser.parse_args()

    with open(args.fio_json, encoding="utf-8") as stream:
        report = json.load(stream)

    for job in report.get("jobs", []):
        name = job.get("jobname", "unknown")
        for op_name in ("read", "write"):
            op = job.get(op_name, {})
            if not op.get("io_bytes"):
                continue
            p99 = percentile(op, "99.000000")
            p999 = percentile(op, "99.900000")
            print(f"{name}.{op_name}.p99_ns={p99}")
            print(f"{name}.{op_name}.p99_9_ns={p999}")


if __name__ == "__main__":
    main()
