"""Shared sanitization helpers for persisted event stores.

Both ``fae.tool_audit.ToolAuditStore`` and ``fae.agent_trace.AgentTraceStore``
need the same sensitive-key redaction and length cap when persisting user
content (tool arguments, subagent tasks, results). Keeping the rules in one
place guarantees trace and audit reports stay consistent.
"""

from __future__ import annotations

import json
import re
from typing import Any, Final, Mapping

REDACTED: Final[str] = "[REDACTED]"
MAX_FIELD_CHARS: Final[int] = 20_000

_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|access[_-]?token|authorization|bearer|cookie|password|passwd|secret|token|private[_-]?key|client[_-]?secret)",
    re.IGNORECASE,
)
_SENSITIVE_TEXT = re.compile(
    r"\b(api[_-]?key|access[_-]?token|authorization|bearer|cookie|password|passwd|secret|token)\b(\s*[:=]\s*)([^\s,;]+)",
    re.IGNORECASE,
)


def sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if _SENSITIVE_KEY.search(str(key)) else sanitize_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_value(item) for item in value]
    if isinstance(value, str):
        return _SENSITIVE_TEXT.sub(r"\1\2" + REDACTED, value)
    return value


def safe_json(value: Any) -> str:
    if isinstance(value, str):
        raw = value
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            pass
    else:
        raw = ""
    if raw and isinstance(value, str):
        sanitized = sanitize_value(value)
    else:
        try:
            sanitized = json.dumps(
                sanitize_value(value),
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )
        except (TypeError, ValueError):
            sanitized = str(value)
    return sanitized[:MAX_FIELD_CHARS]


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    return _SENSITIVE_TEXT.sub(r"\1\2" + REDACTED, str(value))[:MAX_FIELD_CHARS]
