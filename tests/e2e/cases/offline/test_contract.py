from __future__ import annotations

import hashlib
import json
import shutil
import stat
from pathlib import Path

from support import PipeBuilderE2ECase
from support.model import CaseMetadata
from support.sandbox import EXAMPLES, PIPEBUILDER, REPO_ROOT, Sandbox, snapshot_tree


class GoldenBuildCases(PipeBuilderE2ECase):
    metadata = CaseMetadata(
        tier="offline",
        requirements=("BUILD", "WORKSPACE", "ADAPTERS", "LOCK", "GOLDEN"),
        tags=("golden", "all-agents", "idempotence"),
        agents=("codex", "cursor", "codebuddy", "claude-code"),
    )

    def setUp(self) -> None:
        super().setUp()
        self.use_example("all-agents-golden")
        self.expected = EXAMPLES / "all-agents-golden" / "expected"

    def test_static_example_matches_full_managed_tree_and_file_goldens(self):
        before = self.box.snapshot_inputs()
        payload = self.expect_ok(self.box.builder("build"))
        self.assertEqual(payload["summary"], {"generated": 28, "removed": 0, "skills": 1})
        lock = json.loads((self.box.root / ".pipebuilder/lock.json").read_text(encoding="utf-8"))
        actual_targets = sorted(item["target"] for item in lock["artifacts"])
        expected_targets = json.loads((self.expected / "managed-targets.json").read_text(encoding="utf-8"))
        self.assertEqual(actual_targets, expected_targets)
        self.assertEqual(
            (self.box.root / ".pipebuilder/generated/workspace-rule.md").read_text(encoding="utf-8"),
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
        lock = json.loads((self.box.root / ".pipebuilder/lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["schema"], "pipebuilder-lock.v1")
        self.assertEqual(lock["pipespace"]["workspace"], "golden-space.code-workspace")
        self.assertEqual([item["id"] for item in lock["agents"]], ["codex", "cursor", "codebuddy", "claude-code"])
        self.assertEqual(
            [item["capabilityStatus"] for item in lock["agents"]],
            ["client-verified", "client-verified", "generated-only", "client-verified"],
        )
        self.assertNotIn(str(self.box.base), json.dumps(lock))
        for artifact in lock["artifacts"]:
            path = self.box.root / artifact["target"]
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(artifact["digest"], "sha256:" + digest, artifact["target"])
            self.assertTrue(artifact["sources"], artifact["target"])
            self.assertTrue(artifact["semanticKey"], artifact["target"])
            self.assertIsInstance(artifact["risks"], list)
            self.assertIn(artifact["operation"], {"copy", "render", "merge-document", "merge-json", "merge-toml"})
        for provider in lock["providers"]:
            self.assertIn("resolvedPath", provider)
            self.assertEqual(provider["snapshot"], provider["digest"])

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
        self.assertFalse(any((path / ".pipe-agents").exists() for path in targets))
        self.assertIn("custom-field: preserved", (targets[0] / "SKILL.md").read_text(encoding="utf-8"))


class CliContractCases(PipeBuilderE2ECase):
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
        version = self.box.run_command([str(Path(__import__("sys").executable)), str(PIPEBUILDER), "--version"])
        self.assertEqual(version.returncode, 0)
        self.assertEqual(version.stdout.strip(), "PipeBuilder 0.1.2")

    def test_json_report_contract_for_build_and_clean(self):
        build = self.expect_ok(self.box.builder("build"))
        self.assertEqual(build["command"], "build")
        self.assertEqual(build["pipespace"], "fixture-space")
        self.assertEqual(Path(build["pipespaceRoot"]), self.box.root.resolve())
        clean = self.expect_ok(self.box.builder("clean"))
        self.assertEqual(clean["command"], "clean")
        self.assertGreater(clean["summary"]["removed"], 0)

    def test_runner_command_records_redact_credentials(self):
        secret = "sk-pipebuilder-secret-123456789"
        result = self.box.run_command(
            [str(Path(__import__("sys").executable)), "-c", f"print('authorization=Bearer {secret}')"],
        )
        self.assertEqual(result.returncode, 0)
        serialized = json.dumps(result.report_record())
        self.assertNotIn(secret, serialized)
        self.assertIn("<redacted>", serialized)

    def test_sandbox_cleanup_handles_readonly_git_objects(self):
        readonly = self.box.write_bytes(
            "repos/catalog/.git/objects/40/object",
            b"fixture",
            base=self.box.base,
        )
        readonly.chmod(stat.S_IREAD)
        sandbox_root = self.box.base
        self.box.close()
        self.assertFalse(sandbox_root.exists())
        self.box = Sandbox()

    def test_release_artifact_is_single_python_file_and_compiles(self):
        self.assertTrue(PIPEBUILDER.is_file())
        first_hundred_lines = "\n".join(PIPEBUILDER.read_text(encoding="utf-8").splitlines()[:100])
        for expected in (
            "independently distributable single-file CLI",
            "Quick start",
            "pipespace.json",
            "exactly one of branch or tag",
            "Ownership and outputs",
        ):
            self.assertIn(expected, first_hundred_lines)
        result = self.box.run_command([str(Path(__import__("sys").executable)), "-m", "py_compile", str(PIPEBUILDER)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        release = self.box.base / "standalone-release" / "pipebuilder.py"
        release.parent.mkdir()
        shutil.copy2(PIPEBUILDER, release)
        help_result = self.box.run_command([str(Path(__import__("sys").executable)), str(release), "--help"], cwd=self.box.base)
        self.assertEqual(help_result.returncode, 0, help_result.stdout + help_result.stderr)
        for expected in ("Quick start", "Git Provider", ".pipebuilder/lock.json", "--offline", "verify"):
            self.assertIn(expected, help_result.stdout)
        self.assertNotIn("build-tree", help_result.stdout)
        standalone = self.box.run_command(
            [str(Path(__import__("sys").executable)), str(release), "build", str(self.box.root), "--format", "json"],
            cwd=self.box.base,
        )
        self.assertEqual(standalone.returncode, 0, standalone.stdout + standalone.stderr)
        self.assertTrue((self.box.root / ".pipebuilder/lock.json").is_file())

    def test_release_source_compiles_on_minimum_supported_python(self):
        source = PIPEBUILDER.read_text(encoding="utf-8")
        compile(source, str(PIPEBUILDER), "exec", dont_inherit=True)
        self.assertIn("Python 3.7+", source[:4000])


class InitCases(PipeBuilderE2ECase):
    metadata = CaseMetadata(tier="offline", requirements=("CLI", "INIT", "MANIFEST", "WORKSPACE"), tags=("init", "idempotence"))

    def test_empty_space_is_initialized_and_second_run_only_validates(self):
        first = self.expect_ok(self.box.builder("init"))
        self.assertEqual(first["pipespace"], "space")
        self.assertEqual(first["summary"], {"created": 2, "validated": 0})
        manifest = json.loads((self.box.root / "pipespace.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["agents"], ["codex", "cursor", "codebuddy", "claude-code"])
        self.assertTrue((self.box.root / "space.code-workspace").is_file())
        before = snapshot_tree(self.box.root)

        second = self.expect_ok(self.box.builder("init"))
        self.assertEqual(second["summary"], {"created": 0, "validated": 2})
        self.assertEqual(snapshot_tree(self.box.root), before)
        self.expect_ok(self.box.builder("check"))

    def test_init_creates_a_missing_target_directory_and_supports_explicit_name(self):
        target = self.box.base / "nested" / "new-project"
        result = self.box.run_command(
            [str(Path(__import__("sys").executable)), str(PIPEBUILDER), "init", str(target), "--name", "web-game", "--format", "json"],
            cwd=self.box.base,
        )
        payload = self.expect_ok(result)
        self.assertEqual(payload["pipespace"], "web-game")
        self.assertTrue((target / "pipespace.json").is_file())
        self.assertTrue((target / "web-game.code-workspace").is_file())

        invalid_target = self.box.base / "Invalid Directory"
        invalid = self.box.run_command(
            [str(Path(__import__("sys").executable)), str(PIPEBUILDER), "init", str(invalid_target), "--format", "json"],
            cwd=self.box.base,
        )
        self.expect_code(invalid, "PB002")
        self.assertFalse((invalid_target / "pipespace.json").exists())

    def test_existing_manifest_is_preserved_while_missing_workspace_is_created(self):
        manifest = {
            "schema": "pipespace.v1",
            "name": "custom-space",
            "agents": ["codex"],
            "skills": [],
            "tags": [],
            "skillProviders": [],
        }
        self.box.write_json("pipespace.json", manifest)
        before = (self.box.root / "pipespace.json").read_bytes()
        payload = self.expect_ok(self.box.builder("init"))
        self.assertEqual(payload["summary"], {"created": 1, "validated": 1})
        self.assertEqual((self.box.root / "pipespace.json").read_bytes(), before)
        self.assertTrue((self.box.root / "custom-space.code-workspace").is_file())

    def test_invalid_existing_required_file_fails_without_creating_the_other(self):
        self.box.write_text("pipespace.json", "{invalid")
        before = snapshot_tree(self.box.root)
        self.expect_code(self.box.builder("init"), "PB001")
        self.assertEqual(snapshot_tree(self.box.root), before)

        (self.box.root / "pipespace.json").unlink()
        self.box.write_text("space.code-workspace", "{invalid")
        before = snapshot_tree(self.box.root)
        self.expect_code(self.box.builder("init"), "PB004")
        self.assertEqual(snapshot_tree(self.box.root), before)

    def test_project_local_bootstrap_creates_a_buildable_self_hosted_pipespace(self):
        project = self.box.base / "sample-project"
        shared = project / "pipespaces/shared/skills/pipebuilder"
        space = project / "pipespaces/sample-project-dev"
        (shared / "scripts").mkdir(parents=True)
        for relative in ("SKILL.md", "pipebuilder.py", "scripts/update.py"):
            shutil.copy2(REPO_ROOT / relative, shared / relative)

        initialized = self.box.run_command(
            [
                str(Path(__import__("sys").executable)),
                str(PIPEBUILDER),
                "init",
                str(space),
                "--name",
                "sample-project-dev",
                "--project",
                "../..",
                "--shared-skills",
                "../shared/skills",
                "--format",
                "json",
            ],
            cwd=project,
        )
        self.expect_ok(initialized)
        manifest = json.loads((space / "pipespace.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["skills"], ["pipebuilder"])
        self.assertEqual(
            manifest["skillProviders"],
            [{"type": "folder", "path": "../shared/skills"}],
        )
        workspace = json.loads(
            (space / "sample-project-dev.code-workspace").read_text(encoding="utf-8")
        )
        self.assertEqual(
            workspace["folders"],
            [
                {"name": "pipeline", "path": "."},
                {"name": "project", "path": "../.."},
            ],
        )
        repeated = self.box.run_command(
            [
                str(Path(__import__("sys").executable)),
                str(PIPEBUILDER),
                "init",
                str(space),
                "--name",
                "sample-project-dev",
                "--project",
                "../..",
                "--shared-skills",
                "../shared/skills",
                "--format",
                "json",
            ],
            cwd=project,
        )
        repeated_payload = self.expect_ok(repeated)
        self.assertEqual(repeated_payload["summary"], {"created": 0, "validated": 2})
        for command in ("check", "build", "verify"):
            result = self.box.run_command(
                [
                    str(Path(__import__("sys").executable)),
                    str(PIPEBUILDER),
                    command,
                    str(space),
                    "--format",
                    "json",
                ],
                cwd=project,
            )
            self.expect_ok(result)
        self.assertTrue((space / ".agents/skills/pipebuilder/SKILL.md").is_file())
        self.assertTrue((space / ".cursor/skills/pipebuilder/SKILL.md").is_file())

    def test_bootstrap_paths_are_relative_existing_and_contain_pipebuilder(self):
        project = self.box.base / "sample-project"
        project.mkdir()
        space = project / "pipespaces/sample-project-dev"
        missing_shared = project / "pipespaces/shared/skills"
        missing_shared.mkdir(parents=True)

        absolute = self.box.run_command(
            [
                str(Path(__import__("sys").executable)),
                str(PIPEBUILDER),
                "init",
                str(space),
                "--project",
                str(project),
                "--format",
                "json",
            ],
            cwd=project,
        )
        self.expect_code(absolute, "PB001")
        missing_skill = self.box.run_command(
            [
                str(Path(__import__("sys").executable)),
                str(PIPEBUILDER),
                "init",
                str(space),
                "--project",
                "../..",
                "--shared-skills",
                "../shared/skills",
                "--format",
                "json",
            ],
            cwd=project,
        )
        self.expect_code(missing_skill, "PB005")
        self.assertFalse((space / "pipespace.json").exists())
        self.assertFalse(any(space.glob("*.code-workspace")))
