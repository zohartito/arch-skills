import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import seeded_eval


@pytest.mark.parametrize("size", [None, (17, 11), (36, 24)])
def test_all_five_seeds_are_detectable(tmp_path, size):
    if size is None:
        source = Path(__file__).resolve().parents[3] / "evals/fixtures/sheet-review.pdf"
    else:
        source = tmp_path / "source.pdf"
        with fitz.open() as doc:
            doc.new_page(width=size[0] * 72, height=size[1] * 72)
            doc.save(source)
    seeded = tmp_path / "seeded.pdf"
    key = seeded_eval.plant_defects(source, seeded)
    report = seeded_eval.run_preflight(seeded, tmp_path / "report",
                                       ["--palette", "#000000,#ffffff", "--compare", str(source)])
    missed = [entry["defect"] for entry in key if not seeded_eval.caught(entry, report["findings"])]
    assert missed == []
