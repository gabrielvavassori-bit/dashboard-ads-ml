#!/usr/bin/env python3
"""Hook Stop do Codex: seleciona e executa protecoes para o diff pendente."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, text=True, capture_output=True, check=False
    )


def _repo_root() -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        return None
    return Path(result.stdout.strip()).resolve()


def _changed_files(repo: Path) -> list[str]:
    tracked = _git(repo, "diff", "--name-only", "HEAD").stdout.splitlines()
    untracked = _git(repo, "ls-files", "--others", "--exclude-standard").stdout.splitlines()
    return sorted({path.replace("\\", "/") for path in [*tracked, *untracked] if path})


def _signature(repo: Path, files: list[str]) -> str:
    diff = _git(repo, "diff", "--binary", "HEAD").stdout
    untracked = []
    for relative in files:
        path = repo / relative
        if path.is_file() and not _git(repo, "ls-files", "--error-unmatch", relative).returncode == 0:
            untracked.append(relative + "\n" + path.read_text(encoding="utf-8", errors="replace"))
    return hashlib.sha256((diff + "\n" + "\n".join(untracked)).encode("utf-8")).hexdigest()


def _state_path(repo: Path) -> Path:
    result = _git(repo, "rev-parse", "--git-path", "antiregression-stop-state.json")
    return (repo / result.stdout.strip()).resolve()


def _load_state(path: Path) -> dict[str, str]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(path: Path, state: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def _output(payload: dict[str, object]) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def _block(reason: str) -> int:
    return _output({"decision": "block", "reason": reason})


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        event = {}

    repo = _repo_root()
    if repo is None:
        return _output({"continue": True})

    files = _changed_files(repo)
    if not files:
        return _output({"continue": True})

    guard = repo / "scripts" / "regression_guard.py"
    state_path = _state_path(repo)
    signature = _signature(repo, files)
    previous = _load_state(state_path)
    if (
        event.get("stop_hook_active")
        and previous.get("signature") == signature
        and previous.get("result") == "failed"
    ):
        return _output({
            "continue": False,
            "stopReason": "ANTIREGRESSION permanece falhando; a alteracao nao pode ser declarada segura.",
            "systemMessage": "ANTIREGRESSION: VALIDATION ERROR ou FAIL permanece para o diff atual.",
        })

    command = [sys.executable, str(guard), "--repo", str(repo)]
    for file_name in files:
        command.extend(["--changed-file", file_name])
    selection = subprocess.run(command, cwd=repo, text=True, capture_output=True, check=False)
    if selection.returncode:
        _save_state(state_path, {"signature": signature, "result": "failed"})
        return _block(
            "ANTIREGRESSION: VALIDATION ERROR. O catalogo, o guard ou a configuracao critica nao puderam ser validados."
        )

    try:
        selected = json.loads(selection.stdout.splitlines()[0]).get("matched", [])
    except (IndexError, json.JSONDecodeError):
        _save_state(state_path, {"signature": signature, "result": "failed"})
        return _block("ANTIREGRESSION: VALIDATION ERROR. O seletor nao retornou um resultado valido.")

    if not selected:
        _save_state(state_path, {"signature": signature, "result": "clear"})
        return _output({
            "continue": True,
            "systemMessage": "ANTIREGRESSION: nenhuma regressao relacionada encontrada.",
        })

    execution = subprocess.run([*command, "--run"], cwd=repo, text=True, capture_output=True, check=False)
    if execution.returncode:
        _save_state(state_path, {"signature": signature, "result": "failed"})
        label = "VALIDATION ERROR" if execution.returncode == 2 else "FAIL"
        return _block(
            f"ANTIREGRESSION: {', '.join(selected)}: {label}. "
            "A invariante critica nao foi comprovada; corrija e execute novamente."
        )

    _save_state(state_path, {"signature": signature, "result": "passed"})
    return _output({
        "continue": True,
        "systemMessage": f"ANTIREGRESSION: {', '.join(selected)}: PASS.",
    })


if __name__ == "__main__":
    raise SystemExit(main())
