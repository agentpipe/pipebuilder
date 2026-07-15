from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from support import PipeBuilderE2ECase, Sandbox, snapshot_tree, try_symlink
from support.model import CaseMetadata


class PipeSpaceTreeCases(PipeBuilderE2ECase):
    metadata = CaseMetadata(
        tier="offline",
        requirements=("CHILD-DISCOVERY", "PB017", "TREE-OWNERSHIP", "TREE-RECOVERY"),
        tags=("tree", "children", "ownership", "recovery"),
        parallel_safe=False,
    )

    def setUp(self) -> None:
        super().setUp()
        self.box.manifest(name="root-space", agents=["codex"])

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
            f"{relative}/pipespace.json",
            {
                "schema": "pipespace.v1",
                "name": name,
                "agents": ["codex"],
                "skills": [],
                "tags": [],
                "skillProviders": providers or [],
            },
        )
        self.box.write_json(
            f"{relative}/{name}.code-workspace",
            {"folders": [{"name": "project", "path": "."}]},
        )
        return root

    def reset(self, *, scan_depth: int | None = None) -> None:
        self.box.close()
        self.box = Sandbox()
        self.box.manifest(
            name="root-space",
            agents=["codex"],
            children_scan_depth=scan_depth,
        )

    def assert_operation_locks_absent(self) -> None:
        self.assertFalse((self.box.root / ".pipebuilder/tree-build.lock").exists())
        for path in self.box.root.rglob(".pipebuilder/build.lock"):
            self.fail(f"operation lock leaked: {path}")

    def test_unified_commands_discover_build_verify_and_reverse_clean(self):
        first = self.add_child("children/child-01", "child-01")
        grandchild = self.add_child("children/child-01/grandchild", "grandchild")
        second = self.add_child("children/child-02", "child-02")
        expected = [
            ".",
            "children/child-01",
            "children/child-01/grandchild",
            "children/child-02",
        ]

        before = snapshot_tree(self.box.root)
        checked = self.expect_ok(self.box.builder("check"))
        self.assertEqual([item["path"] for item in checked["details"]["members"]], expected)
        self.assertEqual(snapshot_tree(self.box.root), before)

        explained = self.expect_ok(self.box.builder("explain"))
        self.assertEqual(explained["summary"]["members"], 4)
        self.assertEqual(explained["details"]["scanDepth"], 3)
        self.assertEqual(snapshot_tree(self.box.root), before)

        built = self.expect_ok(self.box.builder("build"))
        self.assertEqual(built["summary"]["members"], 4)
        for root in (self.box.root, first, grandchild, second):
            self.assertTrue((root / ".pipebuilder/lock.json").is_file())
            self.assertTrue((root / "AGENTS.md").is_file())
        receipt = json.loads(
            (self.box.root / ".pipebuilder/tree-lock.json").read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["tree"]["manifest"], "pipespace.json")
        self.assertEqual([item["path"] for item in receipt["members"]], expected)
        self.assert_operation_locks_absent()

        verified = self.expect_ok(self.box.builder("verify"))
        self.assertEqual(verified["summary"], {"members": 4, "verified": 4})

        cleaned = self.expect_ok(self.box.builder("clean"))
        self.assertEqual(
            [item["path"] for item in cleaned["details"]["members"]],
            list(reversed(expected)),
        )
        for root in (self.box.root, first, grandchild, second):
            self.assertFalse((root / "AGENTS.md").exists())
            self.assertFalse((root / ".pipebuilder/lock.json").exists())
            self.assertTrue((root / "pipespace.json").is_file())
        self.assertFalse((self.box.root / ".pipebuilder/tree-lock.json").exists())
        self.assert_operation_locks_absent()

    def test_scan_depth_bounds_discovery_and_zero_forces_single_space(self):
        for depth, expected in (
            (0, None),
            (1, None),
            (2, [".", "level-1/child-01"]),
            (3, [".", "level-1/child-01", "level-1/child-01/grandchild"]),
        ):
            self.reset(scan_depth=depth)
            child = self.add_child("level-1/child-01", "child-01")
            grandchild = self.add_child(
                "level-1/child-01/grandchild",
                "grandchild",
            )
            result = self.expect_ok(self.box.builder("build"))
            with self.subTest(depth=depth):
                if expected is None:
                    self.assertNotIn("members", result["summary"])
                    self.assertFalse((child / "AGENTS.md").exists())
                    self.assertFalse((grandchild / "AGENTS.md").exists())
                else:
                    receipt = json.loads(
                        (self.box.root / ".pipebuilder/tree-lock.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertEqual(
                        [item["path"] for item in receipt["members"]],
                        expected,
                    )

    def test_verify_is_available_for_a_single_space(self):
        self.reset(scan_depth=0)
        self.expect_ok(self.box.builder("build"))
        verified = self.expect_ok(self.box.builder("verify"))
        self.assertEqual(verified["summary"], {"members": 1, "verified": 1})
        self.assertEqual(verified["details"]["members"][0]["path"], ".")

    def test_hidden_generated_and_symlinked_directories_are_not_scanned(self):
        hidden = self.add_child(".hidden/child", "hidden-child")
        generated = self.add_child(".cursor/child", "generated-child")
        dependency = self.add_child("node_modules/child", "dependency-child")
        outside = self.box.base / "outside"
        outside.mkdir()
        self.box.write_json(
            "pipespace.json",
            {
                "schema": "pipespace.v1",
                "name": "linked-child",
                "agents": ["codex"],
                "skills": [],
                "tags": [],
                "skillProviders": [],
            },
            base=outside,
        )
        self.box.write_json(
            "linked-child.code-workspace",
            {"folders": [{"path": "."}]},
            base=outside,
        )
        link = self.box.root / "linked-child"
        try_symlink(outside, link, target_is_directory=True)

        result = self.expect_ok(self.box.builder("build"))
        self.assertNotIn("members", result["summary"])
        self.assertFalse((hidden / "AGENTS.md").exists())
        self.assertFalse((generated / "AGENTS.md").exists())
        self.assertFalse((dependency / "AGENTS.md").exists())
        self.assertFalse((outside / "AGENTS.md").exists())

    def test_children_schema_is_strict_and_legacy_manifest_is_rejected(self):
        invalid_values = (
            [],
            {},
            {"scanDepth": True},
            {"scanDepth": -1},
            {"scanDepth": 33},
            {"scanDepth": 1, "paths": []},
        )
        for value in invalid_values:
            self.reset()
            manifest = json.loads(
                (self.box.root / "pipespace.json").read_text(encoding="utf-8")
            )
            manifest["children"] = value
            self.box.write_json("pipespace.json", manifest)
            with self.subTest(value=value):
                self.expect_code(self.box.builder("check"), "PB001")

        self.reset()
        self.box.write_json(
            "pipespace-tree.json",
            {"schema": "pipespace-tree.v1", "children": []},
        )
        self.expect_code(self.box.builder("check"), "PB015")

    def test_membership_change_is_verified_then_rebuilt_without_extra_command(self):
        self.add_child("children/child-01", "child-01")
        self.expect_ok(self.box.builder("build"))
        second = self.add_child("children/child-02", "child-02")
        self.expect_code(self.box.builder("verify"), "PB017")
        rebuilt = self.expect_ok(self.box.builder("build"))
        self.assertEqual(rebuilt["summary"]["members"], 3)
        self.assertTrue((second / "AGENTS.md").is_file())
        self.expect_ok(self.box.builder("verify"))

    def test_root_post_cannot_stale_a_child_plan(self):
        child = self.add_child("children/child-01", "child-01")
        provider = self.box.root / "root-provider"
        provider.mkdir()
        self.box.write_text(
            "root-provider/mutate.py",
            "from pathlib import Path\n"
            "root = Path(__file__).resolve().parent.parent\n"
            "path = root / 'children/child-01/child-01.code-workspace'\n"
            "path.write_text(path.read_text(encoding='utf-8') + ' \\n', encoding='utf-8')\n",
        )
        self.box.manifest(
            name="root-space",
            agents=["codex"],
            providers=[
                {
                    "type": "folder",
                    "path": "root-provider",
                    "command": {"cwd": ".", "args": [sys.executable, "mutate.py"]},
                }
            ],
        )

        self.expect_code(self.box.builder("build"), "PB017")
        self.assertTrue((self.box.root / ".pipebuilder/lock.json").is_file())
        self.assertFalse((child / ".pipebuilder/lock.json").exists())
        journal = json.loads(
            (self.box.root / ".pipebuilder/tree-journal.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            [item["stage"] for item in journal["members"]],
            ["post-succeeded", "stale-plan"],
        )
        self.assertFalse((self.box.root / ".pipebuilder/tree-lock.json").exists())
        self.assert_operation_locks_absent()

    def test_post_failure_records_partial_journal_and_rerun_converges(self):
        child = self.add_child(
            "children/child-01",
            "child-01",
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
        self.box.write_text(
            "children/child-01/provider/fail.py",
            "raise SystemExit(23)\n",
        )

        self.expect_code(self.box.builder("build"), "PB016")
        journal_path = self.box.root / ".pipebuilder/tree-journal.json"
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        self.assertEqual(journal["status"], "partial")
        self.assertEqual(
            [item["stage"] for item in journal["members"]],
            ["post-succeeded", "post-failed"],
        )

        manifest = json.loads((child / "pipespace.json").read_text(encoding="utf-8"))
        manifest["skillProviders"] = []
        self.box.write_json("children/child-01/pipespace.json", manifest)
        self.expect_ok(self.box.builder("build"))
        self.assertFalse(journal_path.exists())
        self.expect_ok(self.box.builder("verify"))

    def test_clean_preflights_every_member_before_deleting(self):
        first = self.add_child("children/child-01", "child-01")
        second = self.add_child("children/child-02", "child-02")
        self.expect_ok(self.box.builder("build"))
        drifted = first / "AGENTS.md"
        drifted.unlink()
        drifted.mkdir()
        before = snapshot_tree(self.box.root)

        self.expect_code(self.box.builder("clean"), "PB010")
        self.assertEqual(snapshot_tree(self.box.root), before)
        self.assertTrue((self.box.root / "AGENTS.md").is_file())
        self.assertTrue((second / "AGENTS.md").is_file())
        self.assert_operation_locks_absent()
