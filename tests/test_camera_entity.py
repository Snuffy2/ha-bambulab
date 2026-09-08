"""Tests for Bambu Lab camera entity behavior."""

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("homeassistant")

# Import the camera platform without executing the integration package's setup
# module, which imports unrelated optional integrations such as SSDP.
package = types.ModuleType("custom_components.bambu_lab")
package.__path__ = [str(Path(__file__).parents[1] / "custom_components/bambu_lab")]
sys.modules[package.__name__] = package

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
