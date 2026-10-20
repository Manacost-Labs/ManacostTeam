"""Мост к CLI-агентам: OpenAI-совместимый контракт без настоящих CLI."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shlex
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "cli_model_bridge", ROOT / "tools" / "cli_model_bridge.py"
)
bridge_module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(bridge_module)

ECHO = f"{shlex.quote(sys.executable)} -X utf8 -c \"import sys; print('```json\\n' + sys.stdin.read().upper() + '\\n```')\""
FAIL = f"{shlex.quote(sys.executable)} -c \"import sys; sys.stderr.write('Not logged in - Please run /login'); sys.exit(2)\""
SLOW = f"{shlex.quote(sys.executable)} -c \"import time; time.sleep(5); print('late')\""


def start(command: str, timeout: float = 30.0):
    backend = bridge_module.Backend("custom", "test-model", command, [], "")
    server = bridge_module.serve(bridge_module.Bridge(backend, timeout, 1), "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def post(url: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def test_bridge_returns_openai_shaped_reply_and_strips_fences() -> None:
    server, base = start(ECHO)
    try:
        code, body = post(
            f"{base}/v1/chat/completions",
            {
                "model": "ignored",
                "messages": [
                    {"role": "system", "content": "Ты critic."},
                    {"role": "user", "content": "привет"},
                ],
            },
        )
        assert code == 200, body
        content = body["choices"][0]["message"]["content"]
        assert content.startswith("[SYSTEM]\nТЫ CRITIC.")
        assert content.endswith("[USER]\nПРИВЕТ")
        assert "```" not in content
        assert body["model"] == "custom:ignored"
        assert body["choices"][0]["finish_reason"] == "stop"
        with urllib.request.urlopen(f"{base}/health", timeout=10) as response:
            health = json.load(response)
        assert health["ok"] is True and health["backend"] == "custom" and health["calls"] == 1
    finally:
        server.shutdown()


def test_bridge_folds_multi_turn_messages_into_one_prompt() -> None:
    system, prompt = bridge_module.build_prompt(
        [
            {"role": "system", "content": "правила"},
            {"role": "user", "content": '{"source": 1}'},
            {"role": "assistant", "content": "мусор"},
            {"role": "user", "content": "Ответ не разобран. Верни JSON."},
        ]
    )
    assert system == "правила"
    assert prompt.startswith('[USER]\n{"source": 1}')
    assert "[ASSISTANT]\nмусор" in prompt
    assert prompt.endswith("[ASSISTANT]")
    assert bridge_module.build_prompt([{"role": "user", "content": "один"}]) == ("", "один")


@pytest.mark.parametrize("prompt", ["ascii request", "Привет, 世界🙂"])
def test_bridge_preserves_utf8_when_host_locale_is_not_utf8(tmp_path: Path, prompt: str) -> None:
    child = tmp_path / "utf8_cli.py"
    child.write_text(
        "import sys\n"
        "sys.stderr.write('готово🙂')\n"
        "print('```json\\n✓ ' + sys.stdin.read().upper() + '\\n```')\n",
        encoding="utf-8",
    )
    command = f"{shlex.quote(sys.executable)} -X utf8 {shlex.quote(str(child))}"
    worker = """
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location('bridge', sys.argv[1])
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
backend = bridge.Backend('custom', 'test-model', sys.argv[2], [], '')
reply, code, stderr = backend.run('', json.loads(sys.argv[3]), 5)
print(json.dumps({'reply': reply, 'code': code, 'stderr': stderr}))
"""
    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8=0",
            "-c",
            worker,
            str(ROOT / "tools/cli_model_bridge.py"),
            command,
            json.dumps(prompt),
        ],
        env={**os.environ, "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0", "LC_ALL": "C"},
        capture_output=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "reply": "✓ " + prompt.upper(),
        "code": 0,
        "stderr": "готово🙂",
    }


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_bridge_returns_503_for_invalid_utf8_output(tmp_path: Path, stream: str) -> None:
    child = tmp_path / "invalid_utf8_cli.py"
    child.write_text(
        f"import sys\nsys.stdout.write('answer')\nsys.{stream}.buffer.write(b'\\xff')\n",
        encoding="utf-8",
    )
    command = f"{shlex.quote(sys.executable)} -X utf8 {shlex.quote(str(child))}"
    server, base = start(command)
    try:
        code, body = post(
            f"{base}/v1/chat/completions", {"messages": [{"role": "user", "content": "x"}]}
        )
        assert code == 503, body
        assert body["error"]["backend"] == "custom"
        assert "UTF-8" in body["error"]["message"]
    finally:
        server.shutdown()


def test_bridge_reports_cli_failures_as_unavailable_not_as_text() -> None:
    server, base = start(FAIL)
    try:
        code, body = post(
            f"{base}/v1/chat/completions", {"messages": [{"role": "user", "content": "x"}]}
        )
        assert code == 503, body
        assert "не залогинен" in body["error"]["message"]
        code, body = post(f"{base}/v1/chat/completions", {"messages": []})
        assert code == 400
    finally:
        server.shutdown()


def test_bridge_times_out_with_504() -> None:
    server, base = start(SLOW, timeout=0.5)
    try:
        code, body = post(
            f"{base}/v1/chat/completions", {"messages": [{"role": "user", "content": "x"}]}
        )
        assert code == 504, body
        assert "вовремя" in body["error"]["message"]
    finally:
        server.shutdown()


def test_backend_argv_uses_documented_non_interactive_flags(tmp_path: Path) -> None:
    claude = bridge_module.Backend("claude", "sonnet", "", ["--effort", "low"], "")
    argv, stdin = claude.argv("сис", "текст", str(tmp_path), str(tmp_path / "last"))
    assert argv[:4] == ["claude", "-p", "--output-format", "text"]
    assert "--tools" in argv and argv[argv.index("--tools") + 1] == ""
    assert "--bare" in argv and "--no-session-persistence" in argv
    assert "--system-prompt" not in argv
    assert Path(argv[argv.index("--system-prompt-file") + 1]).read_bytes() == "сис".encode("utf-8")
    assert argv[argv.index("--model") + 1] == "sonnet" and argv[-2:] == ["--effort", "low"]
    assert stdin == "текст"
    codex = bridge_module.Backend("codex", "", "", [], "")
    argv, stdin = codex.argv("сис", "текст", str(tmp_path), str(tmp_path / "last"))
    assert argv[:2] == ["codex", "exec"] and argv[-1] == "-"
    for flag in ("--skip-git-repo-check", "--ephemeral", "read-only", "-o"):
        assert flag in argv
    assert stdin == "[SYSTEM]\nсис\n\n[USER]\nтекст"
    assert bridge_module.strip_fence('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert bridge_module.strip_fence("  чистый ответ  ") == "чистый ответ"


@pytest.mark.parametrize("outcome", ["success", "nonzero", "timeout"])
def test_claude_large_system_stays_out_of_argv_and_temp_file_is_cleaned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    system = "Системные правила — 世界🙂\r\n" * 4000
    prompt = "Данные пользователя\n" * 3000
    observed: list[Path] = []

    def invoke(argv: list[str], **kwargs):
        # Reproduces the Windows command-line boundary without a real model.
        assert len(subprocess.list2cmdline(argv)) < 4096
        assert system not in argv and prompt not in argv
        assert "--system-prompt" not in argv
        path = Path(argv[argv.index("--system-prompt-file") + 1])
        observed.append(path)
        assert path.read_bytes() == system.encode("utf-8")
        assert kwargs["input"] == prompt.encode("utf-8")
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return subprocess.CompletedProcess(
            argv, 0 if outcome == "success" else 2, b"ok", b"diagnostic"
        )

    monkeypatch.setattr(bridge_module.subprocess, "run", invoke)
    backend = bridge_module.Backend("claude", "sonnet", "", [], str(tmp_path))
    reply, code, diagnostic = backend.run(system, prompt, 5)
    assert len(observed) == 1
    assert not observed[0].exists() and not observed[0].parent.exists()
    if outcome == "timeout":
        assert (reply, code, diagnostic) == ("", None, "timeout")
    else:
        assert (reply, code, diagnostic) == (
            "ok", 0 if outcome == "success" else 2, "diagnostic"
        )


def test_claude_empty_system_does_not_create_a_prompt_file(tmp_path: Path) -> None:
    backend = bridge_module.Backend("claude", "sonnet", "", [], "")
    argv, stdin = backend.argv("", "user text", str(tmp_path), str(tmp_path / "last"))
    assert "--system-prompt" not in argv and "--system-prompt-file" not in argv
    assert list(tmp_path.iterdir()) == [] and stdin == "user text"


@pytest.mark.parametrize("outcome", ["success", "nonzero", "timeout"])
def test_claude_file_transport_launches_real_child_and_cleans_up(
    tmp_path: Path, outcome: str
) -> None:
    child = tmp_path / "fake_claude.py"
    observed = tmp_path / "observed.json"
    child.write_text(
        "import hashlib,json,pathlib,subprocess,sys,time\n"
        "path=pathlib.Path(sys.argv[sys.argv.index('--system-prompt-file')+1])\n"
        "body={'system_path':str(path),'system_sha':hashlib.sha256(path.read_bytes()).hexdigest(),"
        "'stdin_sha':hashlib.sha256(sys.stdin.buffer.read()).hexdigest(),"
        "'argv_chars':len(subprocess.list2cmdline(sys.argv))}\n"
        "pathlib.Path(sys.argv[2]).write_text(json.dumps(body),encoding='utf-8')\n"
        "if sys.argv[1]=='timeout':time.sleep(10)\n"
        "print(json.dumps(body))\n"
        "sys.exit(2 if sys.argv[1]=='nonzero' else 0)\n",
        encoding="utf-8",
    )

    class ChildBackend(bridge_module.Backend):
        def argv(self, system, prompt, scratch, last_message):
            argv, stdin = super().argv(system, prompt, scratch, last_message)
            return [sys.executable, "-X", "utf8", str(child), outcome, str(observed)] + argv[1:], stdin

    system = "Правило: «мир» 世界🙂\r\n" * 4000
    prompt = "Источник и данные\n" * 3000
    backend = ChildBackend("claude", "sonnet", "", [], str(tmp_path))
    reply, code, _ = backend.run(system, prompt, 2 if outcome == "timeout" else 10)
    packet = json.loads(observed.read_text(encoding="utf-8"))
    assert packet["system_sha"] == hashlib.sha256(system.encode("utf-8")).hexdigest()
    assert packet["stdin_sha"] == hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    assert packet["argv_chars"] < 4096
    system_path = Path(packet["system_path"])
    assert not system_path.exists() and not system_path.parent.exists()
    if outcome == "timeout":
        assert reply == "" and code is None
    else:
        assert json.loads(reply) == packet and code == (2 if outcome == "nonzero" else 0)


def test_custom_backend_requires_command() -> None:
    with pytest.raises(SystemExit):
        bridge_module.parse_args(["--backend", "custom"])
    args = bridge_module.parse_args(
        ["--backend", "claude", "--model", "opus", "--extra-arg=--effort", "--extra-arg=high"]
    )
    assert args.extra_arg == ["--effort", "high"] and args.port == 8790
