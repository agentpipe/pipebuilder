from __future__ import annotations

from support import PipeBuilderE2ECase
from support.model import CaseMetadata


class CursorClientCases(PipeBuilderE2ECase):
    metadata = CaseMetadata(
        tier="client",
        requirements=("CURSOR-INSTALLED", "RULE-DISCOVERY", "SKILL-DISCOVERY", "COMMAND-DISCOVERY", "MCP-DISCOVERY"),
        tags=("cursor", "client", "no-model"),
        agents=("cursor",),
        parallel_safe=False,
    )

    def setUp(self) -> None:
        super().setUp()
        self.cursor = self.require_program("cursor-agent")
        version_probe = self.box.run_command([self.cursor, "--version"], cwd=self.box.root)
        self.assertEqual(version_probe.returncode, 0, version_probe.stdout + version_probe.stderr)
        self.client_record = {
            "id": "cursor",
            "executable": self.cursor,
            "version": version_probe.stdout.strip(),
            "verificationLevel": "client-parsed",
            "model": None,
        }
        self.use_example("all-agents-golden")
        self.expect_ok(self.box.builder("build"))
        self.box.write_json(
            ".cursor/mcp.json",
            {"mcpServers": {"hb_fixture": {"command": "python3", "args": ["-c", "pass"]}}},
        )

    def client(self, *args: str, timeout: float = 30):
        return self.box.run_command([self.cursor, *args], cwd=self.box.root, timeout=timeout)

    def test_client_version_is_recorded_and_supported_command_surface_exists(self):
        version = self.client("--version")
        self.assertEqual(version.returncode, 0, version.stdout + version.stderr)
        self.assertTrue(version.stdout.strip())
        help_result = self.client("help")
        self.assertEqual(help_result.returncode, 0, help_result.stdout + help_result.stderr)
        for option in ("--print", "--trust", "--workspace", "--mode", "mcp"):
            self.assertIn(option, help_result.stdout)

    def test_real_mcp_discovery_reads_workspace_cursor_config(self):
        result = self.client("mcp", "list")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("hb_fixture", result.stdout)

    def test_about_proves_headless_agent_cli_is_operational(self):
        result = self.client("about")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("About Cursor CLI", result.stdout)
        self.assertIn(self.client_record["version"], result.stdout)

    def test_generated_cursor_artifacts_exist_for_client_discovery_paths(self):
        for path in (
            ".cursor/rules/pipebuilder-workspace.mdc",
            ".cursor/rules/space.mdc",
            ".cursor/skills/portable/SKILL.md",
            ".cursor/commands/golden-check.md",
        ):
            with self.subTest(path=path):
                target = self.box.root / path
                self.assertTrue(target.is_file(), path)
                self.assertTrue(target.read_text(encoding="utf-8").strip(), path)
