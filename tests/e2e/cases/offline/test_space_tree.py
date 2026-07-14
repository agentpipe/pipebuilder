from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from support import HarnessBuilderE2ECase, Sandbox, snapshot_tree
from support.model import CaseMetadata


class HSpaceTreeCases(HarnessBuilderE2ECase):
    metadata = CaseMetadata(
        tier="offline",
        requirements=("HSPACE-TREE", "HB017", "TREE-OWNERSHIP", "TREE-RECOVERY"),
        tags=("tree", "children", "ownership", "recovery"),
        parallel_safe=False,
    )

    def setUp(self) -> None:
        super().setUp()
        self.box.manifest(name="leader", agents=["codex"])

    def add_child(
        self,
        relative: str,
        name: str,
        *,
        providers: list[dict] | None = None,
    ) -> Path:
        root = self.box.root / relative
        root.mkdir(parents=True, exist_ok=True)
        self.box.write_json(
            f"{relative}/harness-space.json",
            {
                "schema": "harness-space.v1",
                "name": name,
                "agents": ["codex"],
                "skills": [],
                "tags": [],
                "skillProviders": providers or [],
            },
        )
        self.box.write_json(f"{relative}/{name}.code-workspace", {"folders": [{"name": "project", "path": "."}]})
        return root

    def write_tree(self, children: list[tuple[str, str]]) -> None:
        self.box.write_json(
            "harness-space-tree.json",
            {
                "schema": "harness-space-tree.v1",
                "children": [{"path": path, "expectName": name} for path, name in children],
            },
        )

    def reset(self) -> None:
        self.box.close()
        self.box = Sandbox()
        self.box.manifest(name="leader", agents=["codex"])

    def assert_tree_operation_locks_absent(self) -> None:
        self.assertFalse((self.box.root / ".harness-builder/tree-build.lock").exists())
        for root in (self.box.root, *sorted((self.box.root / "children").glob("*"))):
            self.assertFalse((root / ".harness-builder/build.lock").exists())

    def test_check_explain_build_verify_and_reverse_clean(self):
        first = self.add_child("children/worker-01", "worker-01")
        second = self.add_child("children/worker-02", "worker-02")
        self.write_tree([("children/worker-01", "worker-01"), ("children/worker-02", "worker-02")])

        before = snapshot_tree(self.box.root)
        checked = self.expect_ok(self.box.builder("check-tree"))
        self.assertEqual([item["path"] for item in checked["details"]["members"]], [".", "children/worker-01", "children/worker-02"])
        self.assertEqual(snapshot_tree(self.box.root), before)

        explained = self.expect_ok(self.box.builder("explain-tree"))
        self.assertEqual(explained["summary"]["members"], 3)
        self.assertEqual(snapshot_tree(self.box.root), before)

        built = self.expect_ok(self.box.builder("build-tree"))
        self.assertEqual(built["summary"]["members"], 3)
        self.assertTrue((self.box.root / ".harness-builder/tree-lock.json").is_file())
        self.assertFalse((self.box.root / ".harness-builder/tree-journal.json").exists())
        for root in (self.box.root, first, second):
            self.assertTrue((root / ".harness-builder/lock.json").is_file())
            self.assertTrue((root / "AGENTS.md").is_file())
        receipt = json.loads((self.box.root / ".harness-builder/tree-lock.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["schema"], "harness-space-tree-lock.v1")
        self.assertEqual([item["path"] for item in receipt["members"]], [".", "children/worker-01", "children/worker-02"])
        self.assert_tree_operation_locks_absent()

        verified = self.expect_ok(self.box.builder("verify-tree"))
        self.assertEqual(verified["summary"], {"members": 3, "verified": 3})

        cleaned = self.expect_ok(self.box.builder("clean-tree"))
        self.assertEqual([item["path"] for item in cleaned["details"]["members"]], ["children/worker-02", "children/worker-01", "."])
        self.assertFalse((self.box.root / ".harness-builder/tree-lock.json").exists())
        self.assertFalse((self.box.root / ".harness-builder/tree-journal.json").exists())
        for root in (self.box.root, first, second):
            self.assertFalse((root / "AGENTS.md").exists())
            self.assertFalse((root / ".harness-builder/lock.json").exists())
            self.assertTrue((root / "harness-space.json").is_file())
        self.assert_tree_operation_locks_absent()

    def test_single_space_build_remains_parent_only(self):
        child = self.add_child("children/worker-01", "worker-01")
        self.write_tree([("children/worker-01", "worker-01")])
        self.expect_ok(self.box.builder("build"))
        self.assertTrue((self.box.root / "AGENTS.md").is_file())
        self.assertFalse((child / "AGENTS.md").exists())
        self.assertFalse((self.box.root / ".harness-builder/tree-lock.json").exists())

    def test_tree_manifest_rejects_escape_reserved_nested_and_identity_mismatch(self):
        cases = (
            "escape",
            "reserved-root",
            "reserved-name",
            "drive-path",
            "nested-children",
            "nested-tree",
            "identity",
            "parent-identity",
        )
        for case in cases:
            self.reset()
            if case == "escape":
                outside = self.box.base / "outside"
                outside.mkdir()
                self.write_tree([("../outside", "outside")])
            elif case == "reserved-root":
                self.add_child(".harness-builder/worker-01", "worker-01")
                self.write_tree([(".harness-builder/worker-01", "worker-01")])
            elif case == "reserved-name":
                self.add_child("children/con", "worker-01")
                self.write_tree([("children/con", "worker-01")])
            elif case == "drive-path":
                self.write_tree([("C:/worker-01", "worker-01")])
            elif case == "nested-children":
                self.add_child("children/worker-01", "worker-01")
                self.add_child("children/worker-01/grandchild", "grandchild")
                self.write_tree(
                    [("children/worker-01", "worker-01"), ("children/worker-01/grandchild", "grandchild")]
                )
            elif case == "nested-tree":
                self.add_child("children/worker-01", "worker-01")
                self.box.write_json(
                    "children/worker-01/harness-space-tree.json",
                    {"schema": "harness-space-tree.v1", "children": []},
                )
                self.write_tree([("children/worker-01", "worker-01")])
            elif case == "identity":
                self.add_child("children/worker-01", "actual-name")
                self.write_tree([("children/worker-01", "expected-name")])
            else:
                self.add_child("children/worker-01", "leader")
                self.write_tree([("children/worker-01", "leader")])
            before = snapshot_tree(self.box.root)
            with self.subTest(case=case):
                self.expect_code(self.box.builder("check-tree"), "HB017")
                self.assertEqual(snapshot_tree(self.box.root), before)

    def test_symlink_child_is_rejected_without_writes(self):
        target = self.add_child("real-worker", "worker-01")
        children = self.box.root / "children"
        children.mkdir()
        try:
            os.symlink(target, children / "worker-01", target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"directory symlink unavailable: {exc}")
        self.write_tree([("children/worker-01", "worker-01")])
        before = snapshot_tree(self.box.root)
        self.expect_code(self.box.builder("check-tree"), "HB017")
        self.assertEqual(snapshot_tree(self.box.root), before)

    def test_parent_post_cannot_stale_a_child_plan(self):
        child = self.add_child("children/worker-01", "worker-01")
        provider = self.box.root / "parent-provider"
        provider.mkdir()
        self.box.write_text(
            "parent-provider/mutate.py",
            "from pathlib import Path\n"
            "root = Path(__file__).resolve().parent.parent\n"
            "path = root / 'children/worker-01/worker-01.code-workspace'\n"
            "path.write_text(path.read_text(encoding='utf-8') + ' \\n', encoding='utf-8')\n",
        )
        self.box.manifest(
            name="leader",
            agents=["codex"],
            providers=[
                {
                    "type": "folder",
                    "path": "parent-provider",
                    "command": {"cwd": ".", "args": [sys.executable, "mutate.py"]},
                }
            ],
        )
        self.write_tree([("children/worker-01", "worker-01")])

        self.expect_code(self.box.builder("build-tree"), "HB017")
        self.assertTrue((self.box.root / ".harness-builder/lock.json").is_file())
        self.assertFalse((child / ".harness-builder/lock.json").exists())
        journal = json.loads((self.box.root / ".harness-builder/tree-journal.json").read_text(encoding="utf-8"))
        self.assertEqual([item["stage"] for item in journal["members"]], ["post-succeeded", "stale-plan"])
        self.assertFalse((self.box.root / ".harness-builder/tree-lock.json").exists())
        self.assert_tree_operation_locks_absent()

    def test_post_failure_records_partial_journal_and_rerun_converges(self):
        child = self.add_child(
            "children/worker-01",
            "worker-01",
            providers=[
                {
                    "type": "folder",
                    "path": "provider",
                    "command": {"cwd": ".", "args": [sys.executable, "fail.py"]},
                }
            ],
        )
        provider = child / "provider"
        provider.mkdir()
        self.box.write_text("children/worker-01/provider/fail.py", "raise SystemExit(23)\n")
        self.write_tree([("children/worker-01", "worker-01")])

        self.expect_code(self.box.builder("build-tree"), "HB016")
        journal_path = self.box.root / ".harness-builder/tree-journal.json"
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        self.assertEqual(journal["status"], "partial")
        self.assertEqual([item["stage"] for item in journal["members"]], ["post-succeeded", "post-failed"])
        self.assertTrue((child / ".harness-builder/lock.json").is_file())
        self.assertFalse((self.box.root / ".harness-builder/tree-lock.json").exists())

        manifest = json.loads((child / "harness-space.json").read_text(encoding="utf-8"))
        manifest["skillProviders"] = []
        self.box.write_json("children/worker-01/harness-space.json", manifest)
        self.expect_ok(self.box.builder("build-tree"))
        self.assertFalse(journal_path.exists())
        self.expect_ok(self.box.builder("verify-tree"))

    def test_final_verification_failure_records_partial_journal(self):
        provider = self.box.root / "parent-provider"
        provider.mkdir()
        self.box.write_text(
            "parent-provider/mutate.py",
            "from pathlib import Path\n"
            "root = Path(__file__).resolve().parent.parent\n"
            "(root / 'AGENTS.md').write_text('post drift\\n', encoding='utf-8')\n",
        )
        self.box.manifest(
            name="leader",
            agents=["codex"],
            providers=[
                {
                    "type": "folder",
                    "path": "parent-provider",
                    "command": {"cwd": ".", "args": [sys.executable, "mutate.py"]},
                }
            ],
        )
        self.add_child("children/worker-01", "worker-01")
        self.write_tree([("children/worker-01", "worker-01")])

        self.expect_code(self.box.builder("build-tree"), "HB017")
        journal = json.loads((self.box.root / ".harness-builder/tree-journal.json").read_text(encoding="utf-8"))
        self.assertEqual(journal["status"], "partial")
        self.assertEqual([item["stage"] for item in journal["members"]], ["post-succeeded", "post-succeeded"])
        self.assertFalse((self.box.root / ".harness-builder/tree-lock.json").exists())
        self.assert_tree_operation_locks_absent()

    def test_clean_tree_preflights_every_member_before_deleting(self):
        first = self.add_child("children/worker-01", "worker-01")
        second = self.add_child("children/worker-02", "worker-02")
        self.write_tree([("children/worker-01", "worker-01"), ("children/worker-02", "worker-02")])
        self.expect_ok(self.box.builder("build-tree"))
        drifted = first / "AGENTS.md"
        drifted.unlink()
        drifted.mkdir()
        before = snapshot_tree(self.box.root)
        self.expect_code(self.box.builder("clean-tree"), "HB010")
        self.assertEqual(snapshot_tree(self.box.root), before)
        self.assertTrue((self.box.root / "AGENTS.md").is_file())
        self.assertTrue((second / "AGENTS.md").is_file())
        self.assert_tree_operation_locks_absent()

    def test_tree_receipt_rejects_membership_drift(self):
        self.add_child("children/worker-01", "worker-01")
        self.add_child("children/worker-02", "worker-02")
        self.write_tree([("children/worker-01", "worker-01"), ("children/worker-02", "worker-02")])
        self.expect_ok(self.box.builder("build-tree"))
        self.write_tree([("children/worker-02", "worker-02"), ("children/worker-01", "worker-01")])
        self.expect_code(self.box.builder("verify-tree"), "HB017")
        self.expect_code(self.box.builder("build-tree"), "HB017")
        self.expect_code(self.box.builder("clean-tree"), "HB017")
