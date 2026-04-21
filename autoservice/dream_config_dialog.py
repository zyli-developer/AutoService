"""Dream Engine conversational 4-parameter configuration dialog.

T6E.9 产出 | 2026-04-17
T4B.3 update | 2026-04-21 — on-confirm hook into DreamScheduler.refresh(tid)

A simple state machine that walks the manager through four configuration
parameters for the Dream Engine nightly-learning cycle:

1. 触发时机 (trigger timing)   — default: "low_peak"
2. 覆盖范围 (coverage scope)   — default: "all_squads"
3. 风险阈值 (risk threshold)   — default: 0.3
4. 灰度策略 (canary strategy)  — default: "10_30_100"

Each step presents a question with a recommended default, accepts natural-
language input, validates, and advances.  After the fourth answer the dialog
shows a summary and asks for confirmation.

T4B.3 integration: :func:`on_config_confirmed` is called by the HTTP layer
after ``_persist_dream_config`` writes to disk.  It asks the module-level
:class:`DreamScheduler` (if one was registered via
:func:`dream_scheduler.set_scheduler`) to invalidate its cache for the
tenant.  Safe no-op in test/CLI contexts where no scheduler is running.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Valid options for each parameter
# ---------------------------------------------------------------------------

TRIGGER_OPTIONS: dict[str, str] = {
    "low_peak": "低峰时段自动触发（推荐）",
    "scheduled": "固定时间触发（每日凌晨2:00）",
    "manual": "仅手动触发",
}

COVERAGE_OPTIONS: dict[str, str] = {
    "all_squads": "所有技能组（推荐）",
    "high_volume": "仅高流量技能组",
    "selected": "指定技能组（后续配置）",
}

CANARY_OPTIONS: dict[str, str] = {
    "10_30_100": "10% → 30% → 100%（推荐，稳健）",
    "5_25_100": "5% → 25% → 100%（保守）",
    "30_100": "30% → 100%（快速）",
    "100": "100% 直接全量（不推荐）",
}

# Friendly labels for display
PARAM_LABELS: dict[str, str] = {
    "trigger": "触发时机",
    "coverage": "覆盖范围",
    "risk_threshold": "风险阈值",
    "canary": "灰度策略",
}


# ---------------------------------------------------------------------------
# Dialog state
# ---------------------------------------------------------------------------


class DreamConfigStep(str, Enum):
    """Dialog progression steps."""
    IDLE = "idle"
    ASK_TRIGGER = "ask_trigger"
    ASK_COVERAGE = "ask_coverage"
    ASK_RISK_THRESHOLD = "ask_risk_threshold"
    ASK_CANARY = "ask_canary"
    CONFIRM = "confirm"
    DONE = "done"


_STEP_ORDER: list[DreamConfigStep] = [
    DreamConfigStep.ASK_TRIGGER,
    DreamConfigStep.ASK_COVERAGE,
    DreamConfigStep.ASK_RISK_THRESHOLD,
    DreamConfigStep.ASK_CANARY,
    DreamConfigStep.CONFIRM,
]


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_trigger(text: str) -> str | None:
    """Accept option key, number (1/2/3), or Chinese keyword."""
    t = text.strip().lower()
    if t in TRIGGER_OPTIONS:
        return t
    # Number shortcut
    keys = list(TRIGGER_OPTIONS.keys())
    if t in ("1", "2", "3"):
        idx = int(t) - 1
        if idx < len(keys):
            return keys[idx]
    # Keyword match
    if "低峰" in text or "low" in t:
        return "low_peak"
    if "固定" in text or "scheduled" in t or "定时" in text:
        return "scheduled"
    if "手动" in text or "manual" in t:
        return "manual"
    # Accept bare Enter → default
    if t == "" or t == "默认":
        return "low_peak"
    return None


def _parse_coverage(text: str) -> str | None:
    t = text.strip().lower()
    if t in COVERAGE_OPTIONS:
        return t
    keys = list(COVERAGE_OPTIONS.keys())
    if t in ("1", "2", "3"):
        idx = int(t) - 1
        if idx < len(keys):
            return keys[idx]
    if "所有" in text or "all" in t or "全部" in text:
        return "all_squads"
    if "高流量" in text or "high" in t:
        return "high_volume"
    if "指定" in text or "select" in t:
        return "selected"
    if t == "" or t == "默认":
        return "all_squads"
    return None


def _parse_risk_threshold(text: str) -> float | None:
    """Accept a number between 0.0 and 1.0 (inclusive)."""
    t = text.strip()
    if t == "" or t == "默认":
        return 0.3
    # Strip trailing '%' and convert
    t = t.rstrip("%")
    try:
        val = float(t)
    except ValueError:
        return None
    # If user typed something like 30, interpret as 0.30
    if val > 1.0 and val <= 100.0:
        val = val / 100.0
    if 0.0 <= val <= 1.0:
        return round(val, 2)
    return None


def _parse_canary(text: str) -> str | None:
    t = text.strip().lower().replace(" ", "").replace("→", "_").replace("->", "_").replace(",", "_")
    if t in CANARY_OPTIONS:
        return t
    keys = list(CANARY_OPTIONS.keys())
    if t in ("1", "2", "3", "4"):
        idx = int(t) - 1
        if idx < len(keys):
            return keys[idx]
    if "稳健" in text or "推荐" in text:
        return "10_30_100"
    if "保守" in text:
        return "5_25_100"
    if "快速" in text:
        return "30_100"
    if "全量" in text or "直接" in text:
        return "100"
    if t == "" or t == "默认":
        return "10_30_100"
    return None


def _parse_confirmation(text: str) -> bool | None:
    """Return True for yes, False for no, None for unrecognised."""
    t = text.strip().lower()
    if t in ("yes", "y", "是", "确认", "ok", "好", "好的", "确定"):
        return True
    if t in ("no", "n", "否", "取消", "不", "算了"):
        return False
    return None


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def _options_text(options: dict[str, str]) -> str:
    lines: list[str] = []
    for i, (key, desc) in enumerate(options.items(), 1):
        lines.append(f"  {i}. {key} — {desc}")
    return "\n".join(lines)


def _trigger_prompt() -> str:
    return (
        "🌙 Dream Engine 配置 (1/4) — 触发时机\n\n"
        "Dream Engine 应在什么时候启动夜间学习？\n\n"
        f"{_options_text(TRIGGER_OPTIONS)}\n\n"
        "请输入选项编号或名称（直接回车使用推荐值 low_peak）:"
    )


def _coverage_prompt() -> str:
    return (
        "🌙 Dream Engine 配置 (2/4) — 覆盖范围\n\n"
        "Dream Engine 应覆盖哪些技能组？\n\n"
        f"{_options_text(COVERAGE_OPTIONS)}\n\n"
        "请输入选项编号或名称（直接回车使用推荐值 all_squads）:"
    )


def _risk_threshold_prompt() -> str:
    return (
        "🌙 Dream Engine 配置 (3/4) — 风险阈值\n\n"
        "允许的最大风险阈值是多少？\n"
        "（0.0 = 零风险容忍，1.0 = 接受所有变更）\n"
        "推荐值: 0.3\n\n"
        "请输入 0.0-1.0 之间的数值（直接回车使用推荐值 0.3）:"
    )


def _canary_prompt() -> str:
    return (
        "🌙 Dream Engine 配置 (4/4) — 灰度策略\n\n"
        "新策略的灰度发布阶段如何设置？\n\n"
        f"{_options_text(CANARY_OPTIONS)}\n\n"
        "请输入选项编号或名称（直接回车使用推荐值 10_30_100）:"
    )


def _confirm_prompt(params: dict[str, Any]) -> str:
    lines = [
        "🌙 Dream Engine 配置确认\n",
        "请确认以下配置:",
    ]
    for key in ("trigger", "coverage", "risk_threshold", "canary"):
        label = PARAM_LABELS[key]
        val = params.get(key, "?")
        # Add friendly description
        if key == "trigger" and val in TRIGGER_OPTIONS:
            val = f"{val} — {TRIGGER_OPTIONS[val]}"
        elif key == "coverage" and val in COVERAGE_OPTIONS:
            val = f"{val} — {COVERAGE_OPTIONS[val]}"
        elif key == "canary" and val in CANARY_OPTIONS:
            val = f"{val} — {CANARY_OPTIONS[val]}"
        lines.append(f"  · {label}: {val}")
    lines.append("\n确认应用此配置？(yes/no)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Session dataclass
# ---------------------------------------------------------------------------


@dataclass
class DreamConfigSession:
    """Tracks a single Dream Engine configuration dialog."""

    step: DreamConfigStep = DreamConfigStep.IDLE
    params: dict[str, Any] = field(default_factory=dict)

    # -- public API ----------------------------------------------------------

    def start(self) -> str:
        """Begin the dialog. Returns the first prompt."""
        self.step = DreamConfigStep.ASK_TRIGGER
        self.params = {}
        return _trigger_prompt()

    def is_active(self) -> bool:
        """Return True if the dialog is in progress (not IDLE/DONE)."""
        return self.step not in (DreamConfigStep.IDLE, DreamConfigStep.DONE)

    def process_input(self, user_input: str) -> tuple[str, bool]:
        """Advance the state machine with *user_input*.

        Returns ``(response_message, is_complete)``.
        ``is_complete`` is True when the dialog has finished (confirmed or
        cancelled).
        """
        text = user_input.strip()

        # Allow cancellation at any point
        if text.lower() in ("cancel", "取消", "退出", "/cancel"):
            self._reset()
            return ("❌ Dream Engine 配置已取消。", True)

        if self.step == DreamConfigStep.ASK_TRIGGER:
            return self._handle_trigger(text)

        if self.step == DreamConfigStep.ASK_COVERAGE:
            return self._handle_coverage(text)

        if self.step == DreamConfigStep.ASK_RISK_THRESHOLD:
            return self._handle_risk_threshold(text)

        if self.step == DreamConfigStep.ASK_CANARY:
            return self._handle_canary(text)

        if self.step == DreamConfigStep.CONFIRM:
            return self._handle_confirmation(text)

        return ("配置对话未启动。请发送 @Dream Engine 开始配置。", False)

    def get_config(self) -> dict[str, Any]:
        """Return the collected configuration (may be partial)."""
        return dict(self.params)

    # -- step handlers -------------------------------------------------------

    def _handle_trigger(self, text: str) -> tuple[str, bool]:
        parsed = _parse_trigger(text)
        if parsed is None:
            return (
                f"⚠️ 无法识别选项。请输入 1-3 或关键字:\n{_options_text(TRIGGER_OPTIONS)}",
                False,
            )
        self.params["trigger"] = parsed
        self.step = DreamConfigStep.ASK_COVERAGE
        return (_coverage_prompt(), False)

    def _handle_coverage(self, text: str) -> tuple[str, bool]:
        parsed = _parse_coverage(text)
        if parsed is None:
            return (
                f"⚠️ 无法识别选项。请输入 1-3 或关键字:\n{_options_text(COVERAGE_OPTIONS)}",
                False,
            )
        self.params["coverage"] = parsed
        self.step = DreamConfigStep.ASK_RISK_THRESHOLD
        return (_risk_threshold_prompt(), False)

    def _handle_risk_threshold(self, text: str) -> tuple[str, bool]:
        parsed = _parse_risk_threshold(text)
        if parsed is None:
            return (
                "⚠️ 请输入 0.0 到 1.0 之间的数值（例如 0.3 或 30%）:",
                False,
            )
        self.params["risk_threshold"] = parsed
        self.step = DreamConfigStep.ASK_CANARY
        return (_canary_prompt(), False)

    def _handle_canary(self, text: str) -> tuple[str, bool]:
        parsed = _parse_canary(text)
        if parsed is None:
            return (
                f"⚠️ 无法识别选项。请输入 1-4 或关键字:\n{_options_text(CANARY_OPTIONS)}",
                False,
            )
        self.params["canary"] = parsed
        self.step = DreamConfigStep.CONFIRM
        return (_confirm_prompt(self.params), False)

    def _handle_confirmation(self, text: str) -> tuple[str, bool]:
        answer = _parse_confirmation(text)
        if answer is None:
            return ("请回复 yes / no（是 / 否）来确认或取消。", False)
        if answer:
            config = self.get_config()
            self.step = DreamConfigStep.DONE
            return (
                "✅ Dream Engine 配置已保存！\n\n"
                f"  · 触发时机: {config['trigger']}\n"
                f"  · 覆盖范围: {config['coverage']}\n"
                f"  · 风险阈值: {config['risk_threshold']}\n"
                f"  · 灰度策略: {config['canary']}\n\n"
                "配置将在下一个低峰周期生效。",
                True,
            )
        self._reset()
        return ("❌ Dream Engine 配置已取消。", True)

    # -- internal ------------------------------------------------------------

    def _reset(self) -> None:
        self.step = DreamConfigStep.IDLE
        self.params = {}


# ---------------------------------------------------------------------------
# Module-level trigger detection
# ---------------------------------------------------------------------------

_TRIGGER_PATTERNS = [
    r"@dream\s*engine",
    r"dream\s*engine\s*配置",
    r"配置\s*dream\s*engine",
    r"/dream[-_]?config",
]

_TRIGGER_RE = re.compile("|".join(_TRIGGER_PATTERNS), re.IGNORECASE)


def is_dream_config_trigger(text: str) -> bool:
    """Return True if *text* looks like a Dream Engine config request."""
    return bool(_TRIGGER_RE.search(text))


# ---------------------------------------------------------------------------
# T4B.3 — on-confirm hook into DreamScheduler.refresh
# ---------------------------------------------------------------------------


def on_config_confirmed(tenant_id: str) -> None:
    """Notify the :class:`DreamScheduler` that *tenant_id* has new config.

    Called by the HTTP handler in :mod:`autoservice.api_routes` immediately
    after :func:`_persist_dream_config` finishes writing the new ``dream``
    block.  The scheduler's ``refresh`` invalidates its cached config so
    the very next tick re-reads ``config.json`` from disk.

    This function is intentionally resilient:

    * No scheduler registered (tests, CLI) → silent no-op.
    * Already inside an event loop → we schedule the refresh as a task
      so the caller doesn't have to ``await``.
    * No running loop (sync call path) → use ``asyncio.run`` with a
      short-lived loop so the refresh still completes.
    * Any error raised by ``refresh`` is logged and swallowed — a config
      dialog must never fail because a background scheduler is sick.

    The idempotent design is key: :meth:`DreamScheduler.refresh` only
    clears a cache entry, so re-calling or calling on a stopped
    scheduler is cheap and safe.
    """
    try:
        from autoservice.dream_scheduler import get_scheduler
    except ImportError:  # pragma: no cover — defensive, scheduler should exist
        return
    sched = get_scheduler()
    if sched is None:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    try:
        if loop is not None and loop.is_running():
            # Already inside an async context (FastAPI request handler) —
            # schedule as fire-and-forget task so we don't block the
            # response. refresh() is cheap (cache invalidation only).
            asyncio.ensure_future(sched.refresh(tenant_id))
        else:
            # Sync call path — spin up a one-shot loop.
            asyncio.run(sched.refresh(tenant_id))
    except Exception:  # noqa: BLE001
        logger.exception(
            "dream_scheduler.refresh dispatch failed for tenant %s (non-fatal)",
            tenant_id,
        )
