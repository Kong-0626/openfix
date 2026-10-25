"""Deterministic safety gates for maintenance guidance."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable


@dataclass(frozen=True)
class SafetyRule:
    id: str
    level: str
    title: str
    triggers: tuple[str, ...]
    message: str
    immediate_actions: tuple[str, ...]
    prohibited_actions: tuple[str, ...]


SAFETY_RULES: tuple[SafetyRule, ...] = (
    SafetyRule(
        id="SAFE-FIRE",
        level="critical",
        title="烟火或焦味风险",
        triggers=("冒烟", "焦味", "起火", "着火", "火光", "燃烧"),
        message="出现烟、火或焦味时，当前状态不应继续生产或反复复位。",
        immediate_actions=(
            "立即停止相关设备并按现场应急程序报警、疏散。",
            "仅在受训且安全的情况下切断指定区域能源。",
            "由授权人员确认现场安全后再调查故障。",
        ),
        prohibited_actions=("继续运行设备", "未经授权进入危险区域", "反复复位掩盖故障"),
    ),
    SafetyRule(
        id="SAFE-ELECTRICAL",
        level="critical",
        title="电气暴露风险",
        triggers=("漏电", "触电", "带电", "电弧", "电气柜进水", "带电拆卸"),
        message="检测到电气暴露或触电风险，禁止带电接触和拆卸。",
        immediate_actions=(
            "保持安全距离并停止设备。",
            "由持证人员隔离、上锁并验证零能量。",
            "存在人员受伤时优先执行现场急救与应急报告。",
        ),
        prohibited_actions=("带电开柜", "绕过漏电保护", "用湿手接触电气部件"),
    ),
    SafetyRule(
        id="SAFE-PRESSURE",
        level="critical",
        title="压力能未释放",
        triggers=("带压", "有压力", "压力未泄", "拆油管", "拆气管", "直接拆油管", "残余压力"),
        message="压力回路仍有残余能量，禁止直接拆卸管路或接头。",
        immediate_actions=(
            "停止设备并切断压力源。",
            "按规程泄压，等待温度稳定，并验证零能量。",
            "由授权人员复核隔离状态后再拆卸。",
        ),
        prohibited_actions=("带压拆管", "仅关闭阀门而不泄压", "用声音判断是否仍有压力"),
    ),
    SafetyRule(
        id="SAFE-ROTATING",
        level="high",
        title="旋转部件暴露风险",
        triggers=("运行中拆", "运行时拆", "拆护罩", "拆开护罩", "触碰输送带", "旋转中调整"),
        message="运行中的旋转部件存在卷入风险，禁止拆卸护罩或进行调整。",
        immediate_actions=(
            "停止设备并执行 LOTO。",
            "等待旋转部件完全静止。",
            "确认护罩复位后再安排试运行。",
        ),
        prohibited_actions=("运行中伸手", "拆除联锁", "用手检查输送带或皮带"),
    ),
    SafetyRule(
        id="SAFE-THERMAL",
        level="high",
        title="高温与烫伤风险",
        triggers=("很烫", "烫手", "烫伤", "灼热", "高温接触", "未冷却"),
        message="高温部件可能造成烫伤，应停止并等待自然冷却。",
        immediate_actions=(
            "停止加工或设备运行，保持必要的冷却系统正常工作。",
            "与高温部件保持距离，不立即触摸或拆卸。",
            "按设备规程冷却后再进行检查。",
        ),
        prohibited_actions=("立即触摸主轴", "用冷水骤冷高温部件", "未冷却拆油路"),
    ),
    SafetyRule(
        id="SAFE-ABNORMAL-MOTION",
        level="high",
        title="异常运动或机械卡涩",
        triggers=("剧烈振动", "抱死", "卡顿", "轴移动卡顿", "机械异响"),
        message="异常振动、卡涩或机械异响可能预示设备失效，应停止继续加载。",
        immediate_actions=(
            "停止设备并识别残余运动风险。",
            "执行能量隔离，禁止用手直接检查运动部件。",
            "由维修人员确认机械和电气因素后再试运行。",
        ),
        prohibited_actions=("带故障继续高负荷生产", "提高保护阈值", "运行中排除卡涩"),
    ),
)


@dataclass(frozen=True)
class SafetyAssessment:
    required: bool
    level: str
    alerts: tuple[dict, ...]
    summary: str

    def to_dict(self) -> dict:
        return asdict(self)


def assess_safety(query: str) -> SafetyAssessment:
    """Apply deterministic safety rules and collect all matching hazards."""

    normalized = (query or "").lower()
    alerts: list[dict] = []
    for rule in SAFETY_RULES:
        matched = [trigger for trigger in rule.triggers if trigger in normalized]
        if rule.id == "SAFE-ROTATING":
            disassembly = any(word in normalized for word in ("拆", "打开", "取下"))
            cover = any(word in normalized for word in ("护罩", "防护罩", "联锁"))
            running = any(word in normalized for word in ("运行", "运转", "开机"))
            if disassembly and cover and running:
                matched.append("运行状态下拆卸护罩")
        if rule.id == "SAFE-ABNORMAL-MOTION" and "异响" in normalized:
            matched.append("异响")
        if not matched:
            continue
        alerts.append(
            {
                "id": rule.id,
                "level": rule.level,
                "title": rule.title,
                "message": rule.message,
                "triggered_by": matched,
                "immediate_actions": list(rule.immediate_actions),
                "prohibited_actions": list(rule.prohibited_actions),
            }
        )

    if not alerts:
        return SafetyAssessment(
            required=False,
            level="normal",
            alerts=(),
            summary="未识别到高危关键词，仍需按现场 LOTO 与设备规程执行。",
        )

    levels = [alert["level"] for alert in alerts]
    level = "critical" if "critical" in levels else "high"
    return SafetyAssessment(
        required=True,
        level=level,
        alerts=tuple(alerts),
        summary="检测到需要立即人工确认的安全风险，不得把建议直接当作复机许可。",
    )


def merge_prohibited_actions(alerts: Iterable[dict]) -> list[str]:
    values: list[str] = []
    for alert in alerts:
        for action in alert.get("prohibited_actions", []):
            if action not in values:
                values.append(action)
    return values
