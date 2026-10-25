"""CLI entry point for the OpenFix reproducible evaluation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from openfix.engine import MaintenanceEngine  # noqa: E402
from openfix.evaluate import evaluate_engine  # noqa: E402


def main() -> int:
    engine = MaintenanceEngine(ROOT / "data")
    report = evaluate_engine(engine)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
