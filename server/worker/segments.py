"""구간 저장 — 필터가 실제로 건드린 구간만 조각으로 남긴다.

설계: docs/구간저장-토글-설계.md

    채택본(filtered.mp4) + armed_segments
      -> 0.5초 격자로 정렬·병합
      -> 무손실 절단(-c copy)  ※ 절단면이 IDR 이라 재인코딩이 없다
      -> [필수] 원본에 조각을 끼워 이어붙이고 **다시 판정**
      -> 적합이면 조각 저장, 아니면 통짜로 후퇴

구간을 심판의 violation_segments 가 아니라 **필터 개입 구간**으로 잡는 이유 —
pselive3 는 위반 임계보다 낮은 데서 미리 무장한다(arm_count 2.0 = "3회가 되기
전에", arm_area 0.20 < 표준 0.25). 심판 구간만 자르면 그 밖에서 필터가
바꿔놓은 부분이 원본으로 재생되어 이음매에 점프가 생긴다. 무장 구간을 쓰면
경계에서 keff=1 이라 **필터본 = 원본**이 보장된다.
"""
from pathlib import Path

from app import storage
from worker import detect, ffmpeg

GOP_S = ffmpeg.GOP_S    # 0.5초. 절단 단위이자 토글 전환 지연 상한
TIME_GUARD = 0.95       # 시간 비율이 이 이상이면 조각 만들 것도 없이 통짜
BYTE_GUARD = 0.85       # 조각 총 바이트가 통짜의 이 배 이상이면 통짜


def snap(segs, dur: float, gop: float = GOP_S) -> list:
    """구간을 gop 격자로 넓히고 겹치면 병합한다."""
    out = []
    for a, b in segs:
        a2 = max(0.0, int(a / gop) * gop)
        b2 = min(dur, (int(b / gop) + 1) * gop)
        if out and a2 <= out[-1][1] + 1e-6:
            out[-1][1] = max(out[-1][1], b2)
        else:
            out.append([a2, b2])
    return out


def store(conn, video_id: int, orig: Path, filtered: Path,
          armed_segments, duration_s: float) -> tuple[str, float]:
    """조각 저장을 시도한다. 반환 (storage_mode, 조각 길이 합).

    실패·무이득이면 'full' 을 돌려주고 조각을 지운다 — 통짜 filtered.mp4 는
    어느 경우에도 남으므로 재생은 항상 가능하다.
    """
    if not armed_segments or duration_s <= 0:
        return "full", 0.0

    segs = snap(armed_segments, duration_s)
    seg_s = sum(b - a for a, b in segs)
    if seg_s / duration_s >= TIME_GUARD:
        return "full", 0.0          # 사실상 전체 — 쪼갤 이유가 없다

    vdir = storage.video_dir(video_id)
    pieces = []
    try:
        for i, (a, b) in enumerate(segs):
            p = vdir / f"seg_{i:03d}.mp4"
            ffmpeg.cut_copy(filtered, p, a, b)
            pieces.append((i, a, b, p))

        # **판단 기준은 시간이 아니라 바이트다.** 0.5초 GOP 이 키프레임을 4배로
        # 늘려 짧은 조각이 여럿이면 통짜보다 커진다(실측 104%). 절단이 무손실
        # 이라 싸니 만들어 보고 잰다.
        if sum(p.stat().st_size for *_, p in pieces) >= BYTE_GUARD * filtered.stat().st_size:
            raise _NoGain()

        if not _splice_ok(vdir, orig, pieces, duration_s):
            raise _NoGain()
    except _NoGain:
        _cleanup(pieces)
        return "full", 0.0
    except Exception:
        _cleanup(pieces)
        raise

    conn.executemany(
        "INSERT INTO video_segments(video_id,idx,start_s,end_s,path,bytes)"
        " VALUES(?,?,?,?,?,?)",
        [(video_id, i, a, b, str(p), p.stat().st_size) for i, a, b, p in pieces])
    return "segments", seg_s


class _NoGain(Exception):
    """조각화가 이득이 없거나 판정을 깼다 — 통짜로 후퇴."""


def _cleanup(pieces):
    for *_, p in pieces:
        p.unlink(missing_ok=True)


def _splice_ok(vdir: Path, orig: Path, pieces, duration_s: float) -> bool:
    """조각을 원본에 끼워 이어붙인 결과 = 토글 ON 재생 화면. 그걸 다시 판정한다.

    통짜 필터본이 적합이어도 이어붙인 것이 적합이라는 보장이 없다 — 인코딩
    경계와 격자 확장분이 변수다. 아키텍처 개요의 '남은 관문 3번'(저장 전 심판
    재판정)이 이 설계에서는 선택이 아니다.
    """
    parts, tmp, cur = [], [], 0.0
    spliced = vdir / "_spliced.mp4"
    try:
        for i, a, b, p in pieces:
            if a - cur > 1e-3:
                q = vdir / f"_gap{i:03d}.mp4"
                ffmpeg.cut_copy(orig, q, cur, a)
                parts.append(q); tmp.append(q)
            parts.append(p)
            cur = b
        if duration_s - cur > 1e-3:
            q = vdir / "_gapend.mp4"
            ffmpeg.cut_copy(orig, q, cur, duration_s)
            parts.append(q); tmp.append(q)
        ffmpeg.concat_copy(parts, spliced, vdir)
        return bool(detect.detect(spliced)["compliant"])
    finally:
        for q in tmp:
            q.unlink(missing_ok=True)
        spliced.unlink(missing_ok=True)
