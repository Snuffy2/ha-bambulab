"""Run one bounded, credential-redacted FFmpeg camera diagnostic.

This is a manual diagnostic, not a Home Assistant runtime dependency. It never
retries automatically or changes printer/Home Assistant configuration.
"""

import argparse
from dataclasses import asdict, dataclass, field
import getpass
import ipaddress
import json
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import TextIO
from urllib.parse import quote


@dataclass
class ProbeResult:
    """Allowlisted output: never retain raw FFmpeg lines or input URLs."""

    frames: int = 0
    media_seconds: float = 0
    interleaved_packets: int = 0
    interleaved_bytes: int = 0
    methods: list[str] = field(default_factory=list)
    statuses: dict[str, int] = field(default_factory=dict)
    exit_code: int | None = None
    elapsed: float = 0
    stop_reason: str | None = None
    forced_kill: bool = False

    def accept_line(self, kind: str, line: str) -> None:
        """Extract only recognized numeric fields and protocol method names."""
        if kind == "progress":
            if match := re.fullmatch(r"frame=\s*(\d+)", line):
                self.frames = max(self.frames, int(match[1]))
            elif match := re.fullmatch(r"out_time_us=(\d+)", line):
                self.media_seconds = max(self.media_seconds, int(match[1]) / 1e6)
            return
        if match := re.search(
            r"(?:^|\s)(OPTIONS|DESCRIBE|SETUP|PLAY|GET_PARAMETER|TEARDOWN) rtsps?://",
            line,
        ):
            # A malformed server must not grow our result without bound.
            if len(self.methods) < 100:
                self.methods.append(match[1])
        if match := re.search(r"RTSP/1\.0 (\d{3})(?:\s|$)", line):
            self.statuses[match[1]] = self.statuses.get(match[1], 0) + 1
        if match := re.search(r"\bid=(\d+) len=(\d+)\s*$", line):
            self.interleaved_packets += 1
            self.interleaved_bytes += int(match[2])

    def succeeded(self, duration: float) -> bool:
        """Require decoded video for the requested duration, not just PLAY OK."""
        return (
            self.exit_code == 0
            and self.stop_reason is None
            and self.frames > 0
            and self.media_seconds >= duration - 0.25
        )


def run_probe(
    command: list[str], duration: float, stall_timeout: float, stop_timeout: float = 5
) -> ProbeResult:
    """Drain both pipes throughout probing and shutdown; discard raw lines.

    SIGINT gives FFmpeg a chance to send TEARDOWN. A kill is a last-resort
    cleanup and is reported, never treated as a successful session release.
    """
    result = ProbeResult()
    lock = threading.Lock()
    process = subprocess.Popen(
        command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, errors="replace", bufsize=1,
    )
    start = last_frame = time.monotonic()
    stopping: float | None = None

    def drain(pipe: TextIO, kind: str) -> None:
        with pipe:
            for line in pipe:
                # Discard raw trace immediately, including URLs/auth headers.
                with lock:
                    result.accept_line(kind, line.strip())

    readers = [
        threading.Thread(target=drain, args=(pipe, kind), daemon=True)
        for pipe, kind in ((process.stdout, "progress"), (process.stderr, "trace"))
    ]
    for reader in readers:
        reader.start()
    old_frames = 0
    try:
        while process.poll() is None:
            now = time.monotonic()
            with lock:
                if result.frames > old_frames:
                    last_frame = now
                    old_frames = result.frames
            if stopping is None:
                if now - last_frame > stall_timeout:
                    result.stop_reason = "no_decoded_frame_progress"
                elif now - start > duration + stall_timeout:
                    result.stop_reason = "wall_clock_limit"
                if result.stop_reason:
                    process.send_signal(signal.SIGINT)
                    stopping = now
            elif now - stopping > stop_timeout:
                process.kill()
                result.forced_kill = True
            time.sleep(0.05)
        result.exit_code = process.wait()
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=stop_timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for reader in readers:
            reader.join(timeout=stop_timeout)
        result.elapsed = round(time.monotonic() - start, 2)
    return result


def main() -> int:
    """Prompt privately for credentials and print a JSON diagnostic summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="Printer IP address (no URL or credentials)")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="FFmpeg binary to test")
    parser.add_argument("--duration", type=int, default=60, choices=range(1, 301), metavar="1..300")
    parser.add_argument("--stall-timeout", type=int, default=15, choices=range(5, 61), metavar="5..60")
    parser.add_argument("--insecure", action="store_true", help="Explicitly allow the printer's self-signed TLS certificate")
    args = parser.parse_args()
    try:
        host = str(ipaddress.ip_address(args.host))
    except ValueError:
        parser.error("host must be an IP address")
    binary = shutil.which(args.ffmpeg)
    if binary is None:
        parser.error("FFmpeg binary not found")
    if not sys.stdin.isatty():
        parser.error("run interactively so the access code can be entered without echo")
    access_code = getpass.getpass("Printer access code: ")
    if not access_code:
        parser.error("an access code is required")
    if ":" in host:
        host = f"[{host}]"
    url = f"rtsps://bblp:{quote(access_code, safe='')}@{host}:322/streaming/live/1"
    command = [
        binary, "-hide_banner", "-loglevel", "trace", "-nostats", "-nostdin",
        "-tls_verify", "0" if args.insecure else "1", "-timeout", "5000000",
        "-rtsp_transport", "tcp", "-i", url, "-map", "0:v:0", "-an",
        "-t", str(args.duration), "-progress", "pipe:1", "-f", "null", "-",
    ]
    try:
        result = run_probe(command, args.duration, args.stall_timeout)
    except OSError:
        print(json.dumps({"error": "could_not_run_probe"}))
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"error": "interrupted"}))
        return 130
    print(json.dumps(asdict(result) | {"success": result.succeeded(args.duration)}))
    return 0 if result.succeeded(args.duration) else 1


if __name__ == "__main__":
    raise SystemExit(main())
