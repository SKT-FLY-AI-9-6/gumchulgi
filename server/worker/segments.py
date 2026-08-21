"""구간 저장 — 필터본을 조각으로만 보관한다. 통짜 파일은 남기지 않는다.

설계: docs/구간저장-토글-설계.md

    채택본 + armed_segments
      -> 0.5초 격자로 정렬·병합
      -> 무손실 절단(-c copy)
      -> [필수] 원본에 끼워 이어붙이고 **다시 판정**
      -> 적합이면 그대로, 아니면 **전체를 덮는 조각 1개로 합친다**
      -> 통짜 필터본 삭제

**통짜 = 전체를 덮는 조각 1개**다. 별개 파일로 둘 이유가 없다. 그래서
storage_mode 같은 분기가 없고, 클라이언트는 언제나 같은 방식으로 재생한다.

**재판정 폴백이 항상 성립한다** — 채택본은 이미 적합 판정을 받은 것이므로
(pipeline._correct_with_ladder), 전체를 덮는 조각 1 개는 그 파일과 바이트가
같아 적합이 보장된다. 잘게 쪼갠 것이 이음매 때문에 판정을 깨면 합치면 된다.

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
BYTE_GUARD = 0.85       # 조각합이 전체 덮개의 이 배 이상이면 굳이 쪼개지 않는다


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
          armed_segments, duration_s: float) -> float:
    """필터본을 조각으로 저장하고 통짜를 지운다. 반환: 조각 길이 합(초).

    항상 조각이 최소 1 개 남는다 — 전체를 덮는 1 개가 곧 통짜다.
    """
    vdir = storage.video_dir(video_id)
    segs = snap(armed_segments, duration_s) if armed_segments else []
    fine = bool(segs) and sum(b - a for a, b in segs) < duration_s

    pieces = []
    if fine:
        pieces = _cut_all(vdir, filtered, segs)
        # 잘게 쪼갠 것이 전체 덮개보다 크면 의미가 없다 — 0.5초 GOP 이 키프레임을
        # 4배로 늘려 짧은 조각이 여럿이면 커진다(실측 104%). 요청 수도 는다.
        too_big = (sum(p.stat().st_size for *_, p in pieces)
                   >= BYTE_GUARD * filtered.stat().st_size)
        if too_big or not _splice_ok(vdir, orig, pieces, duration_s):
            _cleanup(pieces)
            pieces = []

    if not pieces:                       # 전체를 덮는 조각 1 개 = 통짜
        pieces = [(0, 0.0, duration_s, _whole(vdir, filtered))]

    conn.execute("DELETE FROM video_segments WHERE video_id=?", (video_id,))
    conn.executemany(
        "INSERT INTO video_segments(video_id,idx,start_s,end_s,path,bytes)"
        " VALUES(?,?,?,?,?,?)",
        [(video_id, i, a, b, str(p), p.stat().st_size) for i, a, b, p in pieces])
    return sum(b - a for _, a, b, _ in pieces)


def _cut_all(vdir: Path, filtered: Path, segs) -> list:
    pieces = []
    try:
        for i, (a, b) in enumerate(segs):
            p = vdir / f"seg_{i:03d}.mp4"
            ffmpeg.cut_copy(filtered, p, a, b)
            pieces.append((i, a, b, p))
    except Exception:
        _cleanup(pieces)
        raise
    return pieces


def _whole(vdir: Path, filtered: Path) -> Path:
    """통짜를 조각 1 개로 바꾼다 — 이동뿐이라 재인코딩이 없다."""
    p = vdir / "seg_000.mp4"
    filtered.replace(p)
    return p


def _cleanup(pieces):
    for *_, p in pieces:
        p.unlink(missing_ok=True)


def _splice_ok(vdir: Path, orig: Path, pieces, duration_s: float) -> bool:
    """조각을 원본에 끼워 이어붙인 결과 = 토글 ON 재생 화면. 그걸 다시 판정한다.

    채택본이 적합이어도 이어붙인 것이 적합이라는 보장이 없다 — 인코딩 경계와
    격자 확장분이 변수다. 아키텍처 개요의 '남은 관문 3번'(저장 전 심판 재판정)
    이 이 설계에서는 선택이 아니다.
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
