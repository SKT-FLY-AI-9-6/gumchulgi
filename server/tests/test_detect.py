import json

from worker import detect


def test_safe_clip(testclips):
    r = detect.detect(testclips / "00_safe_gradient.mkv")
    assert r["compliant"] is True
    assert r["axes"] == {"flash": 0, "red": 0, "pattern": 0, "cut": 0}


def test_flash_clip(testclips, tmp_path):
    r = detect.detect(testclips / "01_flash_5hz.mkv")
    assert r["compliant"] is False
    assert r["axes"]["flash"] > 0

    p = tmp_path / "rep.json"
    detect.save_report(r["report"], p)
    assert json.loads(p.read_text(encoding="utf-8"))["compliant"] is False
