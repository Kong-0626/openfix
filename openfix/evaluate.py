"""Reproducible evaluation of retrieval, abstention and safety gates."""

from __future__ import annotations

import json
from pathlib import Path

from .engine import MaintenanceEngine


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 1.0


def evaluate_engine(engine: MaintenanceEngine, data_dir: Path | None = None) -> dict:
    root = data_dir or engine.data_dir
    with (root / "eval_cases.json").open("r", encoding="utf-8") as handle:
        cases = json.load(handle)

    results = []
    doc_hits = doc_expected = 0
    case_hits = case_expected = 0
    abstention_correct = 0
    safety_correct = 0

    for item in cases:
        result = engine.diagnose(item["query"]).to_dict()
        evidence_ids = {entry["id"] for entry in result["evidence"]}
        expected_docs = set(item.get("expected_docs", []))
        expected_cases = set(item.get("expected_cases", []))
        found_docs = expected_docs & evidence_ids
        found_cases = expected_cases & evidence_ids
        expected_abstain = bool(item.get("should_abstain"))
        actual_abstain = result["status"] == "input_required"
        safety_match = bool(result["safety"]["required"]) == bool(item.get("safety_required"))

        doc_hits += len(found_docs)
        doc_expected += len(expected_docs)
        case_hits += len(found_cases)
        case_expected += len(expected_cases)
        abstention_correct += int(expected_abstain == actual_abstain)
        safety_correct += int(safety_match)
        results.append(
            {
                "id": item["id"],
                "status": result["status"],
                "expected_docs": sorted(expected_docs),
                "found_docs": sorted(found_docs),
                "expected_cases": sorted(expected_cases),
                "found_cases": sorted(found_cases),
                "abstention_match": expected_abstain == actual_abstain,
                "safety_match": safety_match,
                "confidence": result["confidence"],
            }
        )

    total = len(cases)
    return {
        "total_cases": total,
        "knowledge_evidence_recall": _ratio(doc_hits, doc_expected),
        "case_evidence_recall": _ratio(case_hits, case_expected),
        "abstention_accuracy": _ratio(abstention_correct, total),
        "safety_gate_accuracy": _ratio(safety_correct, total),
        "passed": all(
            item["abstention_match"]
            and item["safety_match"]
            and set(item["expected_docs"]) <= set(item["found_docs"])
            and set(item["expected_cases"]) <= set(item["found_cases"])
            for item in results
        ),
        "note": "指标来自随项目提供的合成演示评测集，不代表真实生产环境效果。",
        "results": results,
    }
