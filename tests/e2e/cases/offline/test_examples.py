from __future__ import annotations

import json
import sys
from pathlib import Path

from support import PipeBuilderE2ECase
from support.model import CaseMetadata
from support.sandbox import PIPEBUILDER, snapshot_tree


class PublicExampleCases(PipeBuilderE2ECase):
    metadata = CaseMetadata(
        tier="offline",
        requirements=("EXAMPLES", "BUILD", "WORKSPACE", "PROVIDERS", "ADAPTERS"),
        tags=("examples", "multi-pipeline", "smoke"),
        agents=("codex", "cursor"),
    )

    def test_multi_pipeline_example_builds_distinct_pipelines_for_one_unchanged_project(self):
        example = self.box.copy_example("multi-pipeline-project")
        project = example / "project"
        project_before = snapshot_tree(project)
        expected = {
            "feature-development": ("feature-implementation", "feature-development.mdc"),
            "bugfix-review": ("bugfix-review", "bugfix-review.mdc"),
        }

        for space_name, (skill_name, rule_name) in expected.items():
            with self.subTest(space=space_name):
                space = example / "pipespaces" / space_name
                result = self.box.run_command(
                    [sys.executable, str(PIPEBUILDER), "build", str(space), "--format", "json"],
                    cwd=example,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                payload = result.json()
                self.assertEqual(payload["schema"], "pipebuilder-report.v1")
                self.assertEqual(payload["status"], "ok")
                self.assertEqual(payload["pipespace"], space_name)
                self.assertFalse((space / ".pipebuilder/build.lock").exists())

                lock = json.loads((space / ".pipebuilder/lock.json").read_text(encoding="utf-8"))
                self.assertEqual([item["name"] for item in lock["skills"]], [skill_name])
                self.assertTrue((space / f".agents/skills/{skill_name}/SKILL.md").is_file())
                self.assertTrue((space / f".cursor/skills/{skill_name}/SKILL.md").is_file())
                self.assertTrue((space / f".cursor/rules/{rule_name}").is_file())

                other_skills = {item[0] for item in expected.values()} - {skill_name}
                other_rules = {item[1] for item in expected.values()} - {rule_name}
                for other_skill in other_skills:
                    self.assertFalse((space / f".agents/skills/{other_skill}").exists())
                    self.assertFalse((space / f".cursor/skills/{other_skill}").exists())
                for other_rule in other_rules:
                    self.assertFalse((space / f".cursor/rules/{other_rule}").exists())

                workspace = json.loads((space / f"{space_name}.code-workspace").read_text(encoding="utf-8"))
                project_folders = [item for item in workspace["folders"] if item["name"] == "project"]
                self.assertEqual(len(project_folders), 1)
                referenced_project = (space / Path(project_folders[0]["path"])).resolve()
                self.assertEqual(referenced_project, project.resolve())

        self.assertEqual(snapshot_tree(project), project_before)
