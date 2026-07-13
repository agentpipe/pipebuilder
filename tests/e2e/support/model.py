from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


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
            "argv": self.argv,
            "cwd": self.cwd,
            "returncode": self.returncode,
            "durationSeconds": round(self.duration_seconds, 6),
            "timedOut": self.timed_out,
            "stdout": self.stdout[-12000:],
            "stderr": self.stderr[-12000:],
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
