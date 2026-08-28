import datetime as dt
import sqlite3

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.config import settings
from app.db import get_db

router = APIRouter()
bearer = HTTPBearer()


def hash_pw(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def check_pw(p: str, h: str) -> bool:
    return bcrypt.checkpw(p.encode(), h.encode())


def make_token(user_id: int) -> str:
    exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=settings.TOKEN_DAYS)
    return jwt.encode({"sub": str(user_id), "typ": "access", "exp": exp},
                      settings.JWT_SECRET, algorithm="HS256")


def make_media_token(user_id: int) -> str:
    """브라우저 <video>/<img> 전용 단기 토큰.

    브라우저 미디어 태그는 Authorization 헤더를 안정적으로 붙일 수 없으므로
    전체 API 권한이 없는 별도 토큰만 URL 쿼리에 사용한다.
    """
    exp = (dt.datetime.now(dt.timezone.utc)
           + dt.timedelta(minutes=settings.MEDIA_TOKEN_MINUTES))
    return jwt.encode({"sub": str(user_id), "typ": "media", "exp": exp},
                      settings.JWT_SECRET, algorithm="HS256")


def _user_from_token(conn: sqlite3.Connection, token: str,
                     expected_type: str) -> sqlite3.Row:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "토큰이 유효하지 않습니다")
    # 기존 개발 토큰에는 typ가 없을 수 있어 access로만 하위 호환한다.
    token_type = payload.get("typ", "access")
    if token_type != expected_type:
        raise HTTPException(401, "토큰 용도가 올바르지 않습니다")
    row = conn.execute("SELECT * FROM users WHERE id=?",
                       (int(payload["sub"]),)).fetchone()
    if row is None:
        raise HTTPException(401, "사용자가 없습니다")
    return row


def user_from_token(conn: sqlite3.Connection, token: str) -> sqlite3.Row:
    return _user_from_token(conn, token, "access")


def user_from_media_token(conn: sqlite3.Connection, token: str) -> sqlite3.Row:
    return _user_from_token(conn, token, "media")


def current_user(cred: HTTPAuthorizationCredentials = Depends(bearer),
                 conn: sqlite3.Connection = Depends(get_db)) -> sqlite3.Row:
    return user_from_token(conn, cred.credentials)


class SignupIn(BaseModel):
    email: str
    password: str
    nickname: str


class LoginIn(BaseModel):
    email: str
    password: str


def _user_out(row) -> dict:
    return {"id": row["id"], "email": row["email"],
            "nickname": row["nickname"],
            "is_admin": bool(row["is_admin"])}


def _create_user(conn, email: str, password: str, nickname: str):
    cur = conn.execute(
        "INSERT INTO users(email, password_hash, nickname) VALUES(?,?,?)",
        (email, hash_pw(password.encode()[:72].decode(errors="ignore")),
         nickname))
    uid = cur.lastrowid
    conn.execute("INSERT INTO user_settings(user_id) VALUES(?)", (uid,))
    return conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


@router.post("/auth/signup", status_code=201)
def signup(body: SignupIn, conn: sqlite3.Connection = Depends(get_db)):
    if not settings.AUTH_OPEN:
        if len(body.password) < 8:
            raise HTTPException(422, "비밀번호는 8자 이상")
        if len(body.password.encode('utf-8')) > 72:
            raise HTTPException(422, "비밀번호는 72바이트 이하")
    try:
        email = body.email.strip().lower()
        row = _create_user(conn, email, body.password,
                           body.nickname)
    except sqlite3.IntegrityError:
        if not settings.AUTH_OPEN:
            raise HTTPException(409, "이미 가입된 이메일입니다")
        # 개방 인증: 이미 있으면 그 계정으로 그냥 들여보낸다
        row = conn.execute("SELECT * FROM users WHERE email=?",
                           (email,)).fetchone()
    return {"token": make_token(row["id"]), "user": _user_out(row)}


@router.post("/auth/login")
def login(body: LoginIn, conn: sqlite3.Connection = Depends(get_db)):
    email = body.email.strip().lower()
    row = conn.execute("SELECT * FROM users WHERE email=?",
                       (email,)).fetchone()
    if settings.AUTH_OPEN:
        # 개방 인증: 비밀번호 검증 생략, 없는 계정은 자동 생성 (시연 전용)
        if row is None:
            nickname = email.split("@")[0] or "게스트"
            row = _create_user(conn, email, body.password,
                               nickname)
        return {"token": make_token(row["id"]), "user": _user_out(row)}
    if row is None:
        raise HTTPException(401, "이메일 또는 비밀번호가 틀립니다")
    try:
        pwd_match = check_pw(body.password, row["password_hash"])
    except ValueError:
        # Password exceeds 72 bytes, treat as wrong password
        pwd_match = False
    if not pwd_match:
        raise HTTPException(401, "이메일 또는 비밀번호가 틀립니다")
    return {"token": make_token(row["id"]), "user": _user_out(row)}


@router.get("/me")
def me(user: sqlite3.Row = Depends(current_user)):
    return _user_out(user)


@router.post("/auth/media-token")
def media_token(user: sqlite3.Row = Depends(current_user)):
    return {"token": make_media_token(user["id"]),
            "expires_in": settings.MEDIA_TOKEN_MINUTES * 60}
