"""Findings filtering, pagination and bulk triage."""
from sqlmodel import Session

from app.db import engine
from app.models import Finding, Role
from conftest import login, make_company, make_user


def _campaign(client):
    return client.post("/api/campaigns", json={
        "name": "f", "target": {"type": "demo"},
        "tools": {"promptfoo": True, "promptfoo_plugins": ["harmful"]},
    }).json()["id"]


def test_findings_filter_paginate_bulk():
    co = make_company("Find Co")
    make_user("analyst@find.test", co, Role.analyst)
    client = login("analyst@find.test")
    camp = _campaign(client)

    with Session(engine) as s:
        for i, (sev, passed) in enumerate([("critical", False), ("high", False), ("low", True)]):
            s.add(Finding(company_id=co, campaign_id=camp, tool="custom", category="c",
                          plugin=f"p{i}", severity=sev, passed=passed,
                          prompt=f"secret word {i}", score=0.0))
        s.commit()

    # default: failures only (shape = {items,total})
    d = client.get(f"/api/campaigns/{camp}/findings?passed=false").json()
    assert d["total"] == 2 and len(d["items"]) == 2

    # severity filter
    assert client.get(f"/api/campaigns/{camp}/findings?severity=critical").json()["total"] == 1

    # full-text search
    assert client.get(f"/api/campaigns/{camp}/findings?q=secret word 1").json()["total"] == 1

    # severity sort: critical before high
    items = client.get(f"/api/campaigns/{camp}/findings?passed=false").json()["items"]
    assert items[0]["severity"] == "critical"

    # bulk status
    ids = [f["id"] for f in client.get(f"/api/campaigns/{camp}/findings?passed=all").json()["items"]]
    assert client.post(f"/api/campaigns/{camp}/findings/bulk", json={"ids": ids, "status": "triaged"}).json()["updated"] == 3
    assert client.get(f"/api/campaigns/{camp}/findings?status=triaged&passed=all").json()["total"] == 3
