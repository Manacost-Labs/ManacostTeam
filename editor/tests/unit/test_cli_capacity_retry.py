import importlib.util
import json
import subprocess
import threading
import urllib.request
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("capacity_bridge", Path(__file__).parents[2] / "tools/cli_model_bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
CAPACITY = "Selected model is at capacity. Please try a different model."


def stream(*events):
    return "\n".join(json.dumps(x) for x in events).encode()


def failure(message=CAPACITY):
    return stream({"type": "error", "message": message}, {"type": "turn.failed", "error": {"message": message}})


def completed(reply):
    return stream({"type": "item.completed", "item": {"type": "agent_message", "text": reply}}, {"type": "turn.completed"})


def test_capacity_retry_reuses_identical_input_and_keeps_total_deadline(monkeypatch, tmp_path):
    seen = []
    clock = [0.0]
    monkeypatch.setattr(bridge.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(bridge.time, "sleep", lambda delay: clock.__setitem__(0, clock[0] + delay))
    last = tmp_path / "last"

    def run(remaining, attempt):
        seen.append((remaining, attempt))
        clock[0] += 1
        if attempt == 0:
            return subprocess.CompletedProcess(["same-model"], 1, failure(), b"")
        last.write_text("negative factual review", "utf8")
        return subprocess.CompletedProcess(["same-model"], 0, completed(last.read_text("utf8")), b"")

    proc = bridge.run_codex_with_capacity_retry(run, timeout=30, last_message=str(last))
    assert proc.returncode == 0
    assert len(seen) == 2 and seen[0] == (30, 0) and seen[1][0] < 29 and seen[1][1] == 1


@pytest.mark.parametrize("raw,code,has_reply", [
    (completed('{"status":"insufficient"}'), 0, True),
    (completed("negative verdict") + b"\n" + failure(), 1, True),
    (stream({"type": "item.started", "item": {"type": "agent_message"}}) + b"\n" + failure(), 1, False),
    (failure("usage limit"), 1, False),
    (failure("not logged in"), 1, False),
    (failure(), 0, False),
    (failure(), 1, True),
    (b"malformed" + failure(), 1, False),
    (failure() + b"\xff", 1, False),
])
def test_capacity_retry_never_revotes_content_or_retries_other_failures(monkeypatch, tmp_path, raw, code, has_reply):
    last = tmp_path / "last"
    if has_reply:
        last.write_text("partial or complete reply", "utf8")
    calls = []
    monkeypatch.setattr(bridge.time, "sleep", lambda _: pytest.fail("unexpected backoff"))

    def run(remaining, attempt):
        calls.append(attempt)
        return subprocess.CompletedProcess([], code, raw, b"")

    bridge.run_codex_with_capacity_retry(run, timeout=30, last_message=str(last))
    assert calls == [0]


def test_capacity_retries_are_bounded_and_timeouts_are_not_retried(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge.time, "sleep", lambda _: None)
    calls = []

    def run(remaining, attempt):
        calls.append(attempt)
        return subprocess.CompletedProcess([], 1, failure(), b"")

    assert bridge.run_codex_with_capacity_retry(run, timeout=30, last_message=str(tmp_path / "last")).returncode == 1
    assert calls == [0, 1, 2]

    def timed_out(remaining, attempt):
        calls.append(attempt)
        raise subprocess.TimeoutExpired("codex", remaining)

    calls.clear()
    with pytest.raises(subprocess.TimeoutExpired):
        bridge.run_codex_with_capacity_retry(timed_out, timeout=30, last_message=str(tmp_path / "last"))
    assert calls == [0]


def test_capacity_retry_respects_short_deadline_and_known_config_warnings(monkeypatch, tmp_path):
    raw = stream({"type": "item.completed", "item": {"type": "error", "message": "Codex is ignoring 2 unrecognized configuration settings.\nuser: ignored"}}) + b"\n" + failure()
    proc = subprocess.CompletedProcess([], 1, raw, b"")
    last = str(tmp_path / "last")
    assert bridge._codex_capacity_failure(proc, last)
    calls = []
    monkeypatch.setattr(bridge.time, "sleep", lambda _: pytest.fail("backoff exceeds remaining deadline"))

    def run(remaining, attempt):
        calls.append(attempt)
        return proc

    assert bridge.run_codex_with_capacity_retry(run, timeout=4, last_message=last) is proc
    assert calls == [0]


def test_codex_backend_uses_shared_retry_and_returns_completed_negative_review(monkeypatch, tmp_path):
    calls = []
    reply = '{"candidate_checked":true,"claims":[{"status":"insufficient"}]}'
    monkeypatch.setattr(bridge.time, "sleep", lambda _: None)

    def run(argv, **kw):
        calls.append((argv, kw["input"]))
        assert "--json" in argv
        if len(calls) == 1:
            return subprocess.CompletedProcess(argv, 1, failure(), b"")
        Path(argv[argv.index("-o") + 1]).write_text(reply, "utf8")
        return subprocess.CompletedProcess(argv, 0, completed(reply), b"")

    monkeypatch.setattr(bridge.subprocess, "run", run)
    backend = bridge.Backend("codex", "same-model", "", [], str(tmp_path))
    api = bridge.Bridge(backend, 30, 1)
    server = bridge.serve(api, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
            data=json.dumps({"messages": [{"role": "user", "content": "unchanged facts"}]}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            code, body = response.status, json.load(response)
    finally:
        server.shutdown()
    assert code == 200 and body["choices"][0]["message"]["content"] == reply
    assert len(calls) == 2 and calls[0] == calls[1]


@pytest.mark.parametrize("raw,last_reply", [(completed("different"), "reply"), (b"", "partial"), (failure(), "partial")])
def test_codex_backend_rejects_unfinished_or_disagreeing_transport(monkeypatch, tmp_path, raw, last_reply):
    def run(argv, **kw):
        Path(argv[argv.index("-o") + 1]).write_text(last_reply, "utf8")
        return subprocess.CompletedProcess(argv, 0, raw, b"")

    monkeypatch.setattr(bridge.subprocess, "run", run)
    backend = bridge.Backend("codex", "same-model", "", [], str(tmp_path))
    reply, code, _ = backend.run("", "input", 30)
    assert code != 0 and not reply
