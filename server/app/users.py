import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import current_user
from app.db import get_db

router = APIRouter()


class SettingsIO(BaseModel):
    filter_on: bool
    auto_skip: bool


def load_settings(conn, user_id: int) -> dict:
    row = conn.execute("SELECT filter_on, auto_skip FROM user_settings "
                       "WHERE user_id=?", (user_id,)).fetchone()
    return {"filter_on": bool(row["filter_on"]),
            "auto_skip": bool(row["auto_skip"])}


@router.get("/me/settings")
def get_settings(user=Depends(current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    return load_settings(conn, user["id"])


@router.put("/me/settings")
def put_settings(body: SettingsIO, user=Depends(current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("UPDATE user_settings SET filter_on=?, auto_skip=? "
                 "WHERE user_id=?",
                 (int(body.filter_on), int(body.auto_skip), user["id"]))
    return body
