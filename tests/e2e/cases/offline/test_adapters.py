from __future__ import annotations

import json
import os
import tomllib

from support import HarnessBuilderE2ECase, snapshot_tree
from support.model import CaseMetadata


class CodexAdapterCases(HarnessBuilderE2ECase):
    metadata = CaseMetadata(
        tier="offline",
        requirements=("ADAPTER-CODEX", "MERGE", "OWNERSHIP"),
        tags=("adapter", "codex"),
        agents=("codex",),
    )

    def test_all_supported_codex_surfaces_merge_in_stable_source_order(self):
        self.box.skill("provider", "codex-cap")
        self.box.write_text(".harness-builder/agents/codex/AGENTS.md", "SPACE_CODEX\n")
        self.box.write_text(
            ".harness-builder/agents/codex/.codex/config.toml",
            '[mcp_servers."team.server"]\ncommand = "python3"\nargs = ["space.py"]\n',
        )
        self.box.write_json(
            ".harness-builder/agents/codex/.codex/hooks.json",
            {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "python3 shared.py"}]}]}},
        )
        self.box.write_text(".harness-builder/agents/codex/.codex/hooks/space.py", "print('space')\n", executable=True)
        self.box.write_text(".harness-builder/agents/codex/.codex/rules/space.rules", 'prefix_rule(pattern = ["git"], decision = "prompt")\n')
        self.box.write_text("provider/codex-cap/.harness-agents/codex/AGENTS.md", "SKILL_CODEX\n")
        self.box.write_text("provider/codex-cap/.harness-agents/codex/.codex/config.toml", '[agents.review]\ndescription = "Review"\n')
        self.box.write_json(
            "provider/codex-cap/.harness-agents/codex/.codex/hooks.json",
            {"hooks": {"Stop": [
                {"hooks": [{"type": "command", "command": "python3 shared.py"}]},
                {"hooks": [{"type": "command", "command": "python3 skill.py"}]},
            ]}},
        )
        self.box.write_text("provider/codex-cap/.harness-agents/codex/.codex/hooks/skill.py", "print('skill')\n")
        self.box.write_text("provider/codex-cap/.harness-agents/codex/.codex/rules/skill.rules", 'prefix_rule(pattern = ["python"], decision = "allow")\n')
        self.box.manifest(agents=["codex"], skills=["codex-cap"], providers=[{"type": "folder", "path": "provider"}])
        self.expect_ok(self.box.builder("build"))
        agents = (self.box.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertLess(agents.index("HarnessBuilder Workspace"), agents.index("SPACE_CODEX"))
        self.assertLess(agents.index("SPACE_CODEX"), agents.index("SKILL_CODEX"))
        config = tomllib.loads((self.box.root / ".codex/config.toml").read_text(encoding="utf-8"))
        self.assertEqual(config["mcp_servers"]["team.server"]["args"], ["space.py"])
        self.assertEqual(config["agents"]["review"]["description"], "Review")
        groups = json.loads((self.box.root / ".codex/hooks.json").read_text(encoding="utf-8"))["hooks"]["Stop"]
        self.assertEqual([item["hooks"][0]["command"] for item in groups], ["python3 shared.py", "python3 skill.py"])
        self.assertTrue(os.access(self.box.root / ".codex/hooks/space.py", os.X_OK))
        self.assertTrue((self.box.root / ".codex/hooks/skill.py").is_file())
        self.assertTrue((self.box.root / ".codex/rules/space.rules").is_file())
        self.assertTrue((self.box.root / ".codex/rules/skill.rules").is_file())
        explain = self.expect_ok(self.box.builder("explain"))
        rule = next(item for item in explain["details"]["operations"] if item["target"] == ".codex/rules/skill.rules")
        self.assertIn("experimental-platform-surface", {item["kind"] for item in rule["risks"]})
        lock = json.loads((self.box.root / ".harness-builder/lock.json").read_text(encoding="utf-8"))
        locked_rule = next(item for item in lock["artifacts"] if item["target"] == ".codex/rules/skill.rules")
        self.assertEqual(locked_rule["risks"], rule["risks"])

    def test_project_machine_keys_are_rejected_but_project_keys_are_allowed(self):
        forbidden = ("model_provider", "openai_base_url", "notify", "profile", "otel")
        for key in forbidden:
            self.box.close(); self.box = __import__("support").Sandbox()
            self.box.manifest(agents=["codex"])
            self.box.write_text(".harness-builder/agents/codex/.codex/config.toml", f'{key} = "forbidden"\n')
            with self.subTest(key=key):
                self.expect_code(self.box.builder("check"), "HB011")
        self.box.close(); self.box = __import__("support").Sandbox()
        self.box.manifest(agents=["codex"])
        self.box.write_text(".harness-builder/agents/codex/.codex/config.toml", 'approval_policy = "never"\n[sandbox_workspace_write]\nnetwork_access = false\n')
        self.expect_ok(self.box.builder("build"))

    def test_generated_targets_are_restored_from_sources(self):
        self.box.manifest(agents=["codex"])
        self.box.write_text(".harness-builder/agents/codex/AGENTS.md", "SOURCE_GUIDANCE\n")
        self.box.write_text(".harness-builder/agents/codex/.codex/config.toml", 'approval_policy = "never"\n')
        self.expect_ok(self.box.builder("build"))
        (self.box.root / "AGENTS.md").write_text("TARGET_DRIFT\n", encoding="utf-8")
        (self.box.root / ".codex/config.toml").write_text('approval_policy = "on-request"\n', encoding="utf-8")
        self.expect_ok(self.box.builder("build"))
        self.assertIn("SOURCE_GUIDANCE", (self.box.root / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertNotIn("TARGET_DRIFT", (self.box.root / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertEqual(tomllib.loads((self.box.root / ".codex/config.toml").read_text())["approval_policy"], "never")


class OtherAdapterCases(HarnessBuilderE2ECase):
    metadata = CaseMetadata(
        tier="offline",
        requirements=("ADAPTER-CURSOR", "ADAPTER-CODEBUDDY", "ADAPTER-CLAUDE"),
        tags=("adapter", "native-surfaces"),
        agents=("cursor", "codebuddy", "claude-code"),
    )

    def test_cursor_rules_commands_skills_and_workspace_rule(self):
        self.box.skill("provider", "cursor-cap")
        self.box.write_text(".harness-builder/agents/cursor/.cursor/rules/space.mdc", "---\ndescription: Space\nalwaysApply: true\n---\nSPACE\n")
        self.box.write_text("provider/cursor-cap/.harness-agents/cursor/.cursor/rules/team.mdc", "---\nglobs: ['**/*.py']\n---\nTEAM\n")
        self.box.write_text("provider/cursor-cap/.harness-agents/cursor/.cursor/commands/check.md", "CHECK\n")
        self.box.manifest(agents=["cursor"], skills=["cursor-cap"], providers=[{"type": "folder", "path": "provider"}])
        self.expect_ok(self.box.builder("build"))
        for path in (
            ".cursor/rules/harnessbuilder-workspace.mdc",
            ".cursor/rules/space.mdc",
            ".cursor/rules/team.mdc",
            ".cursor/commands/check.md",
            ".cursor/skills/cursor-cap/SKILL.md",
        ):
            self.assertTrue((self.box.root / path).is_file(), path)

    def test_codebuddy_commands_agents_settings_mcp_hooks_skills_and_workspace_rule(self):
        self.box.skill("provider", "codebuddy-cap")
        self.box.write_text("provider/codebuddy-cap/.harness-agents/codebuddy/.codebuddy/commands/check.md", "CHECK\n")
        self.box.write_text("provider/codebuddy-cap/.harness-agents/codebuddy/.codebuddy/agents/review.md", "---\nname: review\ndescription: Review changes\n---\nREVIEW\n")
        self.box.write_json("provider/codebuddy-cap/.harness-agents/codebuddy/.codebuddy/settings.json", {"hooks": {"stop": [{"command": "python3 stop.py"}]}})
        self.box.write_json("provider/codebuddy-cap/.harness-agents/codebuddy/.codebuddy/mcp.json", {"mcpServers": {"local": {"command": "python3"}}})
        self.box.write_text("provider/codebuddy-cap/.harness-agents/codebuddy/.codebuddy/hooks/stop.py", "print('stop')\n", executable=True)
        self.box.manifest(agents=["codebuddy"], skills=["codebuddy-cap"], providers=[{"type": "folder", "path": "provider"}])
        self.expect_ok(self.box.builder("build"))
        for path in (
            ".codebuddy/rules/harnessbuilder-workspace.md",
            ".codebuddy/commands/check.md",
            ".codebuddy/agents/review.md",
            ".codebuddy/settings.json",
            ".codebuddy/mcp.json",
            ".codebuddy/hooks/stop.py",
            ".codebuddy/skills/codebuddy-cap/SKILL.md",
        ):
            self.assertTrue((self.box.root / path).is_file(), path)
        self.assertTrue(os.access(self.box.root / ".codebuddy/hooks/stop.py", os.X_OK))

    def test_claude_instructions_rules_commands_agents_settings_mcp_hooks_and_skills(self):
        self.box.skill("provider", "claude-cap")
        base = "provider/claude-cap/.harness-agents/claude-code"
        self.box.write_text(f"{base}/CLAUDE.md", "CLAUDE_GUIDANCE\n")
        self.box.write_text(f"{base}/.claude/rules/team.md", "TEAM\n")
        self.box.write_text(f"{base}/.claude/commands/check.md", "CHECK\n")
        self.box.write_text(f"{base}/.claude/agents/review.md", "---\nname: review\ndescription: Review changes\n---\nREVIEW\n")
        self.box.write_json(f"{base}/.claude/settings.json", {"hooks": {"Stop": [{"command": "python3 stop.py"}]}})
        self.box.write_json(f"{base}/.mcp.json", {"mcpServers": {"local": {"command": "python3"}}})
        self.box.write_text(f"{base}/.claude/hooks/stop.py", "print('stop')\n", executable=True)
        self.box.manifest(agents=["claude-code"], skills=["claude-cap"], providers=[{"type": "folder", "path": "provider"}])
        payload = self.expect_ok(self.box.builder("build"))
        self.assertIn("HBW002", [item["code"] for item in payload["diagnostics"]])
        for path in (
            "CLAUDE.md",
            ".claude/rules/harnessbuilder-workspace.md",
            ".claude/rules/team.md",
            ".claude/commands/check.md",
            ".claude/agents/review.md",
            ".claude/settings.json",
            ".mcp.json",
            ".claude/hooks/stop.py",
            ".claude/skills/claude-cap/SKILL.md",
        ):
            self.assertTrue((self.box.root / path).is_file(), path)

    def test_unselected_agent_sources_are_not_read_or_projected(self):
        self.box.skill("provider", "scoped")
        self.box.write_text(".harness-builder/agents/cursor/unsupported/bad.txt", "ignored\n")
        self.box.write_text("provider/scoped/.harness-agents/cursor/unsupported/bad.txt", "ignored\n")
        self.box.manifest(agents=["codex"], skills=["scoped"], providers=[{"type": "folder", "path": "provider"}])
        self.expect_ok(self.box.builder("build"))
        self.assertFalse((self.box.root / ".cursor").exists())

    def test_unknown_space_agent_namespace_is_rejected_even_when_empty(self):
        self.box.manifest(agents=["codex"])
        (self.box.root / ".harness-builder/agents/not-an-agent").mkdir(parents=True)
        self.expect_code(self.box.builder("check"), "HB009")


class AdapterRejectionCases(HarnessBuilderE2ECase):
    metadata = CaseMetadata(tier="offline", requirements=("HB009", "HB010", "HB011"), tags=("adapter", "negative"))

    def test_gated_and_unknown_native_surfaces_are_rejected(self):
        cases = (
            ("codex", ".codex/commands/no.md", "no"),
            ("codebuddy", ".codebuddy/rules/no.md", "no"),
            ("cursor", ".cursor/agents/no.md", "no"),
            ("claude-code", ".claude/unknown/no.txt", "no"),
        )
        for agent, relative, content in cases:
            self.box.close(); self.box = __import__("support").Sandbox()
            self.box.manifest(agents=[agent])
            self.box.write_text(f".harness-builder/agents/{agent}/{relative}", content)
            with self.subTest(agent=agent, relative=relative):
                self.expect_code(self.box.builder("check"), "HB009")

    def test_empty_unsupported_native_directories_are_not_silently_ignored(self):
        cases = (
            ("codex", ".codex/commands"),
            ("cursor", ".cursor/agents"),
            ("codebuddy", ".codebuddy/rules"),
            ("claude-code", ".claude/plugins"),
        )
        for agent, relative in cases:
            self.box.close(); self.box = __import__("support").Sandbox()
            self.box.manifest(agents=[agent])
            (self.box.root / f".harness-builder/agents/{agent}/{relative}").mkdir(parents=True)
            with self.subTest(agent=agent, relative=relative):
                self.expect_code(self.box.builder("check"), "HB009")

    def test_invalid_cursor_rule_agent_frontmatter_json_and_toml_are_rejected(self):
        cases = (
            ("cursor", ".cursor/rules/bad.mdc", "---\nunknown: x\n---\n", "HB009"),
            ("codebuddy", ".codebuddy/agents/bad.md", "---\nname: bad\n---\n", "HB009"),
            ("claude-code", ".claude/settings.json", "[", "HB009"),
            ("codex", ".codex/config.toml", "[broken", "HB009"),
            ("codex", ".codex/hooks.json", '{"hooks":{"Stop":[{"matcher":"x"}]}}', "HB009"),
            ("codebuddy", ".codebuddy/settings.json", '{"hooks":{"Stop":"not-a-list"}}', "HB009"),
            ("claude-code", ".claude/settings.json", '{"permissions":{"defaultMode":"bypassPermissions"}}', "HB011"),
        )
        for agent, relative, content, code in cases:
            self.box.close(); self.box = __import__("support").Sandbox()
            self.box.manifest(agents=[agent])
            self.box.write_text(f".harness-builder/agents/{agent}/{relative}", content)
            with self.subTest(agent=agent, relative=relative):
                self.expect_code(self.box.builder("check"), code)

    def test_hook_command_secret_literals_are_rejected_but_environment_references_are_allowed(self):
        self.box.manifest(agents=["codex"])
        path = ".harness-builder/agents/codex/.codex/hooks.json"
        self.box.write_json(
            path,
            {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "curl -H 'Authorization: Bearer literal-secret' https://example.invalid"}]}]}},
        )
        self.expect_code(self.box.builder("check"), "HB011")
        self.box.write_json(
            path,
            {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "curl -H 'Authorization: Bearer ${HOOK_TOKEN}' https://example.invalid"}]}]}},
        )
        payload = self.expect_ok(self.box.builder("explain"))
        hooks = next(item for item in payload["details"]["operations"] if item["target"] == ".codex/hooks.json")
        self.assertTrue(hooks["risks"])

    def test_agent_rule_mcp_and_toml_semantic_shapes_are_validated(self):
        cases = (
            ("codebuddy", ".codebuddy/agents/bad.md", "---\nname: bad\ndescription: Bad\ntools:\n  nested: invalid\n---\n", "HB009"),
            ("claude-code", ".claude/rules/bad.md", "---\npaths:\n  nested: invalid\n---\n", "HB009"),
            ("claude-code", ".claude/agents/bad.md", "---\nname: bad\ndescription: Bad\nisolation: container\n---\n", "HB009"),
            ("claude-code", ".mcp.json", '{"mcpServers":[]}', "HB009"),
            ("codex", ".codex/config.toml", '[[agents]]\nname = "unsupported-array-table"\n', "HB009"),
        )
        for agent, relative, content, code in cases:
            self.box.close(); self.box = __import__("support").Sandbox()
            self.box.manifest(agents=[agent])
            self.box.write_text(f".harness-builder/agents/{agent}/{relative}", content)
            with self.subTest(agent=agent, relative=relative):
                self.expect_code(self.box.builder("check"), code)

        self.box.close(); self.box = __import__("support").Sandbox()
        self.box.manifest(agents=["claude-code"])
        self.box.write_text(
            ".harness-builder/agents/claude-code/.claude/agents/reviewer.md",
            "---\nname: reviewer\ndescription: Review\nskills: [missing-skill]\n---\n",
        )
        self.expect_code(self.box.builder("check"), "HB009")

    def test_same_target_and_semantic_key_conflicts_fail_before_writes(self):
        self.box.skill("provider", "conflict")
        self.box.write_text(".harness-builder/agents/codex/.codex/config.toml", '[agents.review]\ndescription = "Space"\n')
        self.box.write_text("provider/conflict/.harness-agents/codex/.codex/config.toml", '[agents.review]\ndescription = "Skill"\n')
        self.box.manifest(agents=["codex"], skills=["conflict"], providers=[{"type": "folder", "path": "provider"}])
        before = snapshot_tree(self.box.root)
        payload = self.expect_code(self.box.builder("build"), "HB010")
        self.assertEqual(payload["diagnostics"][0]["semanticKey"], "agents.review.description")
        self.assertEqual(snapshot_tree(self.box.root), before)

    def test_command_and_agent_semantic_name_collisions_are_portable(self):
        cases = (
            ("cursor", ".cursor/commands/team/Check.md", ".cursor/commands/release/check.md"),
            ("codebuddy", ".codebuddy/commands/check.md", ".codebuddy/commands/CHECK.md"),
            ("claude-code", ".claude/commands/team/check.md", ".claude/commands/team/CHECK.md"),
        )
        for agent, one, two in cases:
            self.box.close(); self.box = __import__("support").Sandbox()
            self.box.manifest(agents=[agent])
            self.box.write_text(f".harness-builder/agents/{agent}/{one}", "one\n")
            self.box.write_text(f".harness-builder/agents/{agent}/{two}", "two\n")
            with self.subTest(agent=agent):
                self.expect_code(self.box.builder("check"), "HB010")

    def test_secret_literals_rejected_and_environment_references_preserved_without_lock_leak(self):
        self.box.manifest(agents=["claude-code"])
        self.box.write_json(".harness-builder/agents/claude-code/.mcp.json", {"mcpServers": {"bad": {"command": "python3", "api_key": "literal-secret"}}})
        self.expect_code(self.box.builder("check"), "HB011")
        self.box.write_json(".harness-builder/agents/claude-code/.mcp.json", {"mcpServers": {"safe": {"command": "python3", "headers": {"authorization": "${MCP_TOKEN}"}}}})
        self.expect_ok(self.box.builder("build"))
        self.assertIn("${MCP_TOKEN}", (self.box.root / ".mcp.json").read_text(encoding="utf-8"))
        lock_text = (self.box.root / ".harness-builder/lock.json").read_text(encoding="utf-8")
        self.assertNotIn("literal-secret", lock_text)
        self.assertNotIn(os.environ.get("MCP_TOKEN", "never-present-value"), lock_text)
