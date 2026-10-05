#!/usr/bin/env python3
"""Preview/apply only research-modified sources into an EXISTING SDK src tree.

Preserves ftl_config.h, memory_map.h, main.c, nsc_driver.*, BSP and FPGA design.
Existing board customizations inside replaced files must be manually reviewed.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil

FILES = (
    "address_translation.c", "address_translation.h", "allocation_policy.h",
    "data_buffer.c", "data_buffer.h", "garbage_collection.c", "request_format.h",
    "request_transform.c", "request_allocation.c", "request_schedule.c", "ftl_config.c",
    "research_stats.c", "research_stats.h", "research_config.h",
    "nvme/nvme.h", "nvme/nvme_admin_cmd.c", "nvme/nvme_io_cmd.c",
)


def preview(source, destination):
    required = ("address_translation.c", "ftl_config.h", "main.c", "nvme/nvme_io_cmd.c")
    if not all((destination / name).is_file() for name in required):
        raise ValueError("Not an existing GreedyFTL SDK src tree. Check --sdk-src; do not use project root.")
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("Use a separate SDK source tree, not this repository or an overlapping parent.")
    changes, diffs = [], []
    for name in FILES:
        incoming = source / name
        existing = destination / name
        new = incoming.read_bytes()
        old = existing.read_bytes() if existing.exists() else b""
        changes.append({"file": name, "exists": existing.exists(), "changed": old != new,
                        "source_sha256": hashlib.sha256(new).hexdigest(),
                        "original_sha256": hashlib.sha256(old).hexdigest() if existing.exists() else None})
        if old != new:
            diffs.extend(difflib.unified_diff(old.decode(errors="replace").splitlines(True),
                         new.decode(errors="replace").splitlines(True),
                         fromfile=f"SDK/{name}", tofile=f"research/{name}"))
    return changes, "".join(diffs)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sdk-src", required=True, type=Path)
    p.add_argument("--report", required=True, type=Path, help="New folder, outside repository/SDK")
    p.add_argument("--apply", action="store_true", help="Copy changed files AFTER backing them up")
    p.add_argument("--confirm-reviewed-diff", action="store_true")
    args = p.parse_args()
    if args.apply and not args.confirm_reviewed_diff:
        p.error("Review the preview diff first; --apply requires --confirm-reviewed-diff")
    root = Path(__file__).resolve().parents[1]
    target, report = args.sdk_src.resolve(), args.report.resolve()
    if any(report == protected or protected in report.parents or report in protected.parents
           for protected in (root, target)):
        p.error("Report folder must be separate from the repository and SDK src")
    changes, diff = preview(root, target)
    report.mkdir(parents=True, exist_ok=False)
    (report / "changes.diff").write_text(diff, encoding="utf-8")
    (report / "manifest.json").write_text(json.dumps({"sdk_src": str(target), "applied": False,
                                                     "files": changes}, indent=2), encoding="utf-8")
    if args.apply:
        # Back up EVERY original before overwriting ANY source.
        for item in changes:
            existing = target / item["file"]
            if item["exists"]:
                backup = report / "originals" / item["file"]
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(existing, backup)
        for item in changes:
            if item["changed"]:
                destination = target / item["file"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root / item["file"], destination)
        (report / "APPLIED.txt").write_text("Research source files applied. Originals are in originals/.\n",
                                          encoding="utf-8")
        (report / "manifest.json").write_text(json.dumps({"sdk_src": str(target), "applied": True,
                                                         "files": changes}, indent=2), encoding="utf-8")
    for item in changes:
        print(f"{'CHANGE' if item['changed'] else 'SAME'} {item['file']}")
    print(f"{'Applied with backup' if args.apply else 'PREVIEW ONLY; SDK unchanged'}: {report}")
    print("ftl_config.h, linker script, main.c, memory_map.h, nsc_driver and BSP are preserved.")
    print("Manually verify board geometry and apply the linker RAM-boundary ASSERT.")


if __name__ == "__main__":
    main()
