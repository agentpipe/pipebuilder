from __future__ import annotations

import json
from pathlib import Path

from support import HarnessBuilderE2ECase, snapshot_tree
from support.model import CaseMetadata


class ManifestValidationCases(HarnessBuilderE2ECase):
    metadata = CaseMetadata(
        tier="offline",
        requirements=("MANIFEST", "HB001", "HB002", "HB006"),
        tags=("manifest", "diagnostics", "no-side-effects"),
    )

    def setUp(self) -> None:
        super().setUp()
        self.box.manifest(agents=["codex"])

    def assert_manifest_error(self, value, code: str = "HB001") -> None:
        path = self.box.root / "harness-space.json"
        if isinstance(value, str):
            path.write_text(value, encoding="utf-8")
        else:
            self.box.write_json("harness-space.json", value)
        before = snapshot_tree(self.box.root)
        self.expect_code(self.box.builder("build"), code)
        self.assertEqual(snapshot_tree(self.box.root), before)

    def test_malformed_nonobject_and_missing_required_fields(self):
        valid = json.loads((self.box.root / "harness-space.json").read_text(encoding="utf-8"))
        cases = ["{", [], None]
        for field in ("schema", "name", "agents", "skills", "tags", "skillProviders"):
            item = dict(valid)
            item.pop(field)
            cases.append(item)
        for value in cases:
            with self.subTest(value=value):
                self.assert_manifest_error(value)

    def test_schema_unknown_field_and_description_type(self):
        valid = json.loads((self.box.root / "harness-space.json").read_text(encoding="utf-8"))
        cases = []
        item = dict(valid); item["schema"] = "harness-space.v2"; cases.append(item)
        item = dict(valid); item["command"] = ["rm", "-rf"]; cases.append(item)
        item = dict(valid); item["description"] = 42; cases.append(item)
        for value in cases:
            with self.subTest(value=value):
                self.assert_manifest_error(value)

    def test_space_name_validation_has_dedicated_code(self):
        valid = json.loads((self.box.root / "harness-space.json").read_text(encoding="utf-8"))
        for name in ("", "Upper", "-leading", "under_score", "a/escape", 7):
            item = dict(valid); item["name"] = name
            with self.subTest(name=name):
                self.assert_manifest_error(item, "HB002")

    def test_agent_list_shape_duplicates_and_unknown_values(self):
        valid = json.loads((self.box.root / "harness-space.json").read_text(encoding="utf-8"))
        for agents in (None, [], ["codex", "codex"], ["unknown"], [""], "codex"):
            item = dict(valid); item["agents"] = agents
            with self.subTest(agents=agents):
                self.assert_manifest_error(item)

    def test_skill_and_tag_lists_reject_invalid_names_types_and_duplicates(self):
        valid = json.loads((self.box.root / "harness-space.json").read_text(encoding="utf-8"))
        cases = (
            ("skills", "skill"),
            ("skills", ["Bad"]),
            ("skills", ["same", "same"]),
            ("tags", "tag"),
            ("tags", [""]),
            ("tags", ["same", "same"]),
        )
        for field, value in cases:
            item = dict(valid); item[field] = value
            with self.subTest(field=field, value=value):
                self.assert_manifest_error(item)

    def test_provider_schema_relative_path_uniqueness_and_supported_type(self):
        valid = json.loads((self.box.root / "harness-space.json").read_text(encoding="utf-8"))
        cases = (
            ("not-a-list", "HB001"),
            ([{}], "HB001"),
            ([{"type": "folder", "path": "x", "extra": True}], "HB001"),
            ([{"type": "git", "path": "x"}], "HB001"),
            ([{"type": "registry", "path": "x"}], "HB006"),
            ([{"type": "folder", "path": ""}], "HB001"),
            ([{"type": "folder", "path": str(self.box.root)}], "HB001"),
            ([{"type": "folder", "path": "x", "subdir": "../skills"}], "HB001"),
            ([{"type": "folder", "path": "x", "command": {"args": []}}], "HB001"),
            ([{"type": "folder", "path": "x", "command": {"cwd": "../escape", "args": ["tool"]}}], "HB001"),
            ([{"type": "folder", "path": "x"}, {"type": "folder", "path": "./x"}], "HB001"),
        )
        for providers, code in cases:
            item = dict(valid); item["skillProviders"] = providers
            with self.subTest(providers=providers):
                self.assert_manifest_error(item, code)

    def test_git_provider_requires_url_and_exactly_one_safe_branch_or_tag(self):
        valid = json.loads((self.box.root / "harness-space.json").read_text(encoding="utf-8"))
        cases = (
            ([{"type": "git", "url": "../repo"}], "HB001"),
            ([{"type": "git", "url": "../repo", "branch": "main", "tag": "v1"}], "HB001"),
            ([{"type": "git", "url": "../repo", "ref": "main"}], "HB001"),
            ([{"type": "git", "url": "../repo", "branch": "-main"}], "HB001"),
            ([{"type": "git", "url": "../repo", "branch": "feature//nested"}], "HB001"),
            ([{"type": "git", "url": "../repo", "tag": ".hidden"}], "HB001"),
            ([{"type": "git", "url": "../repo", "tag": "release..one"}], "HB001"),
            ([{"type": "git", "url": "../repo", "branch": "main", "subdir": "../skills"}], "HB001"),
            ([{"type": "git", "url": "https://token@example.test/repo.git", "branch": "main"}], "HB011"),
            ([{"type": "git", "url": "https://example.test/repo.git?token=x", "branch": "main"}], "HB011"),
            (
                [
                    {"type": "git", "url": "../repo", "branch": "main"},
                    {"type": "git", "url": "../repo", "branch": "main", "subdir": "."},
                ],
                "HB001",
            ),
        )
        for providers, code in cases:
            item = dict(valid); item["skillProviders"] = providers
            with self.subTest(providers=providers):
                self.assert_manifest_error(item, code)


class WorkspaceValidationCases(HarnessBuilderE2ECase):
    metadata = CaseMetadata(
        tier="offline",
        requirements=("WORKSPACE", "HB003", "HB004"),
        tags=("workspace", "paths", "multi-folder"),
    )

    def setUp(self) -> None:
        super().setUp()
        self.box.manifest(agents=["codex"])

    def test_workspace_is_required_and_selected_by_manifest_name(self):
        (self.box.root / "fixture-space.code-workspace").unlink()
        self.box.write_json("unrelated.code-workspace", {"folders": [{"name": "x", "path": "."}]})
        self.expect_code(self.box.builder("check"), "HB003")

    def test_workspace_nonobject_malformed_and_invalid_folder_shapes(self):
        path = self.box.root / "fixture-space.code-workspace"
        values = ("{", [], None, {}, {"folders": []}, {"folders": "x"}, {"folders": [None]})
        for value in values:
            self.box.manifest(agents=["codex"])
            if isinstance(value, str):
                path.write_text(value, encoding="utf-8")
            else:
                self.box.write_json("fixture-space.code-workspace", value)
            with self.subTest(value=value):
                self.expect_code(self.box.builder("check"), "HB004")

    def test_folder_name_and_path_validation(self):
        cases = (
            [{"path": "."}],
            [{"name": "", "path": "."}],
            [{"name": "x"}],
            [{"name": "x", "path": ""}],
            [{"name": "x", "path": str(self.box.root)}],
            [{"name": "x", "path": "missing"}],
            [{"name": "x", "path": "."}, {"name": "x", "path": "other"}],
            [{"name": "x", "path": "."}, {"name": "y", "path": "./"}],
        )
        for folders in cases:
            self.box.manifest(agents=["codex"], folders=folders)
            with self.subTest(folders=folders):
                self.expect_code(self.box.builder("check"), "HB004")

    def test_same_directory_external_and_multiple_folders_are_preserved_in_order(self):
        external = self.box.base / "项目 #1 'quoted' $dollar"
        external.mkdir()
        self.box.manifest(
            name="different-name",
            agents=["codex"],
            folders=[
                {"name": "space", "path": "."},
                {"name": "unicode shell", "path": "../" + external.name},
            ],
        )
        payload = self.expect_ok(self.box.builder("explain"))
        self.assertEqual(
            payload["details"]["workspace"]["folders"],
            [{"name": "space", "path": "."}, {"name": "unicode shell", "path": "../" + external.name}],
        )
        self.expect_ok(self.box.builder("build"))
        guidance = (self.box.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertLess(guidance.index("`space`"), guidance.index("`unicode shell`"))
        self.assertIn("same directory as Harness Space", guidance)
        self.assertIn("directory-decoupled", guidance)

    def test_extra_vscode_workspace_fields_are_preserved_and_ignored_by_builder(self):
        workspace = self.box.root / "fixture-space.code-workspace"
        value = json.loads(workspace.read_text(encoding="utf-8"))
        value["settings"] = {"editor.formatOnSave": True}
        value["extensions"] = {"recommendations": ["openai.chatgpt"]}
        self.box.write_json("fixture-space.code-workspace", value)
        before = workspace.read_bytes()
        self.expect_ok(self.box.builder("build"))
        self.assertEqual(workspace.read_bytes(), before)


class LegacyNamespaceCases(HarnessBuilderE2ECase):
    metadata = CaseMetadata(tier="offline", requirements=("HB015",), tags=("legacy", "migration"))

    def test_each_legacy_marker_and_mixed_layout_is_rejected_without_writes(self):
        markers = ("tagents", "private", ".harness-agents", ".harness-space.yaml", ".harness-lock.yaml", "legacy.code-workspace.src")
        for marker in markers:
            self.box.close(); self.box = __import__("support").Sandbox()
            self.box.manifest(agents=["codex"])
            path = self.box.root / marker
            if "." in Path(marker).name and not marker == ".harness-agents":
                path.write_text("legacy\n", encoding="utf-8")
            else:
                path.mkdir()
            before = snapshot_tree(self.box.root)
            with self.subTest(marker=marker):
                self.expect_code(self.box.builder("build"), "HB015")
                self.assertEqual(snapshot_tree(self.box.root), before)
