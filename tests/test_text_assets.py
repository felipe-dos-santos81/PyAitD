# SPDX-License-Identifier: GPL-2.0-only
import numpy as np
import pytest

from PyAitD.engine.data.assets import Assets
from PyAitD.engine.data.text import BookToken, parse_book_tokens, parse_system_texts

pytestmark = pytest.mark.engine


def test_system_text_parser_decodes_ids_and_cp437():
    texts = parse_system_texts(b"@20:You Find\r\n@103:A Photograph\r\n")
    assert texts == {20: "You Find", 103: "A Photograph"}


def test_book_parser_emits_layout_controls():
    tokens = parse_book_tokens(b"#CFragment\r\n#P#TThen\x1a")
    assert tokens == (
        BookToken("center"), BookToken("text", "Fragment\n"),
        BookToken("page"), BookToken("tab"), BookToken("text", "Then"),
    )


def test_english_and_reading_background_goldens(data_dir, profile):
    assets = Assets(data_dir, profile)
    assert assets.system_text(20) == "You Find"
    assert assets.system_text(22) == "Take"
    assert assets.system_text(33) == "Drop/Put"
    assert assets.book_tokens(1)[0].text.startswith("They are coming")
    for entry in (6, 7, 8):
        image = assets.resource_screen(entry)
        assert image.shape == (200, 320, 3)
        assert image.dtype == np.uint8


def test_missing_text_names_archive_and_id(data_dir, profile):
    with pytest.raises(KeyError, match=r"ENGLISH\.PAK: text 9999 not found"):
        Assets(data_dir, profile).system_text(9999)
