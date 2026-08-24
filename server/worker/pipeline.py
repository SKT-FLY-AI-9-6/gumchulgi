"""업로드 1건 처리: 정규화 → 검출 → (위반 시) 사다리 보정 → 재판정 → 확정.

사다리(스펙 2026-08-20 개정, 209편 실측 근거 REGRESS_0820.md 8절):
Cfg.strong() 1차 → 재검출 적합이면 채택. 위반 잔존 시 기본 Cfg() 2차 →
두 출력의 위반 규칙 집합을 비교해 strong ⊆ base 면 strong, 아니면 base.
채택본만 filtered.mp4 로 남기고 videos.filter_level 에 강도를 기록한다.
"""
import json
import traceback

from pselive3 import Cfg

# pse_bt1702 등과 같은 방식 — psepipe_v3_seam 이 sys.path 에 있어 최상위로
# import 한다. 모듈이 아직 없어도 워커 기동은 막지 않는다 (impact_json NULL).
try:
    import impact
except Exception:
    impact = None

from app import storage
from worker import detect, ffmpeg, filter_stream


def _rules(result) -> set:
    return set(result["report"].get("failed_rules") or [])


def _correct_with_ladder(video_id: int, orig):
    """위반 원본을 사다리로 보정. (filtered_path, 채택 판정, 강도) 반환."""
    vdir = storage.video_dir(video_id)
    tried = {}                       # level -> (임시 경로, 재검출 결과)
    for level, cfg in (("strong", Cfg.strong()), ("base", Cfg())):
        p = vdir / f"_flt_{level}.mp4"
        filter_stream.filter_video(orig, p, cfg)
        tried[level] = (p, detect.detect(p))
        if tried[level][1]["compliant"]:
            break
    if "base" not in tried:
        adopted = "strong"
    else:
        adopted = ("strong"
                   if _rules(tried["strong"][1]) <= _rules(tried["base"][1])
                   else "base")
    path, result = tried[adopted]
    flt = storage.filtered_path(video_id)
    path.replace(flt)
    for level, (p, _r) in tried.items():
        if level != adopted:
            p.unlink(missing_ok=True)
    return flt, result, adopted


def _measure_impact(orig, flt, report_before, report_after):
    """보정 영향 지표(공용 계약 v1) JSON 문자열. 실패해도 업로드 처리를
    깨지 않는다 — 어떤 예외든 삼키고 None(→ impact_json NULL) 을 돌려준다."""
    try:
        data = impact.measure(str(orig), str(flt),
                              report_before=report_before,
                              report_after=report_after)
        return json.dumps(data, ensure_ascii=False, default=str)
    except Exception:
        traceback.print_exc()
        return None


def process_video(conn, video_id: int):
    vdir = storage.video_dir(video_id)
    upload = next(p for p in vdir.glob("upload.*"))
    orig = storage.original_path(video_id)

    ffmpeg.normalize(upload, orig)
    ffmpeg.thumbnail(orig, storage.thumb_path(video_id))

    first = detect.detect(orig)
    detect.save_report(first["report"], storage.report_path(video_id))

    if first["compliant"]:
        risk, filtered, level, impact_json = "safe", None, None, None
    else:
        flt, second, level = _correct_with_ladder(video_id, orig)
        detect.save_report(second["report"],
                           storage.report_filtered_path(video_id))
        risk = "corrected" if second["compliant"] else "uncorrected"
        filtered = str(flt)
        impact_json = _measure_impact(orig, flt, first["report"],
                                      second["report"])

    a = first["axes"]
    conn.execute(
        "UPDATE videos SET status='ready', risk=?, filter_level=?,"
        " impact_json=?,"
        " original_path=?, filtered_path=?, thumb_path=?, report_path=?,"
        " duration_s=?, n_flash=?, n_red=?, n_pattern=?, n_cut=?"
        " WHERE id=?",
        (risk, level, impact_json, str(orig), filtered,
         str(storage.thumb_path(video_id)),
         str(storage.report_path(video_id)), first["duration_s"],
         a["flash"], a["red"], a["pattern"], a["cut"], video_id))
    upload.unlink(missing_ok=True)
