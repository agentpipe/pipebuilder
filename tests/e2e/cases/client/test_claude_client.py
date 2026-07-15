from __future__ import annotations

from support import PipeBuilderE2ECase
from support.model import CaseMetadata


class ClaudeClientCases(PipeBuilderE2ECase):
    metadata = CaseMetadata(
        tier="client",
        requirements=("CLAUDE-INSTALLED", "CLAUDE-DISCOVERY", "SKILL-DISCOVERY", "SETTINGS-DISCOVERY", "MCP-DISCOVERY"),
        tags=("claude-code", "client", "no-model"),
        agents=("claude-code",),
        parallel_safe=False,
    )

    def setUp(self) -> None:
        super().setUp()
        self.claude = self.require_program("claude")
        version_probe = self.box.run_command([self.claude, "--version"], cwd=self.box.root)
        self.assertEqual(version_probe.returncode, 0, version_probe.stdout + version_probe.stderr)
        self.client_record = {
            "id": "claude-code",
            "executable": self.claude,
            "version": version_probe.stdout.strip(),
            "verificationLevel": "client-parsed",
            "model": None,
        }
        self.use_example("all-agents-golden")
        self.expect_ok(self.box.builder("build"))

    def client(self, *args: str, timeout: float = 60):
        return self.box.run_command([self.claude, *args], cwd=self.box.root, timeout=timeout)

    def test_client_version_is_recorded_and_supported_command_surface_exists(self):
        version = self.client("--version")
        self.assertEqual(version.returncode, 0, version.stdout + version.stderr)
        self.assertRegex(version.stdout.strip(), r"^\d+\.\d+\.\d+")
        help_result = self.client("--help")
        self.assertEqual(help_result.returncode, 0, help_result.stdout + help_result.stderr)
        for option in ("--settings", "--mcp-config", "doctor", "--print"):
            self.assertIn(option, help_result.stdout)

    def test_real_mcp_discovery_reads_generated_project_mcp_config(self):
        result = self.client("mcp", "list")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("hb_fixture", result.stdout)

    def test_real_client_accepts_generated_settings_without_model_request(self):
        settings = self.box.root / ".claude/settings.json"
        self.assertTrue(settings.is_file())
        result = self.client("agents", "--json", "--settings", str(settings))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "[]")

    def test_generated_claude_artifacts_exist_for_client_discovery_paths(self):
        for path in (
            "CLAUDE.md",
            ".claude/rules/pipebuilder-workspace.md",
            ".claude/rules/golden.md",
            ".claude/skills/portable/SKILL.md",
            ".mcp.json",
            ".claude/settings.json",
            ".claude/hooks/probe.py",
        ):
            with self.subTest(path=path):
                target = self.box.root / path
                self.assertTrue(target.is_file(), path)
                self.assertTrue(target.read_text(encoding="utf-8").strip(), path)
        self.assertIn("GOLDEN_CLAUDE_SPACE_GUIDANCE", (self.box.root / "CLAUDE.md").read_text(encoding="utf-8"))
