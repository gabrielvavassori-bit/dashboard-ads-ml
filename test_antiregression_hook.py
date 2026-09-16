"""Testes do hook Stop: seletor, falha critica e restauracao."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parent
HOOK = REPO / ".codex" / "hooks" / "antiregression_stop.py"
GUARD = REPO / "scripts" / "regression_guard.py"


class AntiregressionStopHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        (self.repo / ".codex" / "hooks").mkdir(parents=True)
        (self.repo / "scripts").mkdir()
        (self.repo / "regressions").mkdir()
        (self.repo / ".codex" / "hooks" / "antiregression_stop.py").write_text(
            HOOK.read_text(encoding="utf-8"), encoding="utf-8"
        )
        (self.repo / "scripts" / "regression_guard.py").write_text(
            GUARD.read_text(encoding="utf-8"), encoding="utf-8"
        )
        (self.repo / "app.py").write_text("safe = True\n", encoding="utf-8")
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        self._write_manifest("pass")
        self._git("init")
        self._git("config", "user.email", "hook-test@example.invalid")
        self._git("config", "user.name", "Hook Test")
        self._git("add", ".")
        self._git("commit", "-m", "base")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)

    def _write_manifest(self, mode: str) -> None:
        exit_code = "0" if mode == "pass" else "1"
        manifest = {
            "schema_version": "1.0.0",
            "regressions": [{
                "id": "REGRESSION-001",
                "title": "Snapshot integrity",
                "severity": "CRITICA",
                "file_globs": ["app.py"],
                "invariant": "Cobertura parcial nao pode virar KPI completo.",
                "protections": [{
                    "command": ["{python}", "-c", f"raise SystemExit({exit_code})"],
                    "blocking": True,
                }],
            }],
        }
        (self.repo / "regressions" / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

    def _run_hook(self) -> dict:
        result = subprocess.run(
            [sys.executable, str(self.repo / ".codex" / "hooks" / "antiregression_stop.py")],
            cwd=self.repo,
            input=json.dumps({"stop_hook_active": False}),
            text=True,
            capture_output=True,
            check=True,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        return json.loads(result.stdout)

    def test_unrelated_change_skips_critical_suite(self) -> None:
        (self.repo / "README.md").write_text("unrelated\n", encoding="utf-8")
        output = self._run_hook()
        self.assertTrue(output["continue"])
        self.assertIn("nenhuma regressao relacionada", output["systemMessage"])

    def test_related_change_pass_fail_pass_after_restoration(self) -> None:
        (self.repo / "app.py").write_text("safe = False\n", encoding="utf-8")
        passed = self._run_hook()
        self.assertTrue(passed["continue"])
        self.assertIn("REGRESSION-001: PASS", passed["systemMessage"])

        self._write_manifest("fail")
        failed = self._run_hook()
        self.assertEqual("block", failed["decision"])
        self.assertIn("REGRESSION-001: FAIL", failed["reason"])

        self._write_manifest("pass")
        restored = self._run_hook()
        self.assertTrue(restored["continue"])
        self.assertIn("REGRESSION-001: PASS", restored["systemMessage"])
