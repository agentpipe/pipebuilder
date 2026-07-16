from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

from support import PipeBuilderE2ECase
from support.model import CaseMetadata
from support.sandbox import REPO_ROOT


SKILL_MEMBERS = (
    "pipebuilder/SKILL.md",
    "pipebuilder/pipebuilder.py",
    "pipebuilder/scripts/update.py",
)
PACKAGER = REPO_ROOT / "scripts/package_skill.py"


class SkillReleaseCases(PipeBuilderE2ECase):
    metadata = CaseMetadata(
        tier="offline",
        requirements=("SKILL", "RELEASE", "UPDATE"),
        tags=("skill", "release-zip", "updater"),
    )

    def package(self, name: str = "pipebuilder-skill.zip") -> Path:
        output = self.box.base / "release" / name
        result = self.box.run_command(
            [sys.executable, str(PACKAGER), "--output", str(output)],
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return output

    def install_skill(self) -> Path:
        root = self.box.base / "installed" / "pipebuilder"
        (root / "scripts").mkdir(parents=True)
        for relative in ("SKILL.md", "pipebuilder.py", "scripts/update.py"):
            shutil.copy2(REPO_ROOT / relative, root / relative)
        return root

    def test_root_skill_and_readmes_publish_latest_release_installation(self):
        skill = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(skill.startswith("---\n"))
        self.assertIn("\nname: pipebuilder\n", skill)
        self.assertIn("\ndescription:", skill)
        self.assertLess(len(skill.splitlines()), 500)
        for name in ("README.md", "README.zh-CN.md"):
            content = (REPO_ROOT / name).read_text(encoding="utf-8")
            self.assertIn(
                "https://github.com/aikenc/pipebuilder/releases/latest/download/pipebuilder-skill.zip",
                content,
            )
            self.assertNotIn("raw.githubusercontent.com/aikenc/pipebuilder/main/SKILL.md", content)
            self.assertIn("pipespaces/shared/skills", content)
            self.assertIn("--project ../..", content)
            self.assertIn("--shared-skills ../shared/skills", content)
        updater = (REPO_ROOT / "scripts/update.py").read_text(encoding="utf-8")
        self.assertIn("latest/download", updater)
        workflow = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        for artifact in (
            "dist/pipebuilder.py",
            "dist/pipebuilder.py.sha256",
            "dist/pipebuilder-skill.zip",
        ):
            self.assertIn(artifact, workflow)

    def test_release_zip_has_only_the_specified_skill_directory_and_is_stable(self):
        first = self.package("first.zip")
        second = self.package("second.zip")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with zipfile.ZipFile(str(first), "r") as archive:
            self.assertEqual(tuple(archive.namelist()), SKILL_MEMBERS)
            extract_root = self.box.base / "extracted"
            archive.extractall(str(extract_root))
        extracted = extract_root / "pipebuilder"
        self.box.manifest(
            agents=["codex"],
            skills=["pipebuilder"],
            providers=[{"type": "folder", "path": "../extracted"}],
        )
        self.expect_ok(self.box.builder("check"))
        version = self.box.run_command(
            [sys.executable, str(extracted / "pipebuilder.py"), "--version"],
            cwd=extracted,
        )
        self.assertEqual(version.returncode, 0, version.stdout + version.stderr)
        self.assertEqual(version.stdout.strip(), "PipeBuilder 0.1.2")

    def test_updater_replaces_all_three_files_from_release_zip(self):
        archive = self.package()
        installed = self.install_skill()
        (installed / "SKILL.md").write_text("outdated\n", encoding="utf-8")
        (installed / "pipebuilder.py").write_text("outdated\n", encoding="utf-8")

        result = self.box.run_command(
            [
                sys.executable,
                str(installed / "scripts/update.py"),
                "--archive-url",
                archive.as_uri(),
            ],
            cwd=installed,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["changed"])
        self.assertEqual(payload["files"], ["SKILL.md", "pipebuilder.py", "scripts/update.py"])
        for relative in ("SKILL.md", "pipebuilder.py", "scripts/update.py"):
            self.assertEqual((installed / relative).read_bytes(), (REPO_ROOT / relative).read_bytes())

    def test_updater_dry_run_and_bad_zip_leave_installation_unchanged(self):
        archive = self.package()
        installed = self.install_skill()
        before = {
            relative: (installed / relative).read_bytes()
            for relative in ("SKILL.md", "pipebuilder.py", "scripts/update.py")
        }
        bad_archive = archive.with_name("bad.zip")
        bad_archive.write_bytes(b"not a ZIP")
        failed = self.box.run_command(
            [
                sys.executable,
                str(installed / "scripts/update.py"),
                "--archive-url",
                bad_archive.as_uri(),
            ],
            cwd=installed,
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("not a valid ZIP", failed.stderr)
        self.assertEqual(
            before,
            {
                relative: (installed / relative).read_bytes()
                for relative in ("SKILL.md", "pipebuilder.py", "scripts/update.py")
            },
        )

        dry_run = self.box.run_command(
            [
                sys.executable,
                str(installed / "scripts/update.py"),
                "--dry-run",
                "--archive-url",
                archive.as_uri(),
            ],
            cwd=installed,
        )
        self.assertEqual(dry_run.returncode, 0, dry_run.stdout + dry_run.stderr)
        self.assertTrue(json.loads(dry_run.stdout)["dryRun"])
