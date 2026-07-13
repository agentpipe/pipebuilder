from __future__ import annotations

import json
import os

from support import HarnessBuilderE2ECase, snapshot_tree
from support.model import CaseMetadata


class ProviderResolutionCases(HarnessBuilderE2ECase):
    metadata = CaseMetadata(
        tier="offline",
        requirements=("PROVIDERS", "SELECTION", "HB005", "HB007", "HB008", "HBW001"),
        tags=("providers", "selection", "shadowing"),
    )

    def test_zero_provider_and_zero_skill_is_valid(self):
        self.box.manifest(agents=["codex"])
        payload = self.expect_ok(self.box.builder("build"))
        self.assertEqual(payload["summary"]["skills"], 0)
        self.assertFalse((self.box.root / ".agents").exists())

    def test_missing_provider_and_missing_explicit_skill_have_stable_codes(self):
        self.box.manifest(agents=["codex"], providers=[{"type": "folder", "path": "missing"}])
        self.expect_code(self.box.builder("check"), "HB005")
        (self.box.root / "provider").mkdir()
        self.box.manifest(agents=["codex"], skills=["missing"], providers=[{"type": "folder", "path": "provider"}])
        self.expect_code(self.box.builder("check"), "HB007")

    def test_local_explicit_and_tag_selection_form_a_stable_union(self):
        self.box.skill(".harness-builder/skills", "local")
        self.box.skill("provider-a", "explicit")
        self.box.skill("provider-a", "tagged", tags=["team", "extra"])
        self.box.skill("provider-a", "unselected", tags=["other"])
        self.box.manifest(
            agents=["codex", "cursor"],
            skills=["explicit"],
            tags=["team"],
            providers=[{"type": "folder", "path": "provider-a"}],
        )
        payload = self.expect_ok(self.box.builder("explain"))
        selected = {item["name"]: item["selectedBy"] for item in payload["details"]["skills"]}
        self.assertEqual(selected, {"explicit": "skills", "local": "space-local", "tagged": "tags"})
        self.expect_ok(self.box.builder("build"))
        for name in selected:
            self.assertTrue((self.box.root / f".agents/skills/{name}/SKILL.md").is_file())
            self.assertTrue((self.box.root / f".cursor/skills/{name}/SKILL.md").is_file())
        self.assertFalse((self.box.root / ".agents/skills/unselected").exists())

    def test_local_and_earlier_provider_shadow_later_candidates_with_provenance(self):
        self.box.skill(".harness-builder/skills", "shadow", body="local\n")
        self.box.skill("provider-a", "shadow", body="first\n")
        self.box.skill("provider-b", "shadow", body="second\n")
        self.box.manifest(
            agents=["codex"],
            providers=[{"type": "folder", "path": "provider-a"}, {"type": "folder", "path": "provider-b"}],
        )
        payload = self.expect_ok(self.box.builder("explain"))
        self.assertIn("HBW001", [item["code"] for item in payload["diagnostics"]])
        skill = payload["details"]["skills"][0]
        self.assertEqual(skill["provider"], "space-local")
        self.assertEqual(len(skill["shadowedCandidates"]), 2)

    def test_provider_order_changes_winner_deterministically(self):
        self.box.skill("provider-a", "same", body="A\n")
        self.box.skill("provider-b", "same", body="B\n")
        for order, expected in ((["provider-a", "provider-b"], "A"), (["provider-b", "provider-a"], "B")):
            self.box.manifest(agents=["codex"], skills=["same"], providers=[{"type": "folder", "path": item} for item in order])
            self.expect_ok(self.box.builder("build"))
            content = (self.box.root / ".agents/skills/same/SKILL.md").read_text(encoding="utf-8")
            with self.subTest(order=order):
                self.assertIn("\n" + expected + "\n", content)


class SkillPackageCases(HarnessBuilderE2ECase):
    metadata = CaseMetadata(tier="offline", requirements=("SKILL-PACKAGE", "HB008"), tags=("skill", "copy", "validation"))

    def test_binary_hidden_executable_and_unknown_frontmatter_are_preserved(self):
        self.box.skill("provider", "portable")
        self.box.write_bytes("provider/portable/assets/payload.bin", b"\x00\xfffixture")
        self.box.write_text("provider/portable/scripts/run.py", "print('ok')\n", executable=True)
        self.box.write_text("provider/portable/.metadata", "keep\n")
        self.box.write_text("provider/portable/.DS_Store", "drop\n")
        source_before = snapshot_tree(self.box.root / "provider")
        self.box.manifest(agents=["codex"], skills=["portable"], providers=[{"type": "folder", "path": "provider"}])
        self.expect_ok(self.box.builder("build"))
        target = self.box.root / ".agents/skills/portable"
        self.assertEqual((target / "assets/payload.bin").read_bytes(), b"\x00\xfffixture")
        self.assertTrue(os.access(target / "scripts/run.py", os.X_OK))
        self.assertTrue((target / ".metadata").is_file())
        self.assertFalse((target / ".DS_Store").exists())
        self.assertEqual(snapshot_tree(self.box.root / "provider"), source_before)

    def test_harness_agents_never_leak_into_common_package(self):
        self.box.skill("provider", "native")
        self.box.write_text("provider/native/.harness-agents/codex/AGENTS.md", "native only\n")
        self.box.manifest(agents=["codex"], skills=["native"], providers=[{"type": "folder", "path": "provider"}])
        self.expect_ok(self.box.builder("build"))
        self.assertFalse((self.box.root / ".agents/skills/native/.harness-agents").exists())
        self.assertIn("native only", (self.box.root / "AGENTS.md").read_text(encoding="utf-8"))

    def test_invalid_skill_documents_cover_frontmatter_name_description_and_tags(self):
        invalid = {
            "missing-frontmatter": "body\n",
            "unclosed": "---\nname: unclosed\n",
            "bad-name": "---\nname: Bad\ndescription: x\n---\n",
            "name-mismatch": "---\nname: other\ndescription: x\n---\n",
            "empty-description": "---\nname: empty-description\ndescription:\n---\n",
            "duplicate-tags": "---\nname: duplicate-tags\ndescription: x\ntags:\n  - x\n  - x\n---\n",
            "nested": "---\nname: nested\ndescription: x\nmetadata:\n  key: value\n---\n",
        }
        for directory, content in invalid.items():
            self.box.close(); self.box = __import__("support").Sandbox()
            self.box.write_text(f"provider/{directory}/SKILL.md", content)
            self.box.manifest(agents=["codex"], providers=[{"type": "folder", "path": "provider"}])
            with self.subTest(directory=directory):
                self.expect_code(self.box.builder("check"), "HB008")

    def test_skill_source_symlink_is_rejected_without_following_it(self):
        self.box.skill("provider", "linked")
        outside = self.box.base / "outside-secret.txt"
        outside.write_text("outside\n", encoding="utf-8")
        os.symlink(outside, self.box.root / "provider/linked/link.txt")
        self.box.manifest(agents=["codex"], skills=["linked"], providers=[{"type": "folder", "path": "provider"}])
        self.expect_code(self.box.builder("check"), "HB011")
        self.assertEqual(outside.read_text(encoding="utf-8"), "outside\n")
