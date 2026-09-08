"""Offline tests of the manual camera probe's reporting and process cleanup."""

from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import sys

import pytest

spec = importlib.util.spec_from_file_location(
    "probe_camera_stream", Path(__file__).parents[1] / "scripts/probe_camera_stream.py"
)
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


def test_report_only_exposes_allowlisted_diagnostics() -> None:
    result = probe.ProbeResult()
    for line in (
        "PLAY rtsps://bblp:secret@example.invalid/live RTSP/1.0",
        "Authorization: Digest username=secret, response=private",
        "Session: private-session-id",
        "RTSP/1.0 200 OK",
        "[rtsp @ 123] id=0 len=1234",
        "Error opening input rtsps://bblp:secret@example.invalid/live",
    ):
        result.accept_line("trace", line)
    result.accept_line("progress", "frame=12")
    result.accept_line("progress", "out_time_us=1000000")
    result.accept_line("progress", "out_time_us=N/A")
    report = json.dumps(asdict(result))
    for sensitive in ("secret", "private", "example.invalid", "rtsps://"):
        assert sensitive not in report
    assert result.methods == ["PLAY"]
    assert result.statuses == {"200": 1}
    assert result.interleaved_packets == 1
    assert result.interleaved_bytes == 1234
    assert result.frames == 12
    assert result.media_seconds == 1


@pytest.mark.parametrize(
    ("frames", "media_seconds", "exit_code", "stop_reason", "success"),
    [(0, 60, 0, None, False), (10, 1, 0, None, False),
     (100, 60, 1, None, False), (100, 60, 0, "wall_clock_limit", False),
     (100, 60, 0, None, True)],
)
def test_success_requires_full_decoded_stream(
    frames: int, media_seconds: float, exit_code: int,
    stop_reason: str | None, success: bool,
) -> None:
    result = probe.ProbeResult(
        frames=frames, media_seconds=media_seconds,
        exit_code=exit_code, stop_reason=stop_reason,
    )
    assert result.succeeded(60) is success


def test_drains_large_stderr_without_losing_progress() -> None:
    command = [sys.executable, "-c", """
import sys
sys.stderr.write('private-log-line\\n' * 20000)
print('frame=60\\nout_time_us=2000000', flush=True)
"""]
    result = probe.run_probe(command, duration=2, stall_timeout=5)
    assert result.succeeded(2)
    assert not result.forced_kill


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal semantics")
def test_stalled_child_can_teardown_during_graceful_shutdown() -> None:
    command = [sys.executable, "-c", """
import signal, sys, time
def stop(signum, frame):
    print('TEARDOWN rtsps://private.invalid/live RTSP/1.0', file=sys.stderr, flush=True)
    raise SystemExit(0)
signal.signal(signal.SIGINT, stop)
print('frame=1', flush=True)
while True:
    time.sleep(0.05)
"""]
    result = probe.run_probe(command, duration=10, stall_timeout=0.5, stop_timeout=2)
    assert result.stop_reason == "no_decoded_frame_progress"
    assert "TEARDOWN" in result.methods
    assert not result.forced_kill
    assert not result.succeeded(10)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal semantics")
def test_unresponsive_child_is_reaped_and_never_reported_successful() -> None:
    command = [sys.executable, "-c", """
import signal, time
signal.signal(signal.SIGINT, signal.SIG_IGN)
print('frame=1', flush=True)
while True:
    time.sleep(0.05)
"""]
    result = probe.run_probe(command, duration=10, stall_timeout=0.5, stop_timeout=0.5)
    assert result.forced_kill
    assert result.exit_code is not None
    assert not result.succeeded(10)
