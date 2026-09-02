from __future__ import annotations

import argparse
from pathlib import Path

from .matrix import resume_matrix


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args()
    receipt = resume_matrix(
        Path(args.root), Path(args.receipt), backend="harbor"
    )
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
