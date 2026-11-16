import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pdf_preflight


def test_missing_palette_path_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="palette"):
        pdf_preflight.load_palette(str(tmp_path / "missing.txt"))


def test_empty_palette_file_is_rejected(tmp_path):
    palette = tmp_path / "palette.txt"
    palette.write_text("no colors specified")
    with pytest.raises(ValueError, match="palette"):
        pdf_preflight.load_palette(str(palette))


def test_palette_file_and_inline_list_match(tmp_path):
    palette = tmp_path / "palette.txt"
    palette.write_text("black #000000 and white #ffffff")
    expected = ["#000000", "#FFFFFF"]
    assert pdf_preflight.load_palette(str(palette)) == expected
    assert pdf_preflight.load_palette("#000000,#ffffff") == expected
    assert pdf_preflight.load_palette(None) == []
