"""Exception hierarchy for ConversationEngine v1.0.

See docs/contracts/conversation-engine.md §6.
"""


class EngineError(Exception):
    """Base class for all ConversationEngine errors."""


class ConversationNotFound(EngineError):
    pass


class ConversationAlreadyClosed(EngineError):
    pass


class IllegalModeTransition(EngineError):
    """from_mode -> to_mode 不在合法转换表中。

    注意：target == current 不在此范围（Q4 决策 → mode.noop 事件）。
    """


class UnknownParticipant(EngineError):
    pass


class PermissionDenied(EngineError):
    """Role 无权执行该命令（见 §6.1 权限矩阵）。"""


class TimerNotFound(EngineError):
    pass


class ValidationError(EngineError):
    """入参格式错误（score 超范围、content 空、since/before_sequence 同传等）。"""
