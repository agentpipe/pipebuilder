from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

from support import PipeBuilderE2ECase
from support.model import CaseMetadata
from support.sandbox import REPO_ROOT


PACKAGE_MANIFEST = "pipebuilder/.skill-package.json"
REQUIRED_MEMBERS = {
    "pipebuilder/SKILL.md",
    "pipebuilder/pipebuilder.py",
    "pipebuilder/scripts/update.py",
}
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

    def update(self, installed: Path, archive: Path, *arguments: str):
        return self.box.run_command(
            [
                sys.executable,
                str(installed / "scripts/update.py"),
                *arguments,
                "--archive-url",
                archive.as_uri(),
            ],
            cwd=installed,
        )

    def archive_manifest(self, archive_path: Path) -> dict:
        with zipfile.ZipFile(str(archive_path), "r") as archive:
            return json.loads(archive.read(PACKAGE_MANIFEST).decode("utf-8"))

    def test_root_skill_and_readmes_publish_latest_release_installation(self):
        skill = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(skill.startswith("---\n"))
        self.assertIn("\nname: pipebuilder\n", skill)
        self.assertIn("\ndescription:", skill)
        self.assertLess(len(skill.splitlines()), 500)
        for name in ("README.md", "README.zh-CN.md"):
            content = (REPO_ROOT / name).read_text(encoding="utf-8")
            self.assertIn(
                "https://github.com/agentpipe/pipebuilder/releases/latest/download/pipebuilder-skill.zip",
                content,
            )
            self.assertEqual(
                set(re.findall(r"(?:github\.com|githubusercontent\.com)/([^/\s\"]+)/pipebuilder", content)),
                {"agentpipe"},
            )
            self.assertNotIn("raw.githubusercontent.com/agentpipe/pipebuilder/main/SKILL.md", content)
            self.assertIn("pipespaces/shared/skills", content)
            self.assertIn("--project ../..", content)
            self.assertIn("--shared-skills ../shared/skills", content)
        updater = (REPO_ROOT / "scripts/update.py").read_text(encoding="utf-8")
        self.assertIn('REPOSITORY = "agentpipe/pipebuilder"', updater)
        self.assertIn("latest/download", updater)
        workflow = (REPO_ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
        for artifact in (
            "dist/pipebuilder.py",
            "dist/pipebuilder.py.sha256",
            "dist/pipebuilder-skill.zip",
            "dist/pipebuilder-skill.zip.sha256",
        ):
            self.assertIn(artifact, workflow)

    def test_release_zip_follows_the_skill_directory_manifest_and_is_stable(self):
        first = self.package("first.zip")
        second = self.package("second.zip")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(
            first.with_name(first.name + ".sha256").read_text(encoding="ascii").split()[0],
            hashlib.sha256(first.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            first.with_name(first.name + ".sha256").read_bytes(),
            second.with_name(second.name + ".sha256").read_bytes().replace(b"second.zip", b"first.zip"),
        )
        with zipfile.ZipFile(str(first), "r") as archive:
            names = archive.namelist()
            self.assertEqual(names, sorted(names))
            manifest = json.loads(archive.read(PACKAGE_MANIFEST).decode("utf-8"))
            self.assertEqual(manifest["schema"], "pipebuilder-skill-package.v1")
            expected = {PACKAGE_MANIFEST}
            for entry in manifest["files"]:
                member = f"pipebuilder/{entry['path']}"
                expected.add(member)
                self.assertEqual(
                    entry["sha256"],
                    hashlib.sha256(archive.read(member)).hexdigest(),
                )
            self.assertEqual(set(names), expected)
            self.assertTrue(REQUIRED_MEMBERS.issubset(expected))
            self.assertIn(
                "pipebuilder/.pipe-agents/codebuddy/.codebuddy/settings.json",
                expected,
            )
            self.assertIn(
                "pipebuilder/.pipe-agents/claude-code/.claude/settings.json",
                expected,
            )
            extract_root = self.box.base / "extracted"
            archive.extractall(str(extract_root))

        extracted = extract_root / "pipebuilder"
        self.box.manifest(
            agents=["codebuddy", "claude-code"],
            skills=["pipebuilder"],
            providers=[{"type": "folder", "path": "../extracted"}],
        )
        self.expect_ok(self.box.builder("build"))
        for settings_path in (".codebuddy/settings.json", ".claude/settings.json"):
            settings = json.loads(
                (self.box.root / settings_path).read_text(encoding="utf-8")
            )
            self.assertIn("Edit(/.agents/skills/**)", settings["permissions"]["deny"])
        version = self.box.run_command(
            [sys.executable, str(extracted / "pipebuilder.py"), "--version"],
            cwd=extracted,
        )
        self.assertEqual(version.returncode, 0, version.stdout + version.stderr)
        self.assertEqual(version.stdout.strip(), "PipeBuilder 0.1.3")

    def test_updater_synchronizes_the_manifest_managed_skill_tree(self):
        archive = self.package()
        installed = self.install_skill()
        (installed / "SKILL.md").write_text("outdated\n", encoding="utf-8")
        (installed / "pipebuilder.py").write_text("outdated\n", encoding="utf-8")

        result = self.update(installed, archive)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        expected_files = sorted(
            entry["path"] for entry in self.archive_manifest(archive)["files"]
        )
        self.assertTrue(payload["changed"])
        self.assertEqual(payload["files"], expected_files)
        self.assertTrue((installed / ".skill-package.json").is_file())
        for relative in expected_files:
            self.assertEqual(
                (installed / relative).read_bytes(),
                (REPO_ROOT / relative).read_bytes(),
            )

        obsolete = installed / "assets/obsolete.txt"
        obsolete.parent.mkdir(parents=True)
        obsolete.write_text("obsolete\n", encoding="utf-8")
        installed_manifest = json.loads(
            (installed / ".skill-package.json").read_text(encoding="utf-8")
        )
        installed_manifest["files"].append(
            {
                "path": "assets/obsolete.txt",
                "sha256": hashlib.sha256(obsolete.read_bytes()).hexdigest(),
                "mode": 0o644,
            }
        )
        (installed / ".skill-package.json").write_text(
            json.dumps(installed_manifest), encoding="utf-8"
        )
        cleaned = self.update(installed, archive)
        self.assertEqual(cleaned.returncode, 0, cleaned.stdout + cleaned.stderr)
        self.assertEqual(json.loads(cleaned.stdout)["removed"], ["assets/obsolete.txt"])
        self.assertFalse(obsolete.exists())

        (installed / ".skill-package.json").write_text("{damaged", encoding="utf-8")
        recovered = self.update(installed, archive)
        self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
        self.assertEqual(
            json.loads((installed / ".skill-package.json").read_text(encoding="utf-8"))["schema"],
            "pipebuilder-skill-package.v1",
        )

    def test_updater_dry_run_and_bad_zip_leave_installation_unchanged(self):
        archive = self.package()
        installed = self.install_skill()
        before = {
            relative: (installed / relative).read_bytes()
            for relative in ("SKILL.md", "pipebuilder.py", "scripts/update.py")
        }
        bad_archive = archive.with_name("bad.zip")
        bad_archive.write_bytes(b"not a ZIP")
        bad_archive.with_name(bad_archive.name + ".sha256").write_text(
            f"{hashlib.sha256(bad_archive.read_bytes()).hexdigest()}  {bad_archive.name}\n",
            encoding="ascii",
        )
        failed = self.update(installed, bad_archive)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("not a valid ZIP", failed.stderr)

        checksum = archive.with_name(archive.name + ".sha256")
        valid_checksum = checksum.read_bytes()
        checksum.write_text(f"{'0' * 64}  {archive.name}\n", encoding="ascii")
        mismatch = self.update(installed, archive)
        self.assertNotEqual(mismatch.returncode, 0)
        self.assertIn("SHA-256 mismatch", mismatch.stderr)
        checksum.write_bytes(valid_checksum)

        dry_run = self.update(installed, archive, "--dry-run")
        self.assertEqual(dry_run.returncode, 0, dry_run.stdout + dry_run.stderr)
        self.assertTrue(json.loads(dry_run.stdout)["dryRun"])
        self.assertFalse((installed / ".skill-package.json").exists())
        self.assertEqual(
            before,
            {
                relative: (installed / relative).read_bytes()
                for relative in ("SKILL.md", "pipebuilder.py", "scripts/update.py")
            },
        )

    def test_updater_rejects_manifest_paths_outside_the_skill_convention(self):
        archive = self.package()
        malicious = archive.with_name("malicious.zip")
        with zipfile.ZipFile(str(archive), "r") as source:
            members = {name: source.read(name) for name in source.namelist()}
        manifest = json.loads(members[PACKAGE_MANIFEST].decode("utf-8"))
        escape = b"escape\n"
        manifest["files"].append(
            {
                "path": "../escape.txt",
                "sha256": hashlib.sha256(escape).hexdigest(),
                "mode": 0o644,
            }
        )
        members[PACKAGE_MANIFEST] = json.dumps(manifest).encode("utf-8")
        members["pipebuilder/../escape.txt"] = escape
        with zipfile.ZipFile(str(malicious), "w") as target:
            for name, content in members.items():
                target.writestr(name, content)
        malicious.with_name(malicious.name + ".sha256").write_text(
            f"{hashlib.sha256(malicious.read_bytes()).hexdigest()}  {malicious.name}\n",
            encoding="ascii",
        )
        installed = self.install_skill()
        result = self.update(installed, malicious)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsafe package path", result.stderr)
        self.assertFalse((installed.parent / "escape.txt").exists())
