from __future__ import annotations

import json
import os
from pathlib import Path

from support import PipeBuilderE2ECase, snapshot_tree
from support.model import CaseMetadata


AGENTS_SENTINEL = "HB_AGENTS_7F1C9A2E"
SKILL_SENTINEL = "HB_SKILL_C4D8B613"


class CodexLiveModelCases(PipeBuilderE2ECase):
    metadata = CaseMetadata(
        tier="live",
        requirements=(
            "CODEX-AUTH",
            "REAL-MODEL",
            "AGENTS-CONSUMPTION",
            "SKILL-CONSUMPTION",
            "GIT-PROVIDER-CONSUMPTION",
            "HOOK-EXECUTION",
        ),
        tags=("codex", "live", "model", "sentinel"),
        agents=("codex",),
        parallel_safe=False,
    )

    def setUp(self) -> None:
        super().setUp()
        if os.environ.get("PIPEBUILDER_E2E_LIVE") != "1":
            self.skipTest("live model tests require --tier live or --tier all")
        self.codex = self.require_program("codex")
        version_probe = self.box.run_command([self.codex, "--version"], cwd=self.box.root)
        self.assertEqual(version_probe.returncode, 0, version_probe.stdout + version_probe.stderr)
        requested_model = os.environ.get("PIPEBUILDER_E2E_MODEL")
        self.client_record = {
            "id": "codex",
            "executable": str(Path(self.codex).resolve()),
            "version": version_probe.stdout.strip(),
            "verificationLevel": "live-consumed",
            "model": requested_model or "client-default",
            "modelOverrideSource": "cli" if requested_model else "installed-client",
        }
        git = self.require_program("git")
        self.box.manifest(
            agents=["codex"],
            skills=["hb-live-sentinel"],
            providers=[
                {
                    "type": "git",
                    "url": "../repos/live-skills",
                    "branch": "main",
                    "subdir": "skills",
                }
            ],
        )
        self.box.write_text(
            ".pipebuilder/agents/codex/AGENTS.md",
            "Live probe fact: the project-instruction sentinel is " + AGENTS_SENTINEL + ".\n",
        )
        provider_repo = self.box.base / "repos/live-skills"
        skill_body = (
            "Do not call tools and do not modify files.\n"
            "The Skill sentinel is `" + SKILL_SENTINEL + "`.\n"
            "Read the active project instructions to find the project-instruction sentinel.\n"
            "Return one JSON object with exactly two string properties: `agents` for that project sentinel "
            "and `skill` for this Skill sentinel. Do not add commentary.\n"
        )
        self.box.write_text(
            "skills/hb-live-sentinel/SKILL.md",
            "---\n"
            "name: hb-live-sentinel\n"
            "description: Run the PipeBuilder live sentinel verification when explicitly invoked.\n"
            "---\n\n"
            + skill_body,
            base=provider_repo,
        )
        git_env = {
            "GIT_AUTHOR_NAME": "PipeBuilder E2E",
            "GIT_AUTHOR_EMAIL": "e2e@example.invalid",
            "GIT_COMMITTER_NAME": "PipeBuilder E2E",
            "GIT_COMMITTER_EMAIL": "e2e@example.invalid",
        }
        for arguments in (("init",), ("symbolic-ref", "HEAD", "refs/heads/main"), ("add", "."), ("commit", "-m", "live Skill")):
            completed = self.box.run_command([git, "-C", str(provider_repo), *arguments], env=git_env)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.box.write_json(
            ".pipebuilder/agents/codex/.codex/hooks.json",
            {"hooks": {"SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": "python3 .codex/hooks/live_probe.py", "timeout": 10}]}]}},
        )
        self.box.write_text(
            ".pipebuilder/agents/codex/.codex/hooks/live_probe.py",
            "import json\nimport pathlib\nimport sys\ndata = json.load(sys.stdin)\npathlib.Path('.codex/hook-receipt.json').write_text(json.dumps({'event': data.get('hook_event_name'), 'cwd': data.get('cwd')}) + '\\n', encoding='utf-8')\n",
        )
        initialized = self.box.run_command([git, "init", "-q"], cwd=self.box.root)
        self.assertEqual(initialized.returncode, 0, initialized.stdout + initialized.stderr)
        self.expect_ok(self.box.builder("build"))
        self.codex_home = self.box.home / "codex-live-home"
        self.codex_home.mkdir(parents=True, exist_ok=True)
        real_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        auth = real_home / "auth.json"
        if not auth.is_file():
            if os.environ.get("PIPEBUILDER_E2E_REQUIRE") == "1":
                self.fail(f"Codex login is required; auth file not found at {auth}")
            self.skipTest(f"Codex login is not configured: {auth}")
        os.symlink(auth, self.codex_home / "auth.json")
        escaped = str(self.box.root).replace("\\", "\\\\").replace('"', '\\"')
        (self.codex_home / "config.toml").write_text(
            f'[projects."{escaped}"]\ntrust_level = "trusted"\n',
            encoding="utf-8",
        )

    def test_real_model_consumes_generated_agents_skill_and_hook(self):
        output = self.box.captures / "last-message.json"
        schema = self.box.write_json(
            "captures/live-schema.json",
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["agents", "skill"],
                "properties": {"agents": {"type": "string"}, "skill": {"type": "string"}},
            },
            base=self.box.base,
        )
        argv = [
            self.codex,
            "--ask-for-approval", "never",
            "--sandbox", "workspace-write",
            "--cd", str(self.box.root),
            "--dangerously-bypass-hook-trust",
            "exec",
            "--ephemeral",
            "--json",
            "--skip-git-repo-check",
            "--output-schema", str(schema),
            "--output-last-message", str(output),
        ]
        model = os.environ.get("PIPEBUILDER_E2E_MODEL")
        if model:
            argv.extend(("--model", model))
        argv.append("$hb-live-sentinel Run the generated PipeBuilder sentinel verification exactly as instructed.")
        result = self.box.run_command(
            argv,
            cwd=self.box.root,
            env={"CODEX_HOME": str(self.codex_home)},
            timeout=240,
            inherit_auth=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(output.is_file(), "Codex did not write --output-last-message")
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload, {"agents": AGENTS_SENTINEL, "skill": SKILL_SENTINEL})
        events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        self.assertTrue(events)
        self.assertTrue(any(item.get("type") == "thread.started" for item in events), events)
        completed = next((item for item in reversed(events) if item.get("type") == "turn.completed"), None)
        if completed and isinstance(completed.get("usage"), dict):
            self.client_record["usage"] = completed["usage"]
        receipt_path = self.box.root / ".codex/hook-receipt.json"
        self.assertTrue(receipt_path.is_file(), result.stdout + result.stderr)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["event"], "SessionStart")
        self.assertEqual(Path(receipt["cwd"]), self.box.root)
