"""업로드 1건 처리: 정규화 → 검출 → (위반 시) 사다리 보정 → 재판정 → 확정.

사다리(스펙 2026-08-20 개정, 209편 실측 근거 REGRESS_0820.md 8절):
Cfg.strong() 1차 → 재검출 적합이면 채택. 위반 잔존 시 기본 Cfg() 2차 →
두 출력의 위반 규칙 집합을 비교해 strong ⊆ base 면 strong, 아니면 base.
채택본만 filtered.mp4 로 남기고 videos.filter_level 에 강도를 기록한다.
"""
from pselive3 import Cfg

from app import storage
from worker import detect, ffmpeg, filter_stream, segments


def _rules(result) -> set:
    return set(result["report"].get("failed_rules") or [])


def _correct_with_ladder(video_id: int, orig):
    """위반 원본을 사다리로 보정. (filtered_path, 채택 판정, 강도) 반환."""
    vdir = storage.video_dir(video_id)
    tried = {}                       # level -> (임시 경로, 재검출 결과)
    armed = {}                       # level -> armed_segments
    for level, cfg in (("strong", Cfg.strong()), ("base", Cfg())):
        p = vdir / f"_flt_{level}.mp4"
        got: list = []
        filter_stream.filter_video(orig, p, cfg, armed_out=got)
        armed[level] = got
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
    return flt, result, adopted, armed.get(adopted) or []


def process_video(conn, video_id: int):
    vdir = storage.video_dir(video_id)
    upload = next(p for p in vdir.glob("upload.*"))
    orig = storage.original_path(video_id)

    ffmpeg.normalize(upload, orig)
    ffmpeg.thumbnail(orig, storage.thumb_path(video_id))

    first = detect.detect(orig)
    detect.save_report(first["report"], storage.report_path(video_id))

    if first["compliant"]:
        risk, filtered, level = "safe", None, None
        mode, seg_s = "full", None
    else:
        flt, second, level, armed = _correct_with_ladder(video_id, orig)
        detect.save_report(second["report"],
                           storage.report_filtered_path(video_id))
        risk = "corrected" if second["compliant"] else "uncorrected"
        filtered = str(flt)
        # 구간 저장 — 필터가 건드린 구간만 조각으로. 무이득이거나 이어붙인
        # 결과가 판정을 깨면 'full' 로 후퇴한다(통짜 filtered.mp4 는 그대로 남음).
        mode, seg_s = segments.store(conn, video_id, orig, flt, armed,
                                     first["duration_s"])

    a = first["axes"]
    conn.execute(
        "UPDATE videos SET status='ready', risk=?, filter_level=?,"
        " storage_mode=?, seg_total_s=?, seg_ratio=?,"
        " original_path=?, filtered_path=?, thumb_path=?, report_path=?,"
        " duration_s=?, n_flash=?, n_red=?, n_pattern=?, n_cut=?"
        " WHERE id=?",
        (risk, level, mode, seg_s,
         (seg_s / first["duration_s"]) if seg_s and first["duration_s"] else None,
         str(orig), filtered, str(storage.thumb_path(video_id)),
         str(storage.report_path(video_id)), first["duration_s"],
         a["flash"], a["red"], a["pattern"], a["cut"], video_id))
    upload.unlink(missing_ok=True)
