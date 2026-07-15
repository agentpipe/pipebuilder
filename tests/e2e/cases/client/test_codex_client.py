from __future__ import annotations

import json
import os
import re
from pathlib import Path

from support import PipeBuilderE2ECase
from support.model import CaseMetadata


class CodexClientCases(PipeBuilderE2ECase):
    metadata = CaseMetadata(
        tier="client",
        requirements=("CODEX-INSTALLED", "AGENTS-DISCOVERY", "SKILL-DISCOVERY", "CONFIG-DISCOVERY", "EXECPOLICY"),
        tags=("codex", "client", "no-model"),
        agents=("codex",),
        parallel_safe=False,
    )

    def setUp(self) -> None:
        super().setUp()
        self.codex = self.require_program("codex")
        version_probe = self.box.run_command([self.codex, "--version"], cwd=self.box.root)
        self.assertEqual(version_probe.returncode, 0, version_probe.stdout + version_probe.stderr)
        self.client_record = {
            "id": "codex",
            "executable": str(Path(self.codex).resolve()),
            "version": version_probe.stdout.strip(),
            "verificationLevel": "client-parsed",
            "model": None,
        }
        self.use_fixture("minimal-all-agents")
        git = self.require_program("git")
        initialized = self.box.run_command([git, "init", "-q"], cwd=self.box.root)
        self.assertEqual(initialized.returncode, 0, initialized.stdout + initialized.stderr)
        self.expect_ok(self.box.builder("build"))
        self.codex_home = self.box.home / "codex-home"
        self.codex_home.mkdir(parents=True, exist_ok=True)
        escaped = str(self.box.root).replace("\\", "\\\\").replace('"', '\\"')
        (self.codex_home / "config.toml").write_text(
            f'[projects."{escaped}"]\ntrust_level = "trusted"\n',
            encoding="utf-8",
        )
        self.client_env = {"CODEX_HOME": str(self.codex_home)}

    def client(self, *args: str, timeout: float = 30):
        return self.box.run_command([self.codex, *args], cwd=self.box.root, env=self.client_env, timeout=timeout)

    def prompt_input(self, prompt: str = "$portable Verify discovery.") -> list[dict]:
        result = self.client("-C", str(self.box.root), "debug", "prompt-input", prompt)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_client_version_is_recorded_and_supported_command_surface_exists(self):
        version = self.client("--version")
        self.assertEqual(version.returncode, 0, version.stdout + version.stderr)
        self.assertRegex(version.stdout.strip(), r"^codex-cli \d+\.\d+\.\d+")
        help_result = self.client("exec", "--help")
        self.assertEqual(help_result.returncode, 0)
        for option in ("--json", "--output-last-message", "--ephemeral", "--ignore-user-config"):
            self.assertIn(option, help_result.stdout)

    def test_real_prompt_assembly_discovers_generated_agents_and_common_skill(self):
        prompt = self.prompt_input()
        serialized = json.dumps(prompt, ensure_ascii=False)
        self.assertIn("GOLDEN_CODEX_SPACE_GUIDANCE", serialized)
        self.assertIn("GOLDEN_CODEX_SKILL_GUIDANCE", serialized)
        self.assertIn("PipeSpace: `golden-space`", serialized)
        self.assertIn("- portable: Golden portable fixture", serialized)
        self.assertIn(str(self.box.root / ".agents/skills/portable/SKILL.md"), serialized)
        self.assertNotIn(".pipe-agents/codex", serialized)

    def test_real_prompt_assembly_loads_trusted_generated_project_config(self):
        prompt = self.prompt_input("Return project config sentinel.")
        serialized = json.dumps(prompt, ensure_ascii=False)
        self.assertIn("GOLDEN_CODEX_PROJECT_CONFIG", serialized)

    def test_real_execpolicy_parser_accepts_and_evaluates_generated_rule(self):
        rule = self.box.root / ".codex/rules/golden.rules"
        result = self.client("execpolicy", "check", "--rules", str(rule), "--pretty", "git", "status")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["decision"], "allow")
        self.assertEqual(payload["matchedRules"][0]["prefixRuleMatch"]["matchedPrefix"], ["git", "status"])

    def test_real_client_parses_current_nested_project_hook_schema(self):
        self.box.write_json(
            ".pipebuilder/agents/codex/.codex/hooks.json",
            {"hooks": {"SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": "python3 .codex/hooks/probe.py", "timeout": 10}]}]}},
        )
        self.box.write_text(".pipebuilder/agents/codex/.codex/hooks/probe.py", "import sys\nsys.stdin.read()\n")
        self.expect_ok(self.box.builder("build"))
        result = self.client("-C", str(self.box.root), "debug", "prompt-input", "hook parse probe")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotRegex(result.stderr.lower(), r"invalid.*hook|failed.*hook|parse.*error")
