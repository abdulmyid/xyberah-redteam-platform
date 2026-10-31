"""SCIM 2.0 provisioning endpoints."""
from conftest import make_company


def _token(admin_client, company_id):
    r = admin_client.post("/api/sso/scim-tokens",
                          json={"name": "test", "company_id": company_id, "default_role": "viewer"})
    assert r.status_code == 201, r.text
    return r.json()["token"]


def test_scim_requires_token(client):
    assert client.get("/scim/v2/Users").status_code == 401


def test_scim_create_list_deactivate(admin_client):
    cid = make_company("SCIM Co")
    tok = _token(admin_client, cid)
    h = {"Authorization": f"Bearer {tok}"}

    r = admin_client.post("/scim/v2/Users", headers=h, json={
        "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
        "userName": "scim.user@scimco.test", "name": {"formatted": "SCIM User"},
        "active": True, "externalId": "ext-1"})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    assert r.json()["active"] is True

    r = admin_client.get('/scim/v2/Users?filter=userName eq "scim.user@scimco.test"', headers=h)
    assert r.status_code == 200
    assert r.json()["totalResults"] == 1

    r = admin_client.patch(f"/scim/v2/Users/{uid}", headers=h, json={
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [{"op": "replace", "value": {"active": False}}]})
    assert r.status_code == 200
    assert r.json()["active"] is False


def test_scim_wrong_token_rejected(admin_client):
    assert admin_client.get("/scim/v2/Users", headers={"Authorization": "Bearer nope"}).status_code == 401
