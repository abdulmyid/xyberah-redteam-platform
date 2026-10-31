"""RBAC and multi-tenant isolation — the security-critical guarantees."""
from app.models import Role
from conftest import login, make_company, make_user


def test_login_and_me(admin_client):
    r = admin_client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["role"] == "global_admin"


def test_unauthenticated_is_rejected(client):
    assert client.get("/api/campaigns").status_code == 401


def test_admin_can_create_company(admin_client):
    r = admin_client.post("/api/companies", json={"name": "Acme Security"})
    assert r.status_code == 201, r.text


def _new_campaign(c, name):
    return c.post("/api/campaigns", json={
        "name": name, "target": {"type": "demo"},
        "tools": {"promptfoo": True, "promptfoo_plugins": ["harmful"]},
    })


def test_tenancy_isolation_between_companies():
    ca = make_company("Tenant A")
    cb = make_company("Tenant B")
    ua = make_user("analyst@tenant-a.test", ca, Role.analyst)
    make_user("analyst@tenant-b.test", cb, Role.analyst)

    client_a = login("analyst@tenant-a.test")
    client_b = login("analyst@tenant-b.test")

    r = _new_campaign(client_a, "A-campaign")
    assert r.status_code == 201, r.text
    cid = r.json()["id"]

    # Owner can read it; the other tenant cannot (404, no existence leak)
    assert client_a.get(f"/api/campaigns/{cid}").status_code == 200
    assert client_b.get(f"/api/campaigns/{cid}").status_code == 404

    # B's campaign list must not include A's campaign
    ids_b = [c["id"] for c in client_b.get("/api/campaigns").json()]
    assert cid not in ids_b


def test_duplicate_campaign_copies_config_and_is_scoped():
    ca = make_company("Dup A")
    cb = make_company("Dup B")
    make_user("analyst@dup-a.test", ca, Role.analyst)
    make_user("analyst@dup-b.test", cb, Role.analyst)
    client_a = login("analyst@dup-a.test")
    client_b = login("analyst@dup-b.test")

    cid = _new_campaign(client_a, "orig").json()["id"]
    # owner can duplicate → new draft with same target
    r = client_a.post(f"/api/campaigns/{cid}/duplicate")
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["status"] == "draft" and new["id"] != cid
    # the other tenant cannot duplicate it
    assert client_b.post(f"/api/campaigns/{cid}/duplicate").status_code == 404


def test_viewer_cannot_create_campaign():
    cc = make_company("Tenant V")
    make_user("viewer@tenant-v.test", cc, Role.viewer)
    client = login("viewer@tenant-v.test")
    r = _new_campaign(client, "nope")
    assert r.status_code == 403


def test_global_admin_only_endpoint_blocked_for_company_admin():
    cc = make_company("Tenant G")
    make_user("cadmin@tenant-g.test", cc, Role.company_admin)
    client = login("cadmin@tenant-g.test")
    # SSO config is global-admin only
    assert client.get("/api/sso/config").status_code == 403
