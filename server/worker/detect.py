import json
from pathlib import Path

import pse_bt1702

# violation_segments 의 rule 문자열 prefix → 대시보드 자극 축
_CAT = [("플래시", "flash"), ("적색", "red"), ("패턴", "pattern"),
        ("화면전환", "cut"), ("5초지속", "flash")]


def detect(path) -> dict:
    rep = pse_bt1702.analyze(str(path))
    rep.pop("_spatial", None)
    axes = {"flash": 0, "red": 0, "pattern": 0, "cut": 0}
    for seg in rep.get("violation_segments", []):
        for prefix, key in _CAT:
            if str(seg.get("rule", "")).startswith(prefix):
                axes[key] += 1
                break
    return {"compliant": bool(rep["compliant"]), "axes": axes,
            "duration_s": float(rep.get("duration_s") or 0.0), "report": rep}


def save_report(report: dict, path):
    Path(path).write_text(
        json.dumps(report, ensure_ascii=False, default=str),
        encoding="utf-8")
