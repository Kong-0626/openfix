"""Grounded diagnosis engine for OpenFix."""

from __future__ import annotations

import json
import math
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .safety import assess_safety, merge_prohibited_actions
from .text import (
    BM25Index,
    SearchDocument,
    SearchHit,
    extract_known_codes,
    safe_excerpt,
    tokenize,
)


MAX_QUERY_LENGTH = 1000
MIN_RELEVANCE_SCORE = 2.6


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class DiagnosisResult:
    payload: dict

    def to_dict(self) -> dict:
        return self.payload


class MaintenanceEngine:
    """Combines retrieval, structured records and safety gates.

    The engine intentionally separates evidence retrieval from action policy.
    An optional language model may explain the result later, but cannot invent
    evidence or bypass deterministic safety checks.
    """

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = (data_dir or Path(__file__).resolve().parent.parent / "data").resolve()
        self.assets: list[dict] = _load_json(self.data_dir / "assets.json")
        self.knowledge: list[dict] = _load_json(self.data_dir / "knowledge.json")
        self.cases: list[dict] = _load_json(self.data_dir / "cases.json")
        self._asset_by_id = {asset["id"]: asset for asset in self.assets}
        self._knowledge_by_id = {record["id"]: record for record in self.knowledge}
        self._case_by_id = {record["id"]: record for record in self.cases}
        self._known_alarm_codes = {
            code
            for record in (*self.knowledge, *self.cases)
            for code in record.get("alarm_codes", [])
        }
        self.knowledge_index = BM25Index(self._knowledge_documents())
        self.case_index = BM25Index(self._case_documents())

    def _knowledge_documents(self) -> list[SearchDocument]:
        return [
            SearchDocument(
                id=record["id"],
                text=" ".join(
                    [
                        record.get("title", ""),
                        record.get("title", ""),
                        record.get("content", ""),
                        " ".join(record.get("tags", [])),
                        " ".join(record.get("components", [])),
                        " ".join(record.get("alarm_codes", [])),
                    ]
                ),
                metadata=record,
            )
            for record in self.knowledge
        ]

    def _case_documents(self) -> list[SearchDocument]:
        return [
            SearchDocument(
                id=record["id"],
                text=" ".join(
                    [
                        record.get("title", ""),
                        record.get("title", ""),
                        record.get("root_cause", ""),
                        record.get("resolution", ""),
                        " ".join(record.get("symptoms", [])),
                        " ".join(record.get("components", [])),
                        " ".join(record.get("alarm_codes", [])),
                    ]
                ),
                metadata=record,
            )
            for record in self.cases
        ]

    def overview(self) -> dict:
        alarm_codes = sorted(
            {
                code
                for record in (*self.knowledge, *self.cases)
                for code in record.get("alarm_codes", [])
            }
        )
        return {
            "project": "OpenFix",
            "tagline": "工业设备检修证据链智能体",
            "stats": {
                "assets": len(self.assets),
                "knowledge_records": len(self.knowledge),
                "historical_cases": len(self.cases),
                "alarm_codes": len(alarm_codes),
            },
            "assets": self.assets,
            "alarm_codes": alarm_codes,
            "sample_queries": [
                "AC-01 空压机报 E201，排气温度高，复位后很快又停机",
                "PU-07 冷却泵 P110 出口压力低，泵体有异响，电流也下降了",
                "CNC-12 报 S412 伺服过载，X 轴移动卡顿，润滑同时报警",
                "设备有焦味并且冒烟，应该怎么继续生产",
            ],
            "capabilities": [
                "中文与设备编码混合检索",
                "SOP、历史工单与设备结构联合取证",
                "高危操作确定性拦截",
                "诊断结果转人工审批工单",
                "全量本地运行，无云服务依赖",
            ],
            "disclaimer": "当前为演示数据集。输出仅用于辅助诊断，不替代设备厂商规程、授权人员判断或现场安全评估。",
        }

    def _resolve_asset(self, query: str, asset_id: str | None) -> dict | None:
        if asset_id:
            return self._asset_by_id.get(asset_id)
        upper_query = query.upper()
        for asset in self.assets:
            asset_id_value = asset["id"].upper()
            if re.search(rf"(?<![A-Z0-9]){re.escape(asset_id_value)}(?![A-Z0-9])", upper_query):
                return asset
        alias_matches = [
            asset
            for asset in self.assets
            if any(alias.upper() in upper_query for alias in asset.get("aliases", []))
        ]
        return alias_matches[0] if len(alias_matches) == 1 else None

    def _context_query(self, query: str, asset: dict | None) -> str:
        if not asset:
            return query
        return " ".join(
            [
                query,
                asset["name"],
                asset["asset_type"],
                " ".join(asset.get("aliases", [])),
                " ".join(asset.get("components", [])),
            ]
        )

    def _rank_with_structure(
        self,
        hits: list[SearchHit],
        query: str,
        asset: dict | None,
        record_type: str,
    ) -> list[SearchHit]:
        query_codes = extract_known_codes(query, self._known_alarm_codes)
        tokens = set(tokenize(query))
        adjusted: list[SearchHit] = []
        for hit in hits:
            record = hit.metadata
            boost = 0.0
            record_codes = {code.upper() for code in record.get("alarm_codes", [])}
            if query_codes & record_codes:
                boost += 12.0 if record_type == "knowledge" else 9.0
            if asset and record.get("asset_type") == asset.get("asset_type"):
                boost += 4.5
            shared_components = {
                token for token in tokens if token in " ".join(record.get("components", []))
            }
            boost += min(len(shared_components) * 0.25, 2.0)
            adjusted.append(SearchHit(hit.id, hit.score + boost, hit.metadata))
        adjusted.sort(key=lambda item: (-item.score, item.id))
        return adjusted

    def diagnose(self, query: str, asset_id: str | None = None) -> DiagnosisResult:
        normalized = re.sub(r"\s+", " ", (query or "")).strip()
        if len(normalized) > MAX_QUERY_LENGTH:
            raise ValueError(f"故障描述不能超过 {MAX_QUERY_LENGTH} 个字符")
        if asset_id and asset_id not in self._asset_by_id:
            raise ValueError("设备编号不在当前资产台账中")

        request_id = f"DX-{secrets.token_hex(6).upper()}"
        asset = self._resolve_asset(normalized, asset_id)
        safety = assess_safety(normalized)

        if len(normalized) < 3:
            return DiagnosisResult(
                self._abstain_payload(
                    request_id,
                    asset,
                    safety.to_dict(),
                    "请输入设备编号、报警代码以及可观察到的现象。",
                )
            )

        context = self._context_query(normalized, asset)
        knowledge_hits = self._rank_with_structure(
            self.knowledge_index.search(context, limit=8), normalized, asset, "knowledge"
        )
        case_hits = self._rank_with_structure(
            self.case_index.search(context, limit=8), normalized, asset, "case"
        )

        explicit_codes = extract_known_codes(normalized, self._known_alarm_codes)
        if explicit_codes:
            knowledge_hits = [
                hit
                for hit in knowledge_hits
                if explicit_codes & {code.upper() for code in hit.metadata.get("alarm_codes", [])}
            ]
            case_hits = [
                hit
                for hit in case_hits
                if explicit_codes & {code.upper() for code in hit.metadata.get("alarm_codes", [])}
            ]
        top_score = knowledge_hits[0].score if knowledge_hits else 0.0
        is_out_of_scope = (
            top_score < MIN_RELEVANCE_SCORE
            and not explicit_codes
            and not asset
            and not safety.required
        )
        if is_out_of_scope:
            return DiagnosisResult(
                self._abstain_payload(
                    request_id,
                    asset,
                    safety.to_dict(),
                    "当前描述与已接入的检修知识关联不足。请补充设备编号、报警代码或具体异常现象。",
                )
            )

        evidence = self._build_evidence(
            knowledge_hits[:3], case_hits[:2], explicit_codes, safety.required
        )
        candidates = self._build_candidates(case_hits[:2], knowledge_hits[:2], explicit_codes)
        actions = self._build_actions(knowledge_hits[:2], asset, safety.to_dict())
        missing = self._missing_information(normalized, asset, explicit_codes)
        confidence = self._confidence(knowledge_hits, case_hits, explicit_codes, safety.required)
        summary = self._summary(asset, candidates, safety.to_dict())
        graph = self._evidence_graph(asset, candidates, evidence, safety.to_dict())

        payload = {
            "request_id": request_id,
            "generated_at": _utc_now(),
            "status": "needs_safety_review" if safety.required else "ready_for_human_review",
            "query": normalized,
            "asset": asset,
            "summary": summary,
            "confidence": confidence,
            "confidence_label": (
                "较高" if confidence >= 75 else "中等" if confidence >= 50 else "有限"
            ),
            "safety": safety.to_dict(),
            "candidates": candidates,
            "actions": actions,
            "evidence": evidence,
            "missing_information": missing,
            "graph": graph,
            "guardrails": {
                "requires_human_approval": True,
                "prohibited_actions": merge_prohibited_actions(safety.alerts),
                "policy": "诊断结果不能直接下发为执行许可；工单必须经授权人员批准。",
            },
            "disclaimer": "本结果基于演示知识库，仅用于辅助检修决策。现场须以设备厂商规程和授权人员判断为准。",
        }
        return DiagnosisResult(payload)

    def _abstain_payload(
        self, request_id: str, asset: dict | None, safety: dict, reason: str
    ) -> dict:
        return {
            "request_id": request_id,
            "generated_at": _utc_now(),
            "status": "input_required",
            "query": "",
            "asset": asset,
            "summary": reason,
            "confidence": 0,
            "confidence_label": "有限",
            "safety": safety,
            "candidates": [],
            "actions": [],
            "evidence": [],
            "missing_information": [
                "设备编号或设备类型",
                "报警代码与首次发生时间",
                "温度、压力、振动、电流等可观察变化",
                "是否伴随异响、泄漏、焦味或冒烟",
            ],
            "graph": {"nodes": [], "edges": []},
            "guardrails": {
                "requires_human_approval": True,
                "prohibited_actions": merge_prohibited_actions(safety.get("alerts", [])),
                "policy": "信息不足时系统不生成诊断结论。",
            },
            "disclaimer": "系统已主动放弃推断，请补充可验证的现场信息。",
        }

    def _build_evidence(
        self,
        knowledge_hits: list[SearchHit],
        case_hits: list[SearchHit],
        query_codes: set[str],
        safety_required: bool,
    ) -> list[dict]:
        evidence: list[dict] = []
        evidence_hits = list(knowledge_hits)
        if safety_required and not any(hit.id == "KB-GEN-001" for hit in evidence_hits):
            general_safety = self._knowledge_by_id.get("KB-GEN-001")
            if general_safety:
                evidence_hits.append(SearchHit("KB-GEN-001", 20.0, general_safety))
        for hit in evidence_hits:
            record = hit.metadata
            reasons = ["SOP 内容与故障描述相关"]
            if query_codes & set(record.get("alarm_codes", [])):
                reasons.insert(0, "命中报警代码")
            evidence.append(
                {
                    "id": record["id"],
                    "type": "SOP",
                    "title": record["title"],
                    "excerpt": safe_excerpt(record.get("content", "")),
                    "risk_level": record.get("risk_level", ""),
                    "source": record.get("source", ""),
                    "score": round(hit.score, 2),
                    "reasons": reasons,
                }
            )
        for hit in case_hits:
            record = hit.metadata
            reasons = ["历史案例症状匹配"]
            if query_codes & set(record.get("alarm_codes", [])):
                reasons.insert(0, "历史记录包含相同报警代码")
            evidence.append(
                {
                    "id": record["id"],
                    "type": "历史工单",
                    "title": record["title"],
                    "excerpt": safe_excerpt(
                        f"根因：{record.get('root_cause', '')} 处理：{record.get('resolution', '')}",
                        210,
                    ),
                    "verified": bool(record.get("verified")),
                    "score": round(hit.score, 2),
                    "reasons": reasons,
                }
            )
        evidence.sort(key=lambda item: -item["score"])
        if safety_required:
            safety_items = [item for item in evidence if item["id"] == "KB-GEN-001"]
            if safety_items:
                for item in safety_items:
                    item["reasons"] = ["安全门槛优先引用", *item["reasons"]]
                evidence = safety_items + [item for item in evidence if item["id"] != "KB-GEN-001"]
        return evidence[:5]

    def _build_candidates(
        self,
        case_hits: list[SearchHit],
        knowledge_hits: list[SearchHit],
        query_codes: set[str],
    ) -> list[dict]:
        candidates: list[dict] = []
        for index, hit in enumerate(case_hits):
            record = hit.metadata
            candidates.append(
                {
                    "cause": record.get("root_cause", "历史案例中的可能根因"),
                    "likelihood": "较高" if index == 0 else "中等",
                    "evidence_ids": [record["id"]],
                    "basis": f"历史工单：{record['title']}",
                }
            )
        for hit in knowledge_hits[:2]:
            record = hit.metadata
            if any(candidate["cause"] == record.get("title") for candidate in candidates):
                continue
            candidates.append(
                {
                    "cause": f"需按《{record['title']}》逐项排除关联故障",
                    "likelihood": "待验证",
                    "evidence_ids": [record["id"]],
                    "basis": "设备规程中的故障树条目",
                }
            )
        if query_codes:
            candidates = [
                {
                    **candidate,
                    "basis": f"{candidate['basis']}；关联报警 {', '.join(sorted(query_codes))}",
                }
                for candidate in candidates
            ]
        return candidates[:3]

    def _build_actions(
        self, knowledge_hits: list[SearchHit], asset: dict | None, safety: dict
    ) -> list[dict]:
        if safety.get("required"):
            actions: list[dict] = []
            for alert in safety.get("alerts", []):
                actions.append(
                    {
                        "order": len(actions) + 1,
                        "action": alert["immediate_actions"][0],
                        "phase": "立即处置",
                        "source_ids": [alert["id"]],
                        "requires_approval": True,
                    }
                )
            for alert in safety.get("alerts", []):
                for step in alert["immediate_actions"][1:]:
                    if step not in [action["action"] for action in actions]:
                        actions.append(
                            {
                                "order": len(actions) + 1,
                                "action": step,
                                "phase": "安全确认",
                                "source_ids": [alert["id"]],
                                "requires_approval": True,
                            }
                        )
            return actions[:8]

        actions = []
        seen: set[str] = set()
        for hit in knowledge_hits:
            record = hit.metadata
            for step in record.get("steps", []):
                if step in seen:
                    continue
                seen.add(step)
                actions.append(
                    {
                        "order": len(actions) + 1,
                        "action": step,
                        "phase": "检修确认",
                        "source_ids": [record["id"]],
                        "requires_approval": True,
                    }
                )
                if len(actions) >= 7:
                    break
            if len(actions) >= 7:
                break

        base_safety = "任何进入防护区域、拆护罩或接触压力/电气回路的工作，必须先执行 LOTO。"
        if not any("LOTO" in action["action"] for action in actions):
            actions.append(
                {
                    "order": len(actions) + 1,
                    "action": base_safety,
                    "phase": "安全门槛",
                    "source_ids": ["KB-GEN-001"],
                    "requires_approval": True,
                }
            )
        return actions

    def _missing_information(
        self, query: str, asset: dict | None, query_codes: set[str]
    ) -> list[str]:
        missing: list[str] = []
        if not asset:
            missing.append("具体设备编号或型号")
        if not query_codes:
            missing.append("控制面板报警代码")
        if not re.search(r"\d", query):
            missing.append("温度、压力、电流、振动等量化读数")
        if not any(word in query for word in ("开始", "首次", "一直", "反复", "最近", "今天")):
            missing.append("故障首次出现时间和发生频率")
        if not any(word in query for word in ("复位", "重启", "停机", "运行")):
            missing.append("复位或停机后的状态变化")
        return missing[:4]

    def _confidence(
        self,
        knowledge_hits: list[SearchHit],
        case_hits: list[SearchHit],
        query_codes: set[str],
        safety_required: bool,
    ) -> int:
        knowledge_score = knowledge_hits[0].score if knowledge_hits else 0.0
        case_score = case_hits[0].score if case_hits else 0.0
        level = 24
        level += min(28, round(math.log1p(max(knowledge_score, 0)) * 5))
        level += min(20, round(math.log1p(max(case_score, 0)) * 4))
        if query_codes:
            level += 14
        if len(knowledge_hits) >= 2:
            level += 5
        if safety_required:
            level = min(level, 72)
        return max(25, min(level, 94))

    def _summary(self, asset: dict | None, candidates: list[dict], safety: dict) -> str:
        prefix = f"{asset['id']} {asset['name']}" if asset else "当前设备"
        if safety.get("required"):
            return f"{prefix}存在需人工确认的高危条件。系统已暂停给出复机步骤，先完成安全隔离与现场确认。"
        if candidates:
            return f"{prefix}的可能根因需结合 {len(candidates)} 条假设逐项验证；建议按证据顺序排查，不要直接复位后恢复满负荷。"
        return f"{prefix}信息已记录，但证据不足，建议补充设备状态与测量数据。"

    def _evidence_graph(
        self,
        asset: dict | None,
        candidates: list[dict],
        evidence: list[dict],
        safety: dict,
    ) -> dict:
        nodes = [{"id": "symptom", "label": "现场异常", "kind": "input"}]
        edges: list[dict] = []
        if asset:
            nodes.append({"id": f"asset:{asset['id']}", "label": asset["id"], "kind": "asset"})
            edges.append({"source": "symptom", "target": f"asset:{asset['id']}", "label": "作用于"})
        for index, candidate in enumerate(candidates[:2], start=1):
            node_id = f"cause:{index}"
            nodes.append({"id": node_id, "label": candidate["likelihood"], "kind": "cause"})
            edges.append({"source": "symptom", "target": node_id, "label": "指向"})
        for item in evidence[:3]:
            node_id = f"evidence:{item['id']}"
            nodes.append({"id": node_id, "label": item["id"], "kind": "evidence"})
            edges.append({"source": "symptom", "target": node_id, "label": "证据"})
        if safety.get("required"):
            nodes.append({"id": "safety-gate", "label": "安全门槛", "kind": "safety"})
            edges.append({"source": "symptom", "target": "safety-gate", "label": "先阻断"})
        return {"nodes": nodes, "edges": edges}
