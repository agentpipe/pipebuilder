#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import shutil
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable


E2E_ROOT = Path(__file__).resolve().parent
ROOT = E2E_ROOT.parents[1]
TOOL = ROOT / "harnessbuilder.py"
ARTIFACTS = E2E_ROOT / ".artifacts"


def flatten(suite: unittest.TestSuite) -> list[unittest.TestCase]:
    result: list[unittest.TestCase] = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            result.extend(flatten(item))
        else:
            result.append(item)
    return result


def metadata(test: unittest.TestCase):
    value = getattr(test, "metadata", None)
    if value is None:
        raise RuntimeError(f"case has no metadata: {test.id()}")
    if value.tier not in {"offline", "client", "live"}:
        raise RuntimeError(f"case has invalid tier: {test.id()}: {value.tier}")
    if not value.requirements or not value.tags:
        raise RuntimeError(f"case metadata must declare requirements and tags: {test.id()}")
    return value


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started: dict[str, float] = {}
        self.records: list[dict[str, object]] = []
        self.recorded: set[str] = set()

    def startTest(self, test):
        self.started[test.id()] = time.monotonic()
        super().startTest(test)

    def _record(self, test, status: str, reason: str | None = None):
        if test.id() in self.recorded:
            return
        self.recorded.add(test.id())
        meta = metadata(test)
        item: dict[str, object] = {
            "id": test.id(),
            "tier": meta.tier,
            "requirements": list(meta.requirements),
            "tags": list(meta.tags),
            "agents": list(meta.agents),
            "status": status,
            "durationSeconds": round(time.monotonic() - self.started.get(test.id(), time.monotonic()), 6),
            "commands": getattr(test, "command_records", []),
        }
        if reason:
            item["reason"] = reason
        self.records.append(item)

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "pass")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "fail", self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "fail", self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "skip", reason)

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self._record(test, "fail", self._exc_info_to_string(err, test))


def run_group(tests: list[unittest.TestCase]) -> tuple[list[dict[str, object]], str, bool]:
    stream = io.StringIO()
    suite = unittest.TestSuite(tests)
    runner = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=RecordingResult)
    result: RecordingResult = runner.run(suite)  # type: ignore[assignment]
    return result.records, stream.getvalue(), result.wasSuccessful()


def discover(tiers: Iterable[str]) -> list[unittest.TestCase]:
    loader = unittest.defaultTestLoader
    result: list[unittest.TestCase] = []
    for tier in tiers:
        start = E2E_ROOT / "cases" / tier
        suite = loader.discover(str(start), pattern="test_*.py", top_level_dir=str(E2E_ROOT))
        result.extend(flatten(suite))
    ids = [item.id() for item in result]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise RuntimeError("duplicate case ids: " + ", ".join(duplicates))
    for item in result:
        metadata(item)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="HarnessBuilder black-box E2E runner")
    parser.add_argument("--tier", choices=("offline", "client", "live", "all"), default="offline")
    parser.add_argument("--case", help="substring filter for the fully qualified unittest id")
    parser.add_argument("--agent", choices=("codex", "cursor", "codebuddy", "claude-code"))
    parser.add_argument("--model", help="model override for E2; omit to use the installed Codex default")
    parser.add_argument("--require", action="store_true", help="fail instead of skip when a selected client prerequisite is missing")
    parser.add_argument("--jobs", type=int, default=1, help="parallel workers for cases marked parallel-safe")
    parser.add_argument("--keep-artifacts", action="store_true", help="keep failure artifacts from earlier runs")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be at least 1")
    tiers = ("offline", "client", "live") if args.tier == "all" else (args.tier,)
    sys.path.insert(0, str(E2E_ROOT))
    if not args.keep_artifacts and ARTIFACTS.exists():
        shutil.rmtree(ARTIFACTS)
    if args.require:
        os.environ["HARNESSBUILDER_E2E_REQUIRE"] = "1"
    if "live" in tiers:
        os.environ["HARNESSBUILDER_E2E_LIVE"] = "1"
    if args.model:
        os.environ["HARNESSBUILDER_E2E_MODEL"] = args.model
    tests = discover(tiers)
    if args.case:
        tests = [item for item in tests if args.case in item.id()]
    if args.agent:
        tests = [item for item in tests if not metadata(item).agents or args.agent in metadata(item).agents]
    if not tests:
        print(f"FAIL no test cases matched: {args.case or '<all>'}")
        return 2

    started = time.monotonic()
    parallel = [item for item in tests if metadata(item).parallel_safe]
    serial = [item for item in tests if not metadata(item).parallel_safe]
    if args.jobs == 1:
        outputs = [run_group(tests)]
    else:
        outputs: list[tuple[list[dict[str, object]], str, bool]] = []
        if parallel:
            with ThreadPoolExecutor(max_workers=args.jobs, thread_name_prefix="hb-e2e") as executor:
                futures = [executor.submit(run_group, [test]) for test in parallel]
                for future in as_completed(futures):
                    outputs.append(future.result())
        if serial:
            outputs.append(run_group(serial))

    records = [record for group, _, _ in outputs for record in group]
    records.sort(key=lambda item: str(item["id"]))
    for _, output, _ in sorted(outputs, key=lambda item: item[0][0]["id"] if item[0] else ""):
        sys.stdout.write(output)
    successful = all(item[2] for item in outputs)
    status_counts = {name: sum(1 for item in records if item["status"] == name) for name in ("pass", "fail", "skip")}
    report = {
        "schema": "harnessbuilder-e2e-report.v1",
        "releaseArtifact": str(TOOL),
        "releaseSha256": hashlib.sha256(TOOL.read_bytes()).hexdigest(),
        "runner": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "tier": args.tier,
            "agent": args.agent,
            "model": args.model,
            "jobs": args.jobs,
            "require": args.require,
        },
        "durationSeconds": round(time.monotonic() - started, 6),
        "summary": status_counts,
        "cases": records,
        "status": "pass" if successful else "fail",
    }
    report_path = E2E_ROOT / "e2e-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"summary: {status_counts['pass']} pass, {status_counts['fail']} fail, {status_counts['skip']} skip")
    print(f"report: {report_path}")
    if ARTIFACTS.exists():
        print(f"failure artifacts: {ARTIFACTS}")
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
