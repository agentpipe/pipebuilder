from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time

from support import HarnessBuilderE2ECase, snapshot_tree
from support.model import CaseMetadata, CommandResult
from support.sandbox import HARNESSBUILDER


class OwnershipLifecycleCases(HarnessBuilderE2ECase):
    metadata = CaseMetadata(
        tier="offline",
        requirements=("OWNERSHIP", "CLEAN", "IDEMPOTENCE"),
        tags=("ownership", "lifecycle"),
    )

    def test_clean_removes_only_lock_owned_files_is_idempotent_and_rebuilds(self):
        self.box.skill("provider", "portable")
        self.box.manifest(agents=["codex", "cursor"], skills=["portable"], providers=[{"type": "folder", "path": "provider"}])
        inputs = self.box.snapshot_inputs()
        self.expect_ok(self.box.builder("build"))
        built = self.box.managed_tree()
        self.box.write_text(".cursor/user-note.txt", "keep\n")
        self.box.write_text("user.txt", "keep\n")
        inputs = self.box.snapshot_inputs()
        first = self.expect_ok(self.box.builder("clean"))
        second = self.expect_ok(self.box.builder("clean"))
        self.assertGreater(first["summary"]["removed"], 0)
        self.assertEqual(second["summary"]["removed"], 0)
        self.assertTrue((self.box.root / ".cursor/user-note.txt").is_file())
        self.assertTrue((self.box.root / "user.txt").is_file())
        self.assertEqual(self.box.snapshot_inputs(), inputs)
        self.expect_ok(self.box.builder("build"))
        self.assertEqual(self.box.managed_tree(), built)

    def test_deselecting_skill_removes_common_and_native_outputs(self):
        self.box.skill("provider", "temporary")
        self.box.write_text("provider/temporary/.harness-agents/cursor/.cursor/commands/temp.md", "TEMP\n")
        self.box.manifest(agents=["cursor"], skills=["temporary"], providers=[{"type": "folder", "path": "provider"}])
        self.expect_ok(self.box.builder("build"))
        manifest = json.loads((self.box.root / "harness-space.json").read_text())
        manifest["skills"] = []
        self.box.write_json("harness-space.json", manifest)
        payload = self.expect_ok(self.box.builder("build"))
        self.assertGreaterEqual(payload["summary"]["removed"], 2)
        self.assertFalse((self.box.root / ".cursor/skills/temporary").exists())
        self.assertFalse((self.box.root / ".cursor/commands/temp.md").exists())

    def test_removing_agent_cleans_only_that_agents_outputs(self):
        self.box.manifest(agents=["codex", "cursor"])
        self.expect_ok(self.box.builder("build"))
        manifest = json.loads((self.box.root / "harness-space.json").read_text())
        manifest["agents"] = ["cursor"]
        self.box.write_json("harness-space.json", manifest)
        self.expect_ok(self.box.builder("build"))
        self.assertFalse((self.box.root / "AGENTS.md").exists())
        self.assertFalse((self.box.root / ".agents").exists())
        self.assertTrue((self.box.root / ".cursor/rules/harnessbuilder-workspace.mdc").is_file())

    def test_source_change_updates_target_and_lock_without_mutating_source(self):
        self.box.manifest(agents=["codex"])
        source = self.box.write_text(".harness-builder/agents/codex/AGENTS.md", "VERSION_ONE\n")
        self.expect_ok(self.box.builder("build"))
        old_lock = (self.box.root / ".harness-builder/lock.json").read_bytes()
        source.write_text("VERSION_TWO\n", encoding="utf-8")
        source_before = source.read_bytes()
        self.expect_ok(self.box.builder("build"))
        self.assertEqual(source.read_bytes(), source_before)
        self.assertIn("VERSION_TWO", (self.box.root / "AGENTS.md").read_text(encoding="utf-8"))
        self.assertNotEqual(old_lock, (self.box.root / ".harness-builder/lock.json").read_bytes())

    def test_deleted_managed_file_and_old_builder_version_converge_on_rebuild(self):
        self.box.manifest(agents=["codex"])
        self.expect_ok(self.box.builder("build"))
        (self.box.root / "AGENTS.md").unlink()
        lock_path = self.box.root / ".harness-builder/lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["builder"]["version"] = "0.0.0-old"
        lock["builder"]["digest"] = "sha256:" + "0" * 64
        for artifact in lock["artifacts"]:
            artifact.pop("semanticKey", None)
            artifact.pop("risks", None)
        for provider in lock["providers"]:
            provider.pop("resolvedPath", None)
            provider.pop("snapshot", None)
        for agent in lock["agents"]:
            agent.pop("capabilityStatus", None)
        self.box.write_json(".harness-builder/lock.json", lock)
        self.expect_ok(self.box.builder("build"))
        self.assertTrue((self.box.root / "AGENTS.md").is_file())
        rebuilt = json.loads(lock_path.read_text(encoding="utf-8"))
        self.assertNotEqual(rebuilt["builder"]["version"], "0.0.0-old")

    def test_clean_without_lock_never_guesses_ownership(self):
        self.box.manifest(agents=["codex"])
        self.box.write_text("AGENTS.md", "unowned\n")
        self.expect_ok(self.box.builder("clean"))
        self.assertEqual((self.box.root / "AGENTS.md").read_text(), "unowned\n")


class LockAndInterruptionCases(HarnessBuilderE2ECase):
    metadata = CaseMetadata(
        tier="offline",
        requirements=("HB013", "HB014", "INTERRUPTION", "CONCURRENCY"),
        tags=("lock", "concurrency", "recovery"),
        parallel_safe=False,
    )

    def setUp(self) -> None:
        super().setUp()
        self.box.manifest(agents=["codex"])

    def test_two_real_build_processes_fail_fast_for_the_loser(self):
        argv = [sys.executable, str(HARNESSBUILDER), "build", str(self.box.root), "--format", "json"]
        first = subprocess.Popen(
            argv,
            cwd=self.box.root,
            env=self.box.controlled_env({"HARNESSBUILDER_TEST_HOLD_LOCK_MILLISECONDS": "1500"}),
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        lock = self.box.root / ".harness-builder/build.lock"
        deadline = time.monotonic() + 5
        while not lock.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(lock.exists(), "first process did not acquire build.lock")
        second = self.box.builder("build")
        self.expect_code(second, "HB013")
        stdout, stderr = first.communicate(timeout=10)
        self.box.commands.append(CommandResult(argv, str(self.box.root), first.returncode or 0, stdout, stderr, 0))
        self.assertEqual(first.returncode, 0, stdout + stderr)
        self.assertFalse(lock.exists())

    def test_active_stale_and_malformed_locks_have_stable_semantics(self):
        lock = ".harness-builder/build.lock"
        self.box.write_json(lock, {"pid": os.getpid(), "host": socket.gethostname(), "startedAt": "test"})
        self.expect_code(self.box.builder("build"), "HB013")
        self.box.write_json(lock, {"pid": 99999999, "host": socket.gethostname(), "startedAt": "test"})
        payload = self.expect_code(self.box.builder("build"), "HB014")
        self.assertIn("suggestedAction", payload["diagnostics"][0])
        self.box.write_text(lock, "not-json\n")
        self.expect_code(self.box.builder("build"), "HB013")

    def test_injected_crash_leaves_stale_lock_and_manual_recovery_converges(self):
        crashed = self.box.builder("build", env={"HARNESSBUILDER_TEST_CRASH_AFTER_WRITES": "1"})
        self.assertEqual(crashed.returncode, 97, crashed.stdout + crashed.stderr)
        lock = self.box.root / ".harness-builder/build.lock"
        self.assertTrue(lock.is_file())
        self.assertFalse((self.box.root / ".harness-builder/lock.json").exists())
        self.expect_code(self.box.builder("build"), "HB014")
        lock.unlink()
        self.expect_ok(self.box.builder("build"))

    def test_apply_failure_keeps_old_lock_and_next_build_converges(self):
        self.expect_ok(self.box.builder("build"))
        old_lock = (self.box.root / ".harness-builder/lock.json").read_bytes()
        self.box.write_text(".harness-builder/agents/codex/.codex/config.toml", 'approval_policy = "never"\n')
        failed = self.box.builder("build", env={"HARNESSBUILDER_TEST_FAIL_AFTER_WRITES": "1"})
        self.expect_code(failed, "HB011")
        self.assertEqual((self.box.root / ".harness-builder/lock.json").read_bytes(), old_lock)
        self.assertFalse((self.box.root / ".harness-builder/build.lock").exists())
        self.expect_ok(self.box.builder("build"))
        self.assertNotEqual((self.box.root / ".harness-builder/lock.json").read_bytes(), old_lock)


class FilesystemBoundaryCases(HarnessBuilderE2ECase):
    metadata = CaseMetadata(
        tier="offline",
        requirements=("HB010", "HB011", "PATH-SAFETY"),
        tags=("filesystem", "symlink", "conflict"),
    )

    def test_unowned_target_requires_explicit_migration(self):
        self.box.manifest(agents=["codex"])
        self.box.write_text("AGENTS.md", "human target\n")
        before = snapshot_tree(self.box.root)
        payload = self.expect_code(self.box.builder("build"), "HB010")
        self.assertIn("suggestedAction", payload["diagnostics"][0])
        self.assertEqual(snapshot_tree(self.box.root), before)

    def test_owned_file_type_drift_is_preflighted_before_build_or_clean_changes_anything(self):
        self.box.skill("provider", "drift")
        self.box.manifest(agents=["codex"], skills=["drift"], providers=[{"type": "folder", "path": "provider"}])
        self.expect_ok(self.box.builder("build"))
        target = self.box.root / ".agents/skills/drift/SKILL.md"
        target.unlink(); target.mkdir()
        before = snapshot_tree(self.box.root)
        self.expect_code(self.box.builder("build"), "HB010")
        self.assertEqual(snapshot_tree(self.box.root), before)
        self.expect_code(self.box.builder("clean"), "HB010")
        self.assertEqual(snapshot_tree(self.box.root), before)

    def test_target_parent_symlink_escape_is_rejected_without_outside_write(self):
        self.box.manifest(agents=["codex"])
        self.box.write_text(".harness-builder/agents/codex/.codex/config.toml", 'approval_policy = "never"\n')
        outside = self.box.base / "outside"
        outside.mkdir()
        os.symlink(outside, self.box.root / ".codex")
        self.expect_code(self.box.builder("build"), "HB011")
        self.assertEqual(list(outside.iterdir()), [])

    def test_case_only_path_collisions_are_rejected_for_cross_platform_portability(self):
        self.box.manifest(agents=["cursor"])
        self.box.write_text(".harness-builder/agents/cursor/.cursor/commands/Check.md", "one\n")
        self.box.write_text(".harness-builder/agents/cursor/.cursor/commands/check.md", "two\n")
        self.expect_code(self.box.builder("check"), "HB010")

    def test_unicode_normalization_collisions_and_windows_reserved_names_are_rejected(self):
        self.box.manifest(agents=["cursor"])
        self.box.write_text(".harness-builder/agents/cursor/.cursor/commands/caf\u00e9.md", "one\n")
        self.box.write_text(".harness-builder/agents/cursor/.cursor/commands/cafe\u0301.md", "two\n")
        self.expect_code(self.box.builder("check"), "HB010")

        self.box.close(); self.box = __import__("support").Sandbox()
        self.box.manifest(agents=["cursor"])
        self.box.write_text(".harness-builder/agents/cursor/.cursor/commands/CON.md", "reserved\n")
        self.expect_code(self.box.builder("check"), "HB011")

    def test_invalid_existing_lock_is_not_trusted_or_replaced(self):
        self.box.manifest(agents=["codex"])
        self.box.write_text(".harness-builder/lock.json", "{}\n")
        before = snapshot_tree(self.box.root)
        self.expect_code(self.box.builder("build"), "HB001")
        self.assertEqual(snapshot_tree(self.box.root), before)

    def test_forged_lock_cannot_claim_or_clean_a_human_owned_file(self):
        self.box.manifest(agents=["codex"])
        self.box.write_text("user-owned.txt", "keep\n")
        self.box.write_json(
            ".harness-builder/lock.json",
            {
                "schema": "harnessbuilder-lock.v1",
                "builder": {"version": "0.1.0", "digest": "sha256:" + "0" * 64},
                "space": {},
                "agents": [],
                "providers": [],
                "skills": [],
                "artifacts": [{"target": "user-owned.txt"}],
            },
        )
        before = snapshot_tree(self.box.root)
        self.expect_code(self.box.builder("clean"), "HB001")
        self.assertEqual(snapshot_tree(self.box.root), before)
        self.assertEqual((self.box.root / "user-owned.txt").read_text(encoding="utf-8"), "keep\n")

    def test_builder_state_directory_symlink_is_rejected_before_lock_write(self):
        self.box.manifest(agents=["codex"])
        outside = self.box.base / "outside-builder-state"
        outside.mkdir()
        os.symlink(outside, self.box.root / ".harness-builder")
        argv = [sys.executable, str(HARNESSBUILDER), "build", str(self.box.root), "--format", "json"]
        process = subprocess.Popen(
            argv,
            cwd=self.box.root,
            env=self.box.controlled_env({"HARNESSBUILDER_TEST_HOLD_LOCK_MILLISECONDS": "750"}),
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        outside_lock = outside / "build.lock"
        deadline = time.monotonic() + 0.5
        observed_outside_write = False
        while process.poll() is None and time.monotonic() < deadline:
            if outside_lock.exists():
                observed_outside_write = True
                break
            time.sleep(0.01)
        stdout, stderr = process.communicate(timeout=5)
        self.box.commands.append(CommandResult(argv, str(self.box.root), process.returncode or 0, stdout, stderr, 0))
        self.assertEqual(process.returncode, 1, stdout + stderr)
        self.assertIn("HB011", stdout)
        self.assertFalse(observed_outside_write, "build.lock was created outside the Harness Space")
        self.assertEqual(list(outside.iterdir()), [])

    def test_provider_cannot_reside_inside_generated_target_namespace(self):
        self.box.skill(".agents/skills", "recursive")
        self.box.manifest(agents=["codex"], providers=[{"type": "folder", "path": ".agents/skills"}])
        self.expect_code(self.box.builder("check"), "HB011")
