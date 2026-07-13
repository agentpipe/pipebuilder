from __future__ import annotations

import hashlib
import json
from pathlib import Path

from support import HarnessBuilderE2ECase
from support.model import CaseMetadata
from support.sandbox import FIXTURES, HARNESSBUILDER, snapshot_tree


class GoldenBuildCases(HarnessBuilderE2ECase):
    metadata = CaseMetadata(
        tier="offline",
        requirements=("BUILD", "WORKSPACE", "ADAPTERS", "LOCK", "GOLDEN"),
        tags=("golden", "all-agents", "idempotence"),
        agents=("codex", "cursor", "codebuddy", "claude-code"),
    )

    def setUp(self) -> None:
        super().setUp()
        self.use_fixture("minimal-all-agents")
        self.expected = FIXTURES / "spaces" / "minimal-all-agents" / "expected"

    def test_static_fixture_matches_full_managed_tree_and_file_goldens(self):
        before = self.box.snapshot_inputs()
        payload = self.expect_ok(self.box.builder("build"))
        self.assertEqual(payload["summary"], {"generated": 25, "removed": 0, "skills": 1})
        lock = json.loads((self.box.root / ".harness-builder/lock.json").read_text(encoding="utf-8"))
        actual_targets = sorted(item["target"] for item in lock["artifacts"])
        expected_targets = json.loads((self.expected / "managed-targets.json").read_text(encoding="utf-8"))
        self.assertEqual(actual_targets, expected_targets)
        self.assertEqual(
            (self.box.root / ".harness-builder/generated/workspace-rule.md").read_text(encoding="utf-8"),
            (self.expected / "files/workspace-rule.md").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            (self.box.root / "AGENTS.md").read_text(encoding="utf-8"),
            (self.expected / "files/AGENTS.md").read_text(encoding="utf-8"),
        )
        self.assertEqual(self.box.snapshot_inputs(), before)

    def test_build_is_byte_stable_and_leaves_no_temporary_artifacts(self):
        self.expect_ok(self.box.builder("build"))
        first = snapshot_tree(self.box.root)
        self.expect_ok(self.box.builder("build"))
        self.assertEqual(snapshot_tree(self.box.root), first)
        leftovers = [item["path"] for item in first if ".tmp-" in item["path"] or item["path"].endswith("build.lock")]
        self.assertEqual(leftovers, [])

    def test_lock_digests_sources_adapters_and_paths_match_actual_outputs(self):
        self.expect_ok(self.box.builder("build"))
        lock = json.loads((self.box.root / ".harness-builder/lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["schema"], "harnessbuilder-lock.v1")
        self.assertEqual(lock["space"]["workspace"], "golden-space.code-workspace")
        self.assertEqual([item["id"] for item in lock["agents"]], ["codex", "cursor", "codebuddy", "claude-code"])
        self.assertNotIn(str(self.box.base), json.dumps(lock))
        for artifact in lock["artifacts"]:
            path = self.box.root / artifact["target"]
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(artifact["digest"], "sha256:" + digest, artifact["target"])
            self.assertTrue(artifact["sources"], artifact["target"])
            self.assertIn(artifact["operation"], {"copy", "render", "merge-document", "merge-json", "merge-toml"})

    def test_common_skill_is_identical_for_all_agents_and_excludes_extensions(self):
        self.expect_ok(self.box.builder("build"))
        targets = [
            self.box.root / ".agents/skills/portable",
            self.box.root / ".cursor/skills/portable",
            self.box.root / ".codebuddy/skills/portable",
            self.box.root / ".claude/skills/portable",
        ]
        snapshots = [snapshot_tree(path) for path in targets]
        self.assertTrue(all(item == snapshots[0] for item in snapshots[1:]))
        self.assertFalse(any((path / ".harness-agents").exists() for path in targets))
        self.assertIn("custom-field: preserved", (targets[0] / "SKILL.md").read_text(encoding="utf-8"))


class CliContractCases(HarnessBuilderE2ECase):
    metadata = CaseMetadata(tier="offline", requirements=("CLI", "REPORT"), tags=("cli", "report"))

    def setUp(self) -> None:
        super().setUp()
        self.box.manifest(agents=["codex"])

    def test_check_explain_and_dry_run_are_read_only_and_structured(self):
        before = snapshot_tree(self.box.root)
        for command, args, expected_command in (
            ("check", (), "check"),
            ("explain", (), "explain"),
            ("build", ("--dry-run",), "build --dry-run"),
        ):
            with self.subTest(command=expected_command):
                payload = self.expect_ok(self.box.builder(command, *args))
                self.assertEqual(payload["command"], expected_command)
                self.assertIn("details", payload)
                self.assertEqual(snapshot_tree(self.box.root), before)

    def test_default_cwd_and_explicit_space_have_equivalent_plans(self):
        explicit = self.expect_ok(self.box.builder("explain"))
        cwd = self.expect_ok(self.box.builder("explain", from_cwd=True))
        self.assertEqual(explicit["details"], cwd["details"])

    def test_text_output_and_version_are_human_readable(self):
        text = self.box.builder("check", output_format="text")
        self.assertEqual(text.returncode, 0, text.stdout + text.stderr)
        self.assertIn("OK check fixture-space", text.stdout)
        version = self.box.run_command([str(Path(__import__("sys").executable)), str(HARNESSBUILDER), "--version"])
        self.assertEqual(version.returncode, 0)
        self.assertRegex(version.stdout.strip(), r"^HarnessBuilder \d+\.\d+\.\d+$")

    def test_json_report_contract_for_build_and_clean(self):
        build = self.expect_ok(self.box.builder("build"))
        self.assertEqual(build["command"], "build")
        self.assertEqual(build["space"], "fixture-space")
        self.assertEqual(Path(build["spaceRoot"]), self.box.root.resolve())
        clean = self.expect_ok(self.box.builder("clean"))
        self.assertEqual(clean["command"], "clean")
        self.assertGreater(clean["summary"]["removed"], 0)

    def test_release_artifact_is_single_python_file_and_compiles(self):
        self.assertTrue(HARNESSBUILDER.is_file())
        result = self.box.run_command([str(Path(__import__("sys").executable)), "-m", "py_compile", str(HARNESSBUILDER)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
