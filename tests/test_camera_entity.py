"""Tests for Bambu Lab camera entity behavior."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("homeassistant")

from custom_components.bambu_lab.camera import BambuLabRtspCamera
from custom_components.bambu_lab.pybambu.const import Printers


def make_camera(printer_type: Printers) -> BambuLabRtspCamera:
    """Create an RTSP camera backed by a minimal coordinator."""
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.get_model().info.device_type = printer_type
    entry = SimpleNamespace(
        data={"serial": "TESTSERIAL"}, options={"access_code": "test"}
    )
    return BambuLabRtspCamera(coordinator, entry)


def test_x2d_does_not_open_stream_for_stills() -> None:
    """X2D thumbnails must not retain a camera stream before live view."""
    assert make_camera(Printers.X2D).use_stream_for_stills is False


def test_other_rtsp_cameras_keep_stream_stills() -> None:
    """Existing RTSP camera still-image behavior remains unchanged."""
    assert make_camera(Printers.X1C).use_stream_for_stills is True
