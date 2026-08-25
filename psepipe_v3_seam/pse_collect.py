# -*- coding: utf-8 -*-
"""
pse_collect.py — 해시태그로 릴스를 모아 표본을 만든다 (instaloader 세션 사용)
==============================================================================
비밀번호는 이 스크립트에 **넣지 않는다.** 세션은 pse_session.py 로 만든다.

    python pse_session.py --from-file cookies.txt
    python pse_collect.py --session-user 아이디 --tag reels --tag fyp -n 100

instaloader 의 게시물 이터레이터를 쓰지 않는 이유 (2026-08-10 실측)
--------------------------------------------------------------------
`Hashtag.get_posts_resumable()` / `get_posts()` / `get_top_posts()` 는 셋 다 못 쓴다.

  · get_posts_resumable  legacy GraphQL query_hash. 열리기는 하는데 **릴스가
                         하나도 안 나온다.** 750건을 훑어도 전부 GraphImage /
                         GraphSidecar 이고 is_video 가 전부 False 였다.
                         인스타가 릴스를 이 피드에서 뺀 것으로 보인다.
  · get_top_posts        신형 응답으로 폴백은 하지만 SectionIterator 가
                         'medias' 키를 기대해서 KeyError 로 깨진다. 실제 응답은
                         layout_content.{one_by_two_item,fill_items} 구조다.

그래서 `api/v1/tags/web_info/` 응답을 직접 파싱한다. 릴스는 여기 있다:

    <tab>.sections[].layout_content.one_by_two_item.clips.items[].media
    <tab>.sections[].layout_content.fill_items[].media          (media_type == 2)

이 구조의 장점이 크다 — media 안에 code / video_duration / video_versions(직접
다운로드 URL) / 해상도 / 작성자가 **전부 들어 있다.** 게시물별 추가 요청이
0건이라, instaloader 경로에서 겪던 레이트 리밋 정체가 없다.

페이지 넘김은 <tab>.next_max_id 를 max_id 로 넘긴다 (실측: 요청당 신규 5~9건).

읽어야 할 제약
--------------
1. **무작위 표본이 아니다.** 인스타에 무작위 추출 엔드포인트가 없다. 결과를
   "릴스 전체의 N%"로 쓰면 안 되고 "이 태그 집합에서 뽑은 N편 중 M%"로 써야 한다.
   manifest.csv 가 그 근거다. 게다가 여기서 보이는 건 **태그를 달아 올린 공개
   릴스**뿐이다 — 태그 없는 릴스는 이 방법으로 닿지 않는다.
2. **장르 태그를 쓰면 답이 오염된다.** #edm 같은 태그는 스트로브·LED 월이 몰려
   있어 위반률이 구조적으로 부풀려진다. 일반 비율을 재려면 #reels #fyp #viral
   같은 도달용 범용 태그를 여러 개 섞을 것.
3. **레이트 리밋이 실재한다.** 기본 대기를 넉넉히 잡아 뒀다 (--sleep). 줄이지 말 것.

중단 후 다시 돌리면 manifest.csv 를 보고 이어받는다.
"""
from __future__ import annotations

import argparse
import csv
import itertools
import os
import random
import sys
import time

MANIFEST = "manifest.csv"
COLS = ["shortcode", "hashtag", "tab", "owner", "taken_at", "duration_s",
        "width", "height", "url", "file"]


# ---------------------------------------------------------------- 응답 파싱
def fetch_page(L, tag: str, max_id: str | None = None) -> dict:
    params = {"__a": 1, "__d": "dis", "tag_name": tag}
    if max_id:
        params["max_id"] = max_id
    r = L.context.get_iphone_json(path="api/v1/tags/web_info/", params=params)
    return r.get("data") or r.get("graphql", {}).get("hashtag") or r


def iter_medias(node: dict):
    """(탭이름, media dict) 를 훑는다. 영상만."""
    for tab in ("top", "recent"):
        t = node.get(tab) or {}
        for s in (t.get("sections") or []):
            lc = s.get("layout_content") or {}
            clips = ((lc.get("one_by_two_item") or {}).get("clips") or {})
            for it in (clips.get("items") or []):
                m = it.get("media") or it
                if m.get("media_type") == 2 and m.get("code"):
                    yield tab, m
            for it in (lc.get("fill_items") or []):
                m = it.get("media") or {}
                if m.get("media_type") == 2 and m.get("code"):
                    yield tab, m


def next_cursor(node: dict) -> str | None:
    for tab in ("top", "recent"):
        t = node.get(tab) or {}
        if t.get("more_available") and t.get("next_max_id"):
            return t["next_max_id"]
    return None


def video_url(m: dict) -> str | None:
    vs = m.get("video_versions") or []
    return vs[0].get("url") if vs else None


def tag_stream(L, tag: str, sleep: float):
    """한 태그에서 영상 media 를 계속 흘려보낸다 (페이지 자동 넘김)."""
    cursor, seen = None, set()
    while True:
        try:
            node = fetch_page(L, tag, cursor)
        except Exception as exc:  # noqa: BLE001
            name = type(exc).__name__
            if "TooManyRequests" in name or "429" in str(exc):
                print("    레이트 리밋. 5분 대기합니다.", file=sys.stderr)
                time.sleep(300)
                continue
            print(f"    #{tag} 페이지 실패: {name}: {str(exc)[:110]}", file=sys.stderr)
            return
        fresh = 0
        for tab, m in iter_medias(node):
            if m["code"] in seen:
                continue
            seen.add(m["code"])
            fresh += 1
            yield tab, m
        cursor = next_cursor(node)
        if not cursor:
            print(f"    #{tag} 더 이상 페이지 없음 (누적 {len(seen)}건)", file=sys.stderr)
            return
        if fresh == 0:
            print(f"    #{tag} 신규 없음 — 중단 (누적 {len(seen)}건)", file=sys.stderr)
            return
        time.sleep(sleep)


# ---------------------------------------------------------------- manifest
def load_manifest(outdir: str) -> dict[str, dict]:
    path = os.path.join(outdir, MANIFEST)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8-sig") as fh:
        return {r["shortcode"]: r for r in csv.DictReader(fh)}


def append_manifest(outdir: str, row: dict, first: bool) -> None:
    with open(os.path.join(outdir, MANIFEST), "a", newline="",
              encoding="utf-8-sig") as fh:
        wr = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        if first:
            wr.writeheader()
        wr.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="해시태그에서 릴스를 모아 PSE 분석용 표본을 만든다")
    ap.add_argument("--session-user", required=True,
                    help="pse_session.py 로 세션을 만들어 둔 계정명")
    ap.add_argument("--tag", action="append", required=True,
                    help="해시태그 (# 없이). 여러 번 지정 — 라운드로빈으로 섞는다")
    ap.add_argument("-n", type=int, default=100, help="목표 편수 (기본 100)")
    ap.add_argument("-o", "--outdir", default="reels")
    ap.add_argument("--min-sec", type=float, default=3.0)
    ap.add_argument("--max-sec", type=float, default=90.0)
    ap.add_argument("--sleep", type=float, default=5.0,
                    help="요청 사이 대기 초 (기본 5. 낮추면 차단 위험)")
    ap.add_argument("--seed", type=int, default=None,
                    help="태그 순회 순서 시드 (재현용). 표집을 무작위로 만들지는 못한다")
    ap.add_argument("--exclude-manifest", action="append", default=[], metavar="PATH",
                    help="이 manifest.csv 들에 있는 shortcode 는 건너뛴다. "
                         "2차 표본을 1차와 겹치지 않게 뽑을 때 쓴다. 여러 번 지정 가능")
    a = ap.parse_args()

    try:
        from instaloader import Instaloader
    except ImportError:
        print("instaloader 가 없습니다:  pip install instaloader", file=sys.stderr)
        return 2

    L = Instaloader(quiet=True, download_pictures=False, download_videos=False,
                    download_video_thumbnails=False, save_metadata=False)
    try:
        L.load_session_from_file(a.session_user)
    except FileNotFoundError:
        print(f"'{a.session_user}' 세션이 없습니다. 먼저:\n"
              f"  python pse_session.py --from-file cookies.txt", file=sys.stderr)
        return 2

    os.makedirs(a.outdir, exist_ok=True)
    have = load_manifest(a.outdir)
    first = not have

    # 이전 표본과 겹치지 않게 — shortcode 만 모아 두면 된다
    excl: set[str] = set()
    for p in a.exclude_manifest:
        try:
            with open(p, encoding="utf-8-sig") as fh:
                n0 = len(excl)
                excl |= {r["shortcode"] for r in csv.DictReader(fh) if r.get("shortcode")}
                print(f"  제외 목록 +{len(excl)-n0}편  ({p})", file=sys.stderr)
        except OSError as exc:
            print(f"  제외 목록 읽기 실패 {p}: {exc}", file=sys.stderr)
            return 2
    tags = list(a.tag)
    if a.seed is not None:
        random.Random(a.seed).shuffle(tags)
    print(f"세션 {a.session_user} · 태그 {tags} · 목표 {a.n}편 "
          f"(이미 {len(have)}편 보유)", file=sys.stderr)

    streams = {t: tag_stream(L, t, a.sleep) for t in tags}
    got, scanned, done = len(have), 0, set()

    for t in itertools.cycle(tags):
        if got >= a.n or len(done) >= len(streams):
            break
        if t in done:
            continue
        try:
            tab, m = next(streams[t])
        except StopIteration:
            done.add(t)
            continue

        scanned += 1
        code = m["code"]
        if code in have or code in excl:
            continue
        dur = float(m.get("video_duration") or 0.0)
        if not (a.min_sec <= dur <= a.max_sec):
            continue
        url = video_url(m)
        if not url:
            continue

        dest = os.path.join(a.outdir, f"{code}.mp4")
        try:
            resp = L.context.get_raw(url)
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(1 << 16):
                    fh.write(chunk)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{got}/{a.n}] 실패 {code}: {type(exc).__name__}: "
                  f"{str(exc)[:90]}", file=sys.stderr)
            if os.path.exists(dest):
                os.remove(dest)
            continue

        row = {"shortcode": code, "hashtag": t, "tab": tab,
               "owner": (m.get("user") or {}).get("username", ""),
               "taken_at": m.get("taken_at", ""),
               "duration_s": round(dur, 2),
               "width": m.get("original_width", 0),
               "height": m.get("original_height", 0),
               "url": f"https://www.instagram.com/reel/{code}/",
               "file": os.path.basename(dest)}
        append_manifest(a.outdir, row, first)
        first = False
        have[code] = row
        got += 1
        print(f"  [{got}/{a.n}] #{t:<10} {code}  {dur:>5.1f}s  "
              f"{os.path.getsize(dest)/1e6:>5.1f}MB", file=sys.stderr)

    print(f"\n완료: {got}편 ({scanned}건 훑음)  →  {a.outdir}/", file=sys.stderr)
    print(f"표집 기록: {os.path.join(a.outdir, MANIFEST)}", file=sys.stderr)
    print(f"\n다음:\n  python pse_batch.py {a.outdir} -o 결과 --width 640",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
