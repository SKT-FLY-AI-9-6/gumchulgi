# -*- coding: utf-8 -*-
"""
pse_session.py — 브라우저 쿠키 2개로 instaloader 세션 파일을 만든다
====================================================================
Edge / Chrome 이 앱 바운드 암호화(ABE)로 전환된 뒤로 `instaloader --load-cookies`
가 쿠키를 복호화하지 못한다 (Local State 에 app_bound_encrypted_key 가 있으면 해당).
비밀번호 로그인은 체크포인트에 걸린다. 그 두 경우의 우회로다.

**입력한 값은 이 프로세스 밖으로 나가지 않는다.**
  · getpass 로 받으므로 화면에 찍히지 않고, 셸 히스토리에도 안 남는다
  · 명령행 인자로는 받지 않는다 (인자는 프로세스 목록에 노출된다)
  · 어디에도 로그하지 않는다. instaloader 세션 파일에만 저장된다

  sessionid 는 그 계정의 로그인 자체다. 비밀번호와 같은 취급으로 다룰 것 —
  채팅·이슈·스크린샷에 붙여넣지 말 것.

쿠키 찾는 법 (Edge / Chrome 동일)
  1. instagram.com 에 로그인한 탭에서 F12
  2. Application 탭 → 좌측 Storage → Cookies → https://www.instagram.com
  3. `sessionid` 와 `csrftoken` 의 Value 를 각각 복사

사용법
  python pse_session.py
  python pse_session.py --check          # 기존 세션이 살아 있는지만 확인
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys


def clean(v: str) -> str:
    """붙여넣기에 딸려오는 군더더기를 떼어낸다.

    DevTools 에서 복사하면 따옴표가 붙거나, 쿠키를 통째로 복사하면
    'sessionid=...' 형태이거나, 끝에 세미콜론이 붙어 오는 일이 흔하다.
    """
    v = v.strip().strip('"').strip("'").strip()
    for pre in ("sessionid=", "csrftoken="):
        if v.lower().startswith(pre):
            v = v[len(pre):]
    return v.rstrip(";").strip()


def ctrl_only(v: str) -> bool:
    """Windows getpass 에 Ctrl+V 를 눌렀을 때 들어오는 제어문자(0x16) 뿐인지."""
    return bool(v) and all(ord(c) < 32 for c in v)


def read_cookie_file(path: str) -> tuple[str, str]:
    """`sessionid=...` / `csrftoken=...` 두 줄짜리 파일을 읽는다.

    Windows 콘솔에서 getpass 에 붙여넣기가 안 되는 문제의 우회로다. 읽은 뒤
    파일을 지울지 물어본다 — sessionid 가 평문으로 디스크에 남으면 안 되니까.
    """
    vals: dict[str, str] = {}
    with open(path, encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            vals[k.strip().lower()] = clean(v)
    sid, csrf = vals.get("sessionid", ""), vals.get("csrftoken", "")
    if sid and csrf:
        ans = input(f"\n읽었습니다. '{path}' 를 지울까요? "
                    f"(sessionid 가 평문으로 남습니다) [Y/n] ").strip().lower()
        if ans in ("", "y", "yes"):
            try:
                os.remove(path)
                print(f"  삭제됨: {path}")
            except OSError as exc:
                print(f"  삭제 실패: {exc} — 직접 지워주세요.", file=sys.stderr)
        else:
            print(f"  남겨둡니다. 작업이 끝나면 직접 지우세요: {path}")
    return sid, csrf


def shape(v: str) -> str:
    """값을 노출하지 않고 형태만 설명한다 (진단용)."""
    if not v:
        return "빈 값 (붙여넣기가 안 된 듯합니다)"
    kind = ("숫자로 시작" if v[0].isdigit() else
            "영문자로 시작" if v[0].isalpha() else f"'{v[0]}' 로 시작")
    sep = ("%3A 포함" if "%3A" in v else ": 포함" if ":" in v else "구분자 없음")
    return f"{len(v)}자, {kind}, {sep}"


def verify_auth(L, probe_tag: str = "edm") -> tuple[bool, str]:
    """세션이 **실제로 인증되어 있는지** 확인한다. (성공여부, 설명)

    주의 — 계정 id 를 이름으로 바꾸는 `api/v1/users/<id>/info/` 로는 확인이 안 된다.
    그 엔드포인트는 로그인 없이도 응답해서, 가짜 sessionid 로도 통과한다
    (실측으로 확인했다). 인증 여부를 재려면 **로그인이 필요한 것**을 불러야 한다.

    해시태그 메타데이터(api/v1/tags/web_info/)는 인스타가 로그인을 요구한다.
    게다가 이건 pse_collect.py 가 실제로 쓰는 경로라, 통과하면 수집도 된다는 뜻이
    된다 — 검증과 실제 작업이 같은 경로를 타는 게 낫다.
    """
    try:
        from instaloader import Hashtag
        h = Hashtag.from_name(L.context, probe_tag)
        n = h.mediacount
        return True, f"#{probe_tag} 조회 성공 (게시물 {n:,}건)"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {str(exc)[:160]}"


def whoami(L, sessionid: str) -> str | None:
    """계정 id 로 계정명을 조회한다. **인증 확인이 아니다** — 세션 파일 이름용.

    `Instaloader.test_login()` 을 쓰면 안 된다 — 폐기된 GraphQL query_hash
    (d6f4427fbe92d846298cf93df0b937d3) 를 호출해서 세션이 멀쩡해도 400 이 난다.
    instaloader 자신도 Profile.from_id 에서는 이미 우회해 뒀다:
      structures.py:1031  "The GraphQL user query previously used here started
                           responding with HTTP 400."
    그래서 여기서도 같은 우회로(api/v1/users/<id>/info/)를 쓴다.

    사용자 id 는 sessionid 앞부분에 들어 있다 — "<uid>%3A<...>" 또는 "<uid>:<...>".
    쿠키를 하나 더 받지 않아도 된다.
    """
    uid = sessionid.split("%3A")[0].split(":")[0].strip()
    if not uid.isdigit():
        # 값 자체는 절대 찍지 않는다. 형태만 알려줘서 스스로 진단하게 한다.
        print(f"\nsessionid 형태가 예상과 다릅니다 — {shape(sessionid)}", file=sys.stderr)
        print("  기대: '76561234567%3AAbCd...' 처럼 **숫자로 시작**하고 %3A(또는 :)를 포함",
              file=sys.stderr)
        print("  흔한 실수:", file=sys.stderr)
        print("   · csrftoken 을 sessionid 칸에 넣었다 (csrftoken 은 32자 영숫자, 구분자 없음)",
              file=sys.stderr)
        print("   · Value 가 아니라 Name('sessionid') 을 복사했다", file=sys.stderr)
        print("   · DevTools 에서 셀을 한 번만 클릭해 값이 잘렸다 "
              "— 우클릭 → Copy value 로 복사할 것", file=sys.stderr)
        uid = input("\n대신 ds_user_id 쿠키 값을 넣어주세요 (숫자, 비밀 아님): ").strip()
        if not uid.isdigit():
            return None
    # api/v1 계열은 웹 UA 로 400 이 나고 iPhone UA 로는 되는 경우가 있어 둘 다 시도한다
    data, last = None, None
    for how in ("web", "iphone"):
        try:
            path = f"api/v1/users/{uid}/info/"
            data = (L.context.get_json(path, params={}) if how == "web"
                    else L.context.get_iphone_json(path=path, params={}))
            break
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {str(exc)[:140]}"
    if data is None:
        print(f"세션 확인 요청 실패 ({last})", file=sys.stderr)
        return None
    user = (data or {}).get("user") or {}
    return user.get("username")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="브라우저 쿠키로 instaloader 세션 파일 생성")
    ap.add_argument("--check", action="store_true",
                    help="새로 만들지 않고 기존 세션 유효성만 확인")
    ap.add_argument("--user", default=None,
                    help="--check 용 계정명 (없으면 물어본다)")
    ap.add_argument("--from-file", default=None, metavar="PATH",
                    help="'sessionid=...' / 'csrftoken=...' 두 줄짜리 파일에서 읽는다. "
                         "Windows 콘솔에서 Ctrl+V 붙여넣기가 안 될 때 쓸 것")
    a = ap.parse_args()

    try:
        from instaloader import Instaloader
        from instaloader.instaloader import get_default_session_filename
    except ImportError:
        print("instaloader 가 없습니다:  pip install instaloader", file=sys.stderr)
        return 2

    L = Instaloader(quiet=True, download_pictures=False, download_videos=False,
                    download_video_thumbnails=False, save_metadata=False)

    if a.check:
        user = a.user or input("계정명: ").strip()
        try:
            L.load_session_from_file(user)
        except FileNotFoundError:
            print(f"세션 파일이 없습니다: {get_default_session_filename(user)}")
            return 1
        ok, why = verify_auth(L)
        if ok:
            print(f"세션 유효 — {user}  ({why})")
            return 0
        print(f"세션이 만료됐거나 무효합니다. 다시 만들어야 합니다.\n  {why}")
        return 1

    if a.from_file:
        sessionid, csrftoken = read_cookie_file(a.from_file)
    else:
        print("instagram.com 개발자도구(F12) → Application → Cookies 에서 값을 복사하세요.")
        print("입력은 화면에 표시되지 않습니다. 채팅에는 절대 붙여넣지 마세요.")
        print("※ Windows 에서는 Ctrl+V 가 안 먹습니다 — **마우스 우클릭**으로 붙여넣거나,")
        print("  잘 안 되면 --from-file 을 쓰세요 (python pse_session.py --help).\n")
        sessionid = clean(getpass.getpass("sessionid : "))
        csrftoken = clean(getpass.getpass("csrftoken : "))

    if not sessionid or not csrftoken:
        print("두 값이 모두 필요합니다.", file=sys.stderr)
        return 2
    print(f"  받은 sessionid: {shape(sessionid)}")
    print(f"  받은 csrftoken: {shape(csrftoken)}")
    if ctrl_only(sessionid) or ctrl_only(csrftoken):
        print("\n붙여넣기가 되지 않았습니다 — 제어문자 한 글자만 들어왔습니다.\n"
              "  Windows 의 getpass 는 Ctrl+V 를 붙여넣기로 처리하지 않고 0x16 을 그대로 받습니다.\n"
              "  해결: 프롬프트에서 **마우스 우클릭**으로 붙여넣거나, 아래처럼 파일로 넘기세요.\n\n"
              "    1) 메모장에 두 줄 작성 후 cookies.txt 로 저장:\n"
              "         sessionid=<값>\n"
              "         csrftoken=<값>\n"
              "    2) python pse_session.py --from-file cookies.txt\n"
              "       (읽고 나서 파일을 지울지 물어봅니다)", file=sys.stderr)
        return 2

    # load_session 은 csrftoken 을 반드시 요구한다 (instaloadercontext.py:228)
    cookies = {"sessionid": sessionid, "csrftoken": csrftoken}
    L.load_session("__probe__", cookies)

    # 인증 확인이 먼저다. 계정명 조회는 인증을 증명하지 못한다 (verify_auth 주석 참조)
    ok, why = verify_auth(L)
    if not ok:
        print(f"\n인증 확인 실패 — {why}\n\n"
              "원인은 대체로 셋 중 하나입니다:\n"
              "  · sessionid 를 잘못 복사했다 (앞뒤 공백·따옴표 포함 여부 확인)\n"
              "  · 브라우저에서 로그아웃했다 — 로그아웃하면 sessionid 가 즉시 무효화된다\n"
              "  · 계정에 체크포인트가 걸려 있다 — 브라우저에서 먼저 해제할 것",
              file=sys.stderr)
        return 1
    print(f"  인증 확인 — {why}")

    who = whoami(L, sessionid) or input("계정명을 확인하지 못했습니다. 직접 입력: ").strip()
    if not who:
        return 1

    L.context.username = who
    L.save_session_to_file()
    path = get_default_session_filename(who)
    print(f"\n세션 저장 완료 — {who}")
    print(f"  {path}")
    print(f"\n다음:\n  python pse_collect.py --session-user {who} --tag edm -n 3 -o reels")
    return 0


if __name__ == "__main__":
    sys.exit(main())
