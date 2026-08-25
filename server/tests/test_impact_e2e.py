# -*- coding: utf-8 -*-
"""완전 종단 검증 — 업로드 API → 실제 워커(검출·사다리 보정·impact 계산,
스텁 없음) → 시청 이벤트 → /dashboard/recent_impact.

test_impact_api.py 는 impact 를 심어 넣고 API 계약만 재고,
test_worker.py 는 파이프라인 기계 동작만 잰다. 이 파일이 둘 사이의
이음새 — "실제 보정에서 나온 impact 가 대시보드까지 흐르는가" — 를 잇는다.
플래시 위반 합성 클립(01_flash_5hz)이라 사다리·impact 가 반드시 돈다.
"""
import json

from app import db
from worker import main as worker_main

_KEYS = {"v", "lum_mean_drop_pct", "lum_peak_drop_pct",
         "flash_before", "flash_after",
         "flash_viol_s_before", "flash_viol_s_after",
         "color_mean_duv", "color_p95_duv", "color_keep_pct"}


def test_upload_to_dashboard_impact_e2e(client, auth_headers, testclips):
    h = auth_headers(email="e2e@t.co")

    # 1) 실제 업로드 API
    clip = testclips / "01_flash_5hz.mkv"
    with open(clip, "rb") as f:
        r = client.post("/videos", headers=h, data={"title": "E2E 플래시"},
                        files={"file": ("f.mkv", f, "video/x-matroska")})
    assert r.status_code == 202, r.text
    vid = r.json()["video_id"]

    # 2) 실제 워커 1회 — 검출·보정·impact 전부 진짜로 돈다
    conn = db.connect()
    assert worker_main.run_once(conn) is True
    v = conn.execute("SELECT * FROM videos WHERE id=?", (vid,)).fetchone()
    assert v["status"] == "ready" and v["risk"] in ("corrected", "uncorrected")
    assert v["impact_json"], "보정이 일어났는데 impact_json 이 비었다"
    imp = json.loads(v["impact_json"])
    assert _KEYS <= set(imp), f"계약 키 누락: {_KEYS - set(imp)}"
    assert imp["flash_before"] > 0                    # 위반 클립이었다
    assert imp["flash_after"] <= imp["flash_before"]  # 보정이 늘리진 않는다
    assert imp["flash_viol_s_after"] <= imp["flash_viol_s_before"]
    assert 0.0 <= imp["color_keep_pct"] <= 100.0
    for k in ("lum_mean_drop_pct", "lum_peak_drop_pct",
              "color_mean_duv", "color_p95_duv"):
        assert imp[k] == imp[k]                       # NaN 금지
    conn.close()

    # 3) 보정본 시청 이벤트 → 대시보드에 흐른다
    r = client.post(f"/videos/{vid}/events", headers=h,
                    json={"watched_s": 3.0, "variant": "filtered"})
    assert r.status_code in (200, 201, 204), r.text
    items = client.get("/dashboard/recent_impact", headers=h).json()["items"]
    assert [i["video_id"] for i in items] == [vid]
    assert items[0]["impact"]["flash_before"] == imp["flash_before"]
    assert items[0]["filter_level"] in ("strong", "base")
