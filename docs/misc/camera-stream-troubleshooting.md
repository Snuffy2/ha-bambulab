# Testing an RTSP camera without deploying integration changes

Use `scripts/probe_camera_stream.py` to test the printer directly with an
installed FFmpeg binary. This manual tool makes one video-only connection;
it does not alter Home Assistant, send printer commands, or retry on failure.
It applies to RTSP-capable printers, not the A1/P1 JPEG camera protocol.

## Before testing

- Check print status. Do not restart a printer or toggle camera settings during
  a print as part of this test.
- Close other camera viewers, including dashboards requesting still images.
  Check existing connections where possible. A failed test while another
  reader is connected cannot distinguish connection contention from a stalled
  camera. Closing a browser does not prove that all background consumers stopped.
- Use the printer's current IP address, not an old hostname/IP from its reported
  RTSP URL.
- Use a trusted test host. The tool prompts for the access code and emits only
  allowlisted diagnostics, but FFmpeg still receives the authenticated URL in
  its process arguments. Local process-inspection tools may expose it. Do not
  share process listings or raw FFmpeg trace logs.

From the repository root, replace the documentation address below with the
printer's current IP:

```sh
./.venv/bin/python scripts/probe_camera_stream.py 192.0.2.10 --insecure
```

`--insecure` explicitly disables certificate verification for this probe only,
to allow a printer's self-signed certificate. Omit it when certificate
verification is configured. `--ffmpeg /path/to/ffmpeg` selects another build;
`--duration 120` requests a longer test. The default is 60 seconds, with a
15-second no-decoded-frame watchdog. These are diagnostic limits, not suggested
Home Assistant stream settings.

The default uses ordinary verbose logging and does not impose a short socket
timeout. Add `--protocol-trace` only when RTSP negotiation counters are needed;
trace logging is substantially noisier and should not be the initial playback
test.

## Interpreting the JSON result

- `success` requires decoded frames for the requested media duration, exit code
  zero, and no watchdog stop. An authenticated `PLAY` response alone is not
  successful playback.
- With `--protocol-trace`, `interleaved_packets` and `interleaved_bytes` count
  FFmpeg's RTSP-over-TCP packet trace entries (RTP/RTCP, not decoded video), and
  `methods` and `statuses` summarize negotiation. These fields are
  version-dependent and remain empty with the default verbose logging. Their
  absence alone does not prove there was no network traffic.
- `TEARDOWN` in `methods` means FFmpeg logged a teardown request. It does not
  prove the printer processed that request or released all server resources.
- `stop_reason` indicates a decoded-frame stall or wall-clock deadline.
  `forced_kill` means graceful shutdown did not finish within five seconds.
  Stop testing after a failure; repeated reconnects can confound the diagnosis.

Both subprocess pipes are continuously drained, including during shutdown, so
verbose logging does not itself block FFmpeg on a full pipe. No raw output or
video is saved. A nonzero CLI exit status means the test failed or was interrupted.

## Choosing a fix

First establish sustained playback with one client, then graceful close and a
fresh reconnect. Repeat successful cycles manually before comparing another
version or changing one setting. Compare the same path using Home Assistant's
PyAV runtime before promoting an FFmpeg experiment to integration code.

Keep `use_stream_for_stills=True` unless measurements justify a change: HA can
reuse its existing provider for snapshots; `True` does not inherently open a
second RTSP session. For the X2D, isolated FFplay and PyAV playback succeeded
while repeated HA thumbnail requests failed after the first image. The X2D
therefore uses a placeholder thumbnail so automatic still requests do not claim
the LAN camera before live view. Other RTSP models retain stream-based stills.
Likewise, a working TCP control handshake followed by no video does not justify
a UDP firewall change: compare default RTSPS and explicit TCP playback first.

If a source stalls with multiple clients, isolate it before concluding that
the printer needs a restart. Any recovery that changes production HA or printer
state requires separate approval. Do not disable all users' snapshots or apply
model-wide transport overrides based on one unisolated failure.

References: [FFmpeg RTSP options](https://ffmpeg.org/ffmpeg-protocols.html#rtsp),
[FFmpeg RTSPS transport selection](https://github.com/FFmpeg/FFmpeg/blob/master/libavformat/rtsp.c),
[HA camera image path](https://github.com/home-assistant/core/blob/2026.9.1/homeassistant/components/camera/__init__.py).
