"""Tests for Bambu Lab camera entity behavior."""

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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


@pytest.mark.asyncio
async def test_other_rtsp_camera_uses_default_async_still() -> None:
    """Direct still calls for other RTSP cameras retain HA's default path."""
    camera = make_camera(Printers.X1C)
    stream = MagicMock()
    stream.outputs.return_value = {"hls": object()}
    stream.async_get_image = AsyncMock(return_value=b"stream image")
    camera.stream = stream
    camera.hass = MagicMock()
    camera.hass.async_add_executor_job = AsyncMock(
        side_effect=lambda target: target()
    )
    camera.camera_image = MagicMock(return_value=b"default image")

    assert await camera.async_camera_image() == b"default image"
    stream.async_get_image.assert_not_awaited()
    camera.hass.async_add_executor_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_x2d_caches_image_from_active_stream() -> None:
    """An active HA stream supplies and caches the X2D thumbnail."""
    camera = make_camera(Printers.X2D)
    stream = MagicMock()
    stream.outputs.return_value = {"hls": object()}
    stream.async_get_image = AsyncMock(return_value=b"stream image")
    camera.stream = stream

    assert await camera.async_camera_image(width=640, height=480) == b"stream image"
    stream.async_get_image.assert_awaited_once_with(width=640, height=480)

    stream.outputs.return_value = {}
    assert await camera.async_camera_image() == b"stream image"
    stream.async_get_image.assert_awaited_once()


@pytest.mark.asyncio
async def test_x2d_keeps_previous_image_when_active_stream_has_no_frame() -> None:
    """A missing new keyframe does not replace the previous thumbnail."""
    camera = make_camera(Printers.X2D)
    camera._last_stream_image = b"previous image"
    stream = MagicMock()
    stream.outputs.return_value = {"hls": object()}
    stream.async_get_image = AsyncMock(return_value=None)
    camera.stream = stream

    assert await camera.async_camera_image() == b"previous image"


@pytest.mark.asyncio
async def test_x2d_uses_placeholder_before_streaming() -> None:
    """The X2D uses its placeholder until a live stream supplies a frame."""
    camera = make_camera(Printers.X2D)
    stream = MagicMock()
    stream.outputs.return_value = {}
    stream.async_get_image = AsyncMock()
    camera.stream = stream
    camera.hass = MagicMock()
    camera.hass.async_add_executor_job = AsyncMock(
        side_effect=lambda target: target()
    )
    camera.camera_image = MagicMock(return_value=b"placeholder")

    assert await camera.async_camera_image() == b"placeholder"
    stream.async_get_image.assert_not_awaited()
    camera.hass.async_add_executor_job.assert_awaited_once()
