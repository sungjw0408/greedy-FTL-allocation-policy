#!/usr/bin/env python3
"""Package source only; exclude generated logs and Python caches."""
import argparse
import hashlib
from pathlib import Path
import zipfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    selected = sorted(path for path in root.rglob("*") if path.is_file()
                      and "__pycache__" not in path.parts and path.name != ".DS_Store"
                      and (path.suffix in (".c", ".h", ".py", ".md", ".fio", ".ld", ".txt")
                           or path.name == ".gitignore"))
    hashes = []
    with zipfile.ZipFile(args.output, "x", zipfile.ZIP_DEFLATED) as archive:
        for path in selected:
            relative = path.relative_to(root)
            archive.write(path, f"GreedyFTL-3.0.0-research/{relative}")
            hashes.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {relative}")
        archive.writestr("GreedyFTL-3.0.0-research/SHA256SUMS.txt", "\n".join(hashes) + "\n")
    print(args.output.resolve())


if __name__ == "__main__":
    main()
