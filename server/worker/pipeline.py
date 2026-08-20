"""업로드 1건 처리: 정규화 → 검출 → (위반 시) 보정 → 재판정 → 확정.

스펙 2절의 워커 순서 그대로. 사다리(psepipe)는 MVP 범위 밖 —
재판정 불합격은 risk='uncorrected' 로 표시만 한다.
"""
from app import storage
from worker import detect, ffmpeg, filter_stream


def process_video(conn, video_id: int):
    vdir = storage.video_dir(video_id)
    upload = next(p for p in vdir.glob("upload.*"))
    orig = storage.original_path(video_id)

    ffmpeg.normalize(upload, orig)
    ffmpeg.thumbnail(orig, storage.thumb_path(video_id))

    first = detect.detect(orig)
    detect.save_report(first["report"], storage.report_path(video_id))

    if first["compliant"]:
        risk, filtered = "safe", None
    else:
        flt = storage.filtered_path(video_id)
        filter_stream.filter_video(orig, flt)
        second = detect.detect(flt)
        risk = "corrected" if second["compliant"] else "uncorrected"
        filtered = str(flt)

    a = first["axes"]
    conn.execute(
        "UPDATE videos SET status='ready', risk=?, original_path=?,"
        " filtered_path=?, thumb_path=?, report_path=?, duration_s=?,"
        " n_flash=?, n_red=?, n_pattern=?, n_cut=? WHERE id=?",
        (risk, str(orig), filtered, str(storage.thumb_path(video_id)),
         str(storage.report_path(video_id)), first["duration_s"],
         a["flash"], a["red"], a["pattern"], a["cut"], video_id))
    upload.unlink(missing_ok=True)
