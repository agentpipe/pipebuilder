from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any


def redact(value: str) -> str:
    result = value
    sensitive_names = re.compile(r"(?i)(token|secret|password|passwd|api[_-]?key|authorization|credential)")
    for key, secret in os.environ.items():
        if sensitive_names.search(key) and len(secret) >= 8:
            result = result.replace(secret, "<redacted>")
    patterns = (
        r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}",
        r"(?i)((?:token|secret|password|passwd|api[_-]?key|authorization|credential)\s*[:=]\s*[\"']?)[^\s\"']{8,}",
        r"\bsk-[A-Za-z0-9_-]{8,}\b",
    )
    for pattern in patterns:
        result = re.sub(pattern, r"\1<redacted>" if "(" in pattern else "<redacted>", result)
    return result


@dataclass
class CommandResult:
    argv: list[str]
    cwd: str
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False

    def json(self) -> dict[str, Any]:
        return json.loads(self.stdout)

    def report_record(self) -> dict[str, Any]:
        return {
            "argv": [redact(item) for item in self.argv],
            "cwd": self.cwd,
            "returncode": self.returncode,
            "durationSeconds": round(self.duration_seconds, 6),
            "timedOut": self.timed_out,
            "stdout": redact(self.stdout[-12000:]),
            "stderr": redact(self.stderr[-12000:]),
        }


@dataclass
class CaseMetadata:
    tier: str = "offline"
    requirements: tuple[str, ...] = field(default_factory=tuple)
    tags: tuple[str, ...] = field(default_factory=tuple)
    agents: tuple[str, ...] = field(default_factory=tuple)
    parallel_safe: bool = True


def diagnostic_codes(result: CommandResult) -> list[str]:
    return [item["code"] for item in result.json().get("diagnostics", [])]
