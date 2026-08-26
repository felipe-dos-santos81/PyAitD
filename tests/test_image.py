# SPDX-License-Identifier: GPL-2.0-only
import numpy as np
import pytest

from PyAitD.engine.formats import decode_image, decode_palette
from PyAitD.engine.pak import Pak


def test_palette_golden_values(data_dir):
    pak = Pak(data_dir / "ITD_RESS.PAK")
    pal = decode_palette(pak.read(3))
    assert pal.shape == (256, 3)
    assert pal.dtype == np.uint8
    assert tuple(pal[0]) == (0, 0, 0)
    assert tuple(pal[1]) == (255, 255, 255)


def test_palette_passthrough_8bit():
    raw = bytes([63, 0, 0] + [0] * (768 - 3))
    pal = decode_palette(raw)
    assert tuple(pal[0]) == (63, 0, 0)  # stored 8-bit: no expansion
    raw = bytes([200, 100, 50] + [0] * (768 - 3))
    assert tuple(decode_palette(raw)[0]) == (200, 100, 50)


def test_palette_rejects_bad_size():
    with pytest.raises(ValueError):
        decode_palette(b"\x00" * 767)


def test_camera_image_decode(data_dir):
    pal = decode_palette(Pak(data_dir / "ITD_RESS.PAK").read(3))
    img_raw = Pak(data_dir / "CAMERA00.PAK").read(0)
    img = decode_image(img_raw, pal)
    assert img.shape == (200, 320, 3)
    first_index = img_raw[0]
    assert tuple(img[0, 0]) == tuple(pal[first_index])
    # every pixel must equal its palette lookup
    indices = np.frombuffer(img_raw, dtype=np.uint8).reshape(200, 320)
    assert (img == pal[indices]).all()


def test_image_rejects_bad_size():
    pal = np.zeros((256, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        decode_image(b"\x00" * 100, pal)
