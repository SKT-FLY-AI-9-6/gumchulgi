# -*- coding: utf-8 -*-
"""
pse_refetch.py — shortcode 를 지정해 릴스를 다시 받는다
========================================================
`pse_collect.py` 는 해시태그를 순회해서 **새 표본**을 만든다. 이 파일은 반대로
**이미 아는 shortcode 목록**을 그대로 다시 받는다. 지워버린 표본의 일부를
복구하거나, 특정 편만 재검증할 때 쓴다.

manifest.csv 의 shortcode 만 있으면 되므로, 원본 영상을 지웠어도 그 표본을
그대로 되살릴 수 있다 (게시자가 삭제·비공개로 돌린 것은 제외).

사용법
  python pse_refetch.py --session-user 아이디 -o reels_fp Db2H1qGAZkb Db13dofJyC7
  python pse_refetch.py --session-user 아이디 -o reels_fp --from-file codes.txt
"""
from __future__ import annotations

import argparse
import os
import sys
import time


def main() -> int:
    ap = argparse.ArgumentParser(description="shortcode 지정 재수집")
    ap.add_argument("codes", nargs="*", help="shortcode 들")
    ap.add_argument("--session-user", required=True)
    ap.add_argument("-o", "--outdir", default="refetch")
    ap.add_argument("--from-file", default=None,
                    help="줄바꿈/공백으로 구분된 shortcode 목록 파일")
    ap.add_argument("--sleep", type=float, default=4.0)
    a = ap.parse_args()

    codes = list(a.codes)
    if a.from_file:
        with open(a.from_file, encoding="utf-8-sig") as fh:
            codes += fh.read().split()
    codes = [c.strip() for c in codes if c.strip()]
    if not codes:
        print("shortcode 가 없습니다.", file=sys.stderr)
        return 2

    try:
        from instaloader import Instaloader, Post
    except ImportError:
        print("instaloader 가 없습니다:  pip install instaloader", file=sys.stderr)
        return 2

    L = Instaloader(quiet=True, download_pictures=False, download_videos=False,
                    download_video_thumbnails=False, save_metadata=False)
    try:
        L.load_session_from_file(a.session_user)
    except FileNotFoundError:
        print(f"'{a.session_user}' 세션이 없습니다. python pse_session.py 먼저 실행.",
              file=sys.stderr)
        return 2

    os.makedirs(a.outdir, exist_ok=True)
    got = gone = 0
    for i, code in enumerate(codes, 1):
        dest = os.path.join(a.outdir, f"{code}.mp4")
        if os.path.exists(dest):
            print(f"  [{i}/{len(codes)}] {code} 이미 있음", file=sys.stderr)
            got += 1
            continue
        try:
            p = Post.from_shortcode(L.context, code)
            url = p.video_url
            if not url:
                print(f"  [{i}/{len(codes)}] {code} 영상 아님", file=sys.stderr)
                continue
            resp = L.context.get_raw(url)
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(1 << 16):
                    fh.write(chunk)
            got += 1
            print(f"  [{i}/{len(codes)}] {code}  {os.path.getsize(dest)/1e6:.1f}MB",
                  file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            gone += 1
            print(f"  [{i}/{len(codes)}] {code} 실패: {type(exc).__name__}: "
                  f"{str(exc)[:90]}", file=sys.stderr)
            if os.path.exists(dest):
                os.remove(dest)
        time.sleep(a.sleep)

    print(f"\n완료: {got}/{len(codes)}편  (실패 {gone})  → {a.outdir}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
