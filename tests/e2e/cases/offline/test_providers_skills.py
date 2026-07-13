from __future__ import annotations

import json
import os
import sys
from pathlib import Path

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

    def test_folder_provider_symlink_root_and_content_digest_changes_are_tracked(self):
        external = self.box.base / "external-provider"
        self.box.write_text(
            "linked/SKILL.md",
            "---\nname: linked\ndescription: Linked folder Skill.\n---\n\nfirst\n",
            base=external,
        )
        os.symlink(external, self.box.root / "provider-link")
        self.box.manifest(
            agents=["codex"],
            skills=["linked"],
            providers=[{"type": "folder", "path": "provider-link"}],
        )
        self.expect_ok(self.box.builder("build"))
        first = json.loads((self.box.root / ".harness-builder/lock.json").read_text(encoding="utf-8"))["providers"][1]
        self.assertEqual(first["path"], "provider-link")
        self.assertNotEqual(first["resolvedPath"], "provider-link")
        self.box.write_text(
            "linked/SKILL.md",
            "---\nname: linked\ndescription: Linked folder Skill.\n---\n\nsecond\n",
            base=external,
        )
        self.expect_ok(self.box.builder("build"))
        second = json.loads((self.box.root / ".harness-builder/lock.json").read_text(encoding="utf-8"))["providers"][1]
        self.assertNotEqual(first["digest"], second["digest"])
        self.assertIn("second", (self.box.root / ".agents/skills/linked/SKILL.md").read_text(encoding="utf-8"))

    def test_folder_provider_root_must_be_a_directory(self):
        self.box.write_text("provider-file", "not a directory\n")
        self.box.manifest(agents=["codex"], providers=[{"type": "folder", "path": "provider-file"}])
        self.expect_code(self.box.builder("check"), "HB005")

    def test_folder_provider_aliases_to_the_same_realpath_are_rejected(self):
        external = self.box.base / "shared-provider"
        external.mkdir()
        os.symlink(external, self.box.root / "alias-a")
        os.symlink(external, self.box.root / "alias-b")
        self.box.manifest(
            agents=["codex"],
            providers=[{"type": "folder", "path": "alias-a"}, {"type": "folder", "path": "alias-b"}],
        )
        self.expect_code(self.box.builder("check"), "HB001")

    def test_folder_provider_path_with_unicode_spaces_and_shell_metacharacters_is_literal(self):
        provider = "skills ü # $'"
        self.box.skill(provider, "literal-path", body="literal\n")
        self.box.manifest(
            agents=["codex"],
            skills=["literal-path"],
            providers=[{"type": "folder", "path": provider}],
        )
        self.expect_ok(self.box.builder("build"))
        self.assertIn("literal", (self.box.root / ".agents/skills/literal-path/SKILL.md").read_text(encoding="utf-8"))

    def test_folder_subdir_is_scanned_and_post_command_runs_only_for_build(self):
        source = self.box.base / "component"
        self.box.write_text(
            "skills/commanded/SKILL.md",
            "---\nname: commanded\ndescription: Commanded Skill.\n---\n",
            base=source,
        )
        self.box.write_text(
            "post.py",
            "import pathlib,sys\npathlib.Path(sys.argv[1], 'post-command.txt').write_text('ran\\n', encoding='utf-8')\n",
            base=source,
        )
        provider = {
            "type": "folder",
            "path": "../component",
            "subdir": "skills",
            "command": {"cwd": ".", "args": [sys.executable, "post.py", "{spaceRoot}"]},
        }
        self.box.manifest(agents=["codex"], skills=["commanded"], providers=[provider])
        explain = self.expect_ok(self.box.builder("explain"))
        self.assertEqual(explain["summary"]["postCommands"], 1)
        self.assertFalse((self.box.root / "post-command.txt").exists())
        self.expect_ok(self.box.builder("build", "--dry-run"))
        self.assertFalse((self.box.root / "post-command.txt").exists())
        built = self.expect_ok(self.box.builder("build"))
        self.assertEqual(built["summary"]["postCommands"], 1)
        self.assertEqual((self.box.root / "post-command.txt").read_text(encoding="utf-8"), "ran\n")
        self.assertTrue((self.box.root / ".agents/skills/commanded/SKILL.md").is_file())


class GitProviderCases(HarnessBuilderE2ECase):
    metadata = CaseMetadata(
        tier="offline",
        requirements=("GIT-PROVIDER", "GIT-CACHE", "LOCK", "HB005", "HB011"),
        tags=("providers", "git", "branch", "tag", "offline"),
    )

    def setUp(self) -> None:
        super().setUp()
        self.repo = self.box.base / "repos" / "catalog"
        self.repo.mkdir(parents=True)
        self.cache = self.box.base / "provider-cache"
        self.provider_env = {"HARNESSBUILDER_CACHE_DIR": str(self.cache)}
        self.git("init")
        self.git("symbolic-ref", "HEAD", "refs/heads/main")

    def git(self, *arguments: str):
        result = self.box.run_command(
            ["git", "-C", str(self.repo), *arguments],
            env={
                "GIT_AUTHOR_NAME": "HarnessBuilder E2E",
                "GIT_AUTHOR_EMAIL": "e2e@example.invalid",
                "GIT_COMMITTER_NAME": "HarnessBuilder E2E",
                "GIT_COMMITTER_EMAIL": "e2e@example.invalid",
            },
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout.strip()

    def commit_skill(self, name: str, body: str, *, prefix: str = "skills") -> str:
        self.box.write_text(
            f"{prefix}/{name}/SKILL.md",
            f"---\nname: {name}\ndescription: Git fixture {name}.\n---\n\n{body}\n",
            base=self.repo,
        )
        self.git("add", ".")
        self.git("commit", "-m", f"update {name} {body}")
        return self.git("rev-parse", "HEAD")

    def git_provider(self, **selector: str) -> dict[str, str]:
        return {"type": "git", "url": "../repos/catalog", "subdir": "skills", **selector}

    def lock_git_provider(self) -> dict[str, object]:
        lock = json.loads((self.box.root / ".harness-builder/lock.json").read_text(encoding="utf-8"))
        return next(item for item in lock["providers"] if item["type"] == "git")

    def test_branch_resolves_to_commit_and_builds_from_external_immutable_cache(self):
        commit = self.commit_skill("from-git", "branch-one")
        self.box.manifest(
            agents=["codex", "cursor"],
            skills=["from-git"],
            providers=[self.git_provider(branch="main")],
        )
        self.expect_ok(self.box.builder("build", env=self.provider_env))
        provider = self.lock_git_provider()
        self.assertEqual(provider["url"], "../repos/catalog")
        self.assertEqual(provider["branch"], "main")
        self.assertEqual(provider["commit"], commit)
        self.assertEqual(provider["subdir"], "skills")
        self.assertEqual(provider["snapshot"], provider["digest"])
        self.assertTrue(str(provider["resolvedPath"]).startswith("cache://git/"))
        self.assertNotIn(str(self.box.base), json.dumps(provider))
        self.assertIn("branch-one", (self.box.root / ".agents/skills/from-git/SKILL.md").read_text(encoding="utf-8"))
        self.assertFalse(any(path.name == ".git" for path in self.box.root.rglob(".git")))

    def test_branch_advances_online_but_offline_reuses_locked_commit(self):
        first_commit = self.commit_skill("moving", "first")
        self.box.manifest(agents=["codex"], skills=["moving"], providers=[self.git_provider(branch="main")])
        self.expect_ok(self.box.builder("build", env=self.provider_env))
        second_commit = self.commit_skill("moving", "second")
        unavailable = self.repo.with_name("catalog-unavailable")
        self.repo.rename(unavailable)
        self.expect_ok(self.box.builder("build", "--offline", env=self.provider_env))
        self.assertEqual(self.lock_git_provider()["commit"], first_commit)
        self.assertIn("first", (self.box.root / ".agents/skills/moving/SKILL.md").read_text(encoding="utf-8"))
        unavailable.rename(self.repo)
        self.expect_ok(self.box.builder("build", env=self.provider_env))
        self.assertEqual(self.lock_git_provider()["commit"], second_commit)
        self.assertIn("second", (self.box.root / ".agents/skills/moving/SKILL.md").read_text(encoding="utf-8"))

    def test_tag_remains_pinned_after_branch_advances(self):
        tagged_commit = self.commit_skill("release", "v1-content")
        self.git("tag", "-a", "v1.0.0", "-m", "annotated release")
        self.commit_skill("release", "main-content")
        self.box.manifest(agents=["codex"], skills=["release"], providers=[self.git_provider(tag="v1.0.0")])
        self.expect_ok(self.box.builder("build", env=self.provider_env))
        provider = self.lock_git_provider()
        self.assertEqual(provider["tag"], "v1.0.0")
        self.assertEqual(provider["commit"], tagged_commit)
        self.assertIn("v1-content", (self.box.root / ".agents/skills/release/SKILL.md").read_text(encoding="utf-8"))

    def test_offline_rejects_a_tampered_locked_snapshot(self):
        self.commit_skill("cached", "original")
        self.box.manifest(agents=["codex"], skills=["cached"], providers=[self.git_provider(branch="main")])
        self.expect_ok(self.box.builder("build", env=self.provider_env))
        cached_skill = next(self.cache.rglob("cached/SKILL.md"))
        cached_skill.write_text("tampered\n", encoding="utf-8")
        self.expect_code(self.box.builder("check", "--offline", env=self.provider_env), "HB010")

    def test_offline_requires_a_matching_lock_even_when_the_url_cache_is_warm(self):
        self.commit_skill("cached", "original")
        self.box.manifest(agents=["codex"], skills=["cached"], providers=[self.git_provider(branch="main")])
        self.expect_ok(self.box.builder("build", env=self.provider_env))
        (self.box.root / ".harness-builder/lock.json").unlink()
        self.expect_code(self.box.builder("check", "--offline", env=self.provider_env), "HB005")

    def test_missing_cache_branch_and_subdir_are_structured_provider_errors(self):
        self.commit_skill("available", "ok")
        cases = (
            (self.git_provider(branch="missing"), (), "HB005"),
            ({**self.git_provider(branch="main"), "subdir": "absent"}, (), "HB005"),
            (self.git_provider(branch="main"), ("--offline",), "HB005"),
        )
        for provider, arguments, code in cases:
            self.box.close(); self.box = __import__("support").Sandbox()
            self.repo = self.box.base / "repos" / "catalog"
            self.repo.mkdir(parents=True)
            self.cache = self.box.base / "provider-cache"
            self.provider_env = {"HARNESSBUILDER_CACHE_DIR": str(self.cache)}
            self.git("init"); self.git("symbolic-ref", "HEAD", "refs/heads/main"); self.commit_skill("available", "ok")
            self.box.manifest(agents=["codex"], providers=[provider])
            with self.subTest(provider=provider, arguments=arguments):
                self.expect_code(self.box.builder("check", *arguments, env=self.provider_env), code)

    def test_git_archive_symlinks_are_rejected_before_materialization(self):
        self.commit_skill("unsafe", "body")
        os.symlink("SKILL.md", self.repo / "skills/unsafe/alias.md")
        self.git("add", ".")
        self.git("commit", "-m", "add unsafe symlink")
        self.box.manifest(agents=["codex"], providers=[self.git_provider(branch="main")])
        self.expect_code(self.box.builder("check", env=self.provider_env), "HB011")

    def test_git_post_command_runs_from_full_commit_while_skills_use_subdir(self):
        self.commit_skill("commanded", "git-command")
        self.box.write_text(
            "post.py",
            "import pathlib,sys\npathlib.Path(sys.argv[1], 'git-post.txt').write_text('git-ran\\n', encoding='utf-8')\n",
            base=self.repo,
        )
        self.git("add", ".")
        self.git("commit", "-m", "add post command")
        provider = self.git_provider(branch="main")
        provider["command"] = {"cwd": ".", "args": [sys.executable, "post.py", "{spaceRoot}"]}
        self.box.manifest(agents=["codex"], skills=["commanded"], providers=[provider])
        self.expect_ok(self.box.builder("build", env=self.provider_env))
        self.assertEqual((self.box.root / "git-post.txt").read_text(encoding="utf-8"), "git-ran\n")

    def test_provider_order_and_space_local_priority_also_apply_to_git(self):
        self.commit_skill("same", "git")
        self.box.skill("folder", "same", body="folder\n")
        self.box.skill(".harness-builder/skills", "same", body="local\n")
        self.box.manifest(
            agents=["codex"],
            skills=["same"],
            providers=[self.git_provider(branch="main"), {"type": "folder", "path": "folder"}],
        )
        payload = self.expect_ok(self.box.builder("explain", env=self.provider_env))
        skill = payload["details"]["skills"][0]
        self.assertEqual(skill["provider"], "space-local")
        self.assertEqual(len(skill["shadowedCandidates"]), 2)


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
        }
        for directory, content in invalid.items():
            self.box.close(); self.box = __import__("support").Sandbox()
            self.box.write_text(f"provider/{directory}/SKILL.md", content)
            self.box.manifest(agents=["codex"], providers=[{"type": "folder", "path": "provider"}])
            with self.subTest(directory=directory):
                self.expect_code(self.box.builder("check"), "HB008")

    def test_yaml_block_scalars_and_unknown_nested_frontmatter_are_valid_and_preserved(self):
        content = """---
name: rich-frontmatter
description: >-
  A portable Skill with a folded
  multiline description.
tags:
  - migration
metadata:
  owner: harness-team
  nested:
    maturity: stable
trigger_condition: |
  Use when a legacy THarness Skill is migrated.
---

Fixture body.
"""
        self.box.write_text("provider/rich-frontmatter/SKILL.md", content)
        self.box.manifest(
            agents=["codex", "cursor"],
            skills=["rich-frontmatter"],
            providers=[{"type": "folder", "path": "provider"}],
        )
        self.expect_ok(self.box.builder("build"))
        for target in (".agents/skills/rich-frontmatter/SKILL.md", ".cursor/skills/rich-frontmatter/SKILL.md"):
            self.assertEqual((self.box.root / target).read_text(encoding="utf-8"), content)

    def test_utf8_bom_crlf_and_deep_skill_tree_are_preserved(self):
        skill = "---\r\nname: portable-text\r\ndescription: Portable text fixture.\r\n---\r\n\r\nBody.\r\n"
        self.box.write_bytes("provider/portable-text/SKILL.md", b"\xef\xbb\xbf" + skill.encode("utf-8"))
        deep = "provider/portable-text/" + "/".join(f"level-{index:02d}" for index in range(24)) + "/leaf.txt"
        self.box.write_text(deep, "deep\r\n")
        self.box.manifest(
            agents=["codex"],
            skills=["portable-text"],
            providers=[{"type": "folder", "path": "provider"}],
        )
        self.expect_ok(self.box.builder("build"))
        self.assertEqual(
            (self.box.root / ".agents/skills/portable-text/SKILL.md").read_bytes(),
            b"\xef\xbb\xbf" + skill.encode("utf-8"),
        )
        self.assertEqual((self.box.root / ".agents/skills/portable-text" / Path(deep).relative_to("provider/portable-text")).read_bytes(), b"deep\r\n")

    def test_every_provider_child_directory_must_be_a_skill_package(self):
        self.box.write_text("provider/not-a-skill/README.md", "missing SKILL.md\n")
        self.box.manifest(agents=["codex"], providers=[{"type": "folder", "path": "provider"}])
        self.expect_code(self.box.builder("check"), "HB008")

    def test_unknown_skill_agent_namespace_is_rejected_even_when_empty(self):
        self.box.skill("provider", "unknown-agent")
        (self.box.root / "provider/unknown-agent/.harness-agents/not-an-agent").mkdir(parents=True)
        self.box.manifest(
            agents=["codex"],
            skills=["unknown-agent"],
            providers=[{"type": "folder", "path": "provider"}],
        )
        self.expect_code(self.box.builder("check"), "HB009")

    def test_provider_symlink_loop_is_a_structured_unsafe_path_error(self):
        os.symlink("loop", self.box.root / "loop")
        self.box.manifest(agents=["codex"], providers=[{"type": "folder", "path": "loop"}])
        self.expect_code(self.box.builder("check"), "HB011")

    def test_skill_source_symlink_is_rejected_without_following_it(self):
        self.box.skill("provider", "linked")
        outside = self.box.base / "outside-secret.txt"
        outside.write_text("outside\n", encoding="utf-8")
        os.symlink(outside, self.box.root / "provider/linked/link.txt")
        self.box.manifest(agents=["codex"], skills=["linked"], providers=[{"type": "folder", "path": "provider"}])
        self.expect_code(self.box.builder("check"), "HB011")
        self.assertEqual(outside.read_text(encoding="utf-8"), "outside\n")
