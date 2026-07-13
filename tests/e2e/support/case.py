from __future__ import annotations

import os
import re
import shutil
import unittest
from pathlib import Path
from typing import Any

from .model import CaseMetadata, CommandResult, diagnostic_codes
from .sandbox import REPO_ROOT, Sandbox


ARTIFACTS = REPO_ROOT / "tests" / "e2e" / ".artifacts"


class HarnessBuilderE2ECase(unittest.TestCase):
    metadata = CaseMetadata()

    def setUp(self) -> None:
        self.box = Sandbox()

    def run(self, result: unittest.TestResult | None = None) -> unittest.TestResult:
        active_result = result or self.defaultTestResult()
        try:
            super().run(active_result)
            failed_ids = {item.id() for item, _ in active_result.failures + active_result.errors}
            failed = any(item == self.id() or item.startswith(self.id() + " ") for item in failed_ids)
            if failed and hasattr(self, "box"):
                safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", self.id())
                self.box.archive(ARTIFACTS / safe_id)
            return active_result
        finally:
            if hasattr(self, "box"):
                self.box.close()

    @property
    def command_records(self) -> list[dict[str, Any]]:
        if not hasattr(self, "box"):
            return []
        return [item.report_record() for item in self.box.commands]

    def use_fixture(self, name: str) -> None:
        self.box.close()
        self.box = Sandbox(name)

    def expect_ok(self, result: CommandResult) -> dict[str, Any]:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = result.json()
        self.assertEqual(payload["schema"], "harnessbuilder-report.v1")
        self.assertEqual(payload["status"], "ok")
        self.assertFalse((self.box.root / ".harness-builder/build.lock").exists())
        return payload

    def expect_code(self, result: CommandResult, code: str, *, returncode: int = 1) -> dict[str, Any]:
        self.assertEqual(result.returncode, returncode, result.stdout + result.stderr)
        payload = result.json()
        self.assertEqual(payload["schema"], "harnessbuilder-report.v1")
        self.assertEqual(payload["status"], "error")
        self.assertIn(code, diagnostic_codes(result))
        for diagnostic in payload["diagnostics"]:
            self.assertIsInstance(diagnostic.get("sources"), list, diagnostic)
            self.assertTrue(diagnostic.get("target") or diagnostic.get("semanticKey"), diagnostic)
            self.assertTrue(diagnostic.get("suggestedAction"), diagnostic)
        return payload

    def require_program(self, name: str) -> str:
        found = shutil.which(name)
        if found:
            return found
        if os.environ.get("HARNESSBUILDER_E2E_REQUIRE") == "1":
            self.fail(f"required client is missing: {name}")
        self.skipTest(f"client is not installed: {name}")
        raise AssertionError("unreachable")
