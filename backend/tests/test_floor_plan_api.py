"""The floor plan: drawing a room, and the tables that outlive the drawing.

These talk to a real MongoDB through the app and skip when none is reachable (see
``tests/conftest.py``).
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import ADMIN_EMAIL, SignIn
from fastapi.testclient import TestClient

OWNER_EMAIL = "owner@example.com"
STAFF_EMAIL = "server@example.com"
OUTSIDER_EMAIL = "stranger@example.com"


def _as(client: TestClient, sign_in: SignIn, email: str) -> None:
    """Become ``email`` in this browser (a fresh cookie jar, then a full sign-in)."""
    client.cookies.clear()
    response = sign_in(email)
    assert response.status_code == 302, response.text


def _table(
    element_id: str,
    label: str,
    *,
    x: float = 40,
    y: float = 40,
    seats: int = 4,
    shape: str = "circle",
    table_id: str | None = None,
) -> dict[str, Any]:
    """One table element, at a size the editor would produce."""
    element: dict[str, Any] = {
        "id": element_id,
        "kind": "table",
        "shape": shape,
        "label": label,
        "seats": seats,
        "x": x,
        "y": y,
        "width": 96,
        "height": 96,
    }
    if table_id is not None:
        element["table_id"] = table_id
    return element


def _plan(*elements: dict[str, Any]) -> dict[str, Any]:
    return {"width": 1200, "height": 800, "elements": list(elements)}


@pytest.fixture
def tenant_id(auth_client: TestClient, sign_in: SignIn) -> str:
    """A restaurant owned by ``OWNER_EMAIL``, who is left signed in."""
    _as(auth_client, sign_in, OWNER_EMAIL)
    response = auth_client.post("/api/v1/tenants", json={"name": "Spice Garden"})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


# ----------------------------------------------------------------------------- reading


def test_a_restaurant_with_no_plan_gets_an_empty_canvas(
    auth_client: TestClient, tenant_id: str
) -> None:
    """ "Nothing drawn yet" is the ordinary first state, not a 404."""
    response = auth_client.get(f"/api/v1/tenants/{tenant_id}/floor-plan")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["elements"] == []
    assert body["tables"] == []
    assert body["width"] > 0 and body["height"] > 0


# ----------------------------------------------------------------------------- saving


def test_saving_a_plan_creates_the_tables_it_draws(auth_client: TestClient, tenant_id: str) -> None:
    """The tables are what a QR code and an order will point at, so they get real ids."""
    response = auth_client.put(
        f"/api/v1/tenants/{tenant_id}/floor-plan",
        json=_plan(
            _table("el-a1", "A1", x=40),
            _table("el-a2", "A2", x=200, seats=2, shape="square"),
            {
                "id": "el-text",
                "kind": "text",
                "text": "Terrace",
                "x": 40,
                "y": 16,
                "width": 160,
                "height": 32,
            },
        ),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert {t["label"]: t["seats"] for t in body["tables"]} == {"A1": 4, "A2": 2}
    drawn = {e["id"]: e for e in body["elements"]}
    assert drawn["el-a1"]["table_id"] in {t["id"] for t in body["tables"]}
    assert drawn["el-text"]["table_id"] is None
    assert drawn["el-text"]["text"] == "Terrace"


def test_a_saved_plan_reads_back(auth_client: TestClient, tenant_id: str) -> None:
    """One plan per restaurant: the second read is the first save."""
    auth_client.put(f"/api/v1/tenants/{tenant_id}/floor-plan", json=_plan(_table("el-a1", "A1")))

    body = auth_client.get(f"/api/v1/tenants/{tenant_id}/floor-plan").json()

    assert [e["id"] for e in body["elements"]] == ["el-a1"]
    assert [t["label"] for t in body["tables"]] == ["A1"]
    assert body["updated_at"] is not None


def test_saving_again_replaces_the_drawing_but_keeps_the_table(
    auth_client: TestClient, tenant_id: str
) -> None:
    """Moving and renaming a table must not mint a new one - the QR code is already printed."""
    first = auth_client.put(
        f"/api/v1/tenants/{tenant_id}/floor-plan", json=_plan(_table("el-a1", "A1"))
    ).json()
    table_id = first["tables"][0]["id"]

    second = auth_client.put(
        f"/api/v1/tenants/{tenant_id}/floor-plan",
        json=_plan(_table("el-a1", "Window 1", x=500, seats=6, table_id=table_id)),
    )

    assert second.status_code == 200, second.text
    tables = second.json()["tables"]
    assert len(tables) == 1
    assert tables[0]["id"] == table_id
    assert tables[0]["label"] == "Window 1"
    assert tables[0]["seats"] == 6
    assert second.json()["elements"][0]["x"] == 500


def test_a_table_taken_off_the_plan_is_deactivated_not_deleted(
    auth_client: TestClient, tenant_id: str
) -> None:
    """Its past orders still have to resolve, so the row stays and stops being active."""
    first = auth_client.put(
        f"/api/v1/tenants/{tenant_id}/floor-plan",
        json=_plan(_table("el-a1", "A1"), _table("el-a2", "A2", x=300)),
    ).json()
    retired = next(t["id"] for t in first["tables"] if t["label"] == "A2")

    second = auth_client.put(
        f"/api/v1/tenants/{tenant_id}/floor-plan", json=_plan(_table("el-a1", "A1"))
    ).json()

    assert [t["label"] for t in second["tables"]] == ["A1"]
    # Put it back: the same row comes home, so the printed QR code still works.
    third = auth_client.put(
        f"/api/v1/tenants/{tenant_id}/floor-plan",
        json=_plan(_table("el-a1", "A1"), _table("el-new", "A2", x=300)),
    ).json()
    assert next(t["id"] for t in third["tables"] if t["label"] == "A2") == retired


def test_two_tables_cannot_share_a_name(auth_client: TestClient, tenant_id: str) -> None:
    """A diner has to be able to say which table they are at."""
    response = auth_client.put(
        f"/api/v1/tenants/{tenant_id}/floor-plan",
        json=_plan(_table("el-a1", "A1"), _table("el-a2", "a1", x=300)),
    )

    assert response.status_code == 400, response.text
    assert "own name" in response.json()["detail"]


def test_a_table_element_without_a_name_is_refused(auth_client: TestClient, tenant_id: str) -> None:
    """Naming is the whole point of a table: it is how the order finds its way back."""
    response = auth_client.put(
        f"/api/v1/tenants/{tenant_id}/floor-plan", json=_plan(_table("el-a1", ""))
    )

    assert response.status_code == 422, response.text


def test_an_element_outside_the_canvas_is_refused(auth_client: TestClient, tenant_id: str) -> None:
    """Geometry is tenant-authored data; nothing may be drawn off the floor."""
    response = auth_client.put(
        f"/api/v1/tenants/{tenant_id}/floor-plan",
        json=_plan(_table("el-a1", "A1", x=1180)),
    )

    assert response.status_code == 422, response.text


def test_a_text_element_cannot_carry_table_details(auth_client: TestClient, tenant_id: str) -> None:
    """Only a table is orderable; a caption that claimed a seat count would be a lie."""
    response = auth_client.put(
        f"/api/v1/tenants/{tenant_id}/floor-plan",
        json=_plan(
            {
                "id": "el-text",
                "kind": "text",
                "text": "Terrace",
                "label": "A1",
                "seats": 4,
                "x": 40,
                "y": 16,
                "width": 160,
                "height": 32,
            }
        ),
    )

    assert response.status_code == 422, response.text


def test_two_elements_cannot_share_an_id(auth_client: TestClient, tenant_id: str) -> None:
    """Ids are the editor's, and are how a save is matched to what is on screen."""
    response = auth_client.put(
        f"/api/v1/tenants/{tenant_id}/floor-plan",
        json=_plan(_table("el-a1", "A1"), _table("el-a1", "A2", x=300)),
    )

    assert response.status_code == 422, response.text


def test_an_empty_plan_retires_every_table(auth_client: TestClient, tenant_id: str) -> None:
    """Clearing the floor is allowed; it just takes every table off it."""
    auth_client.put(f"/api/v1/tenants/{tenant_id}/floor-plan", json=_plan(_table("el-a1", "A1")))

    response = auth_client.put(f"/api/v1/tenants/{tenant_id}/floor-plan", json=_plan())

    assert response.status_code == 200, response.text
    assert response.json()["tables"] == []


# ----------------------------------------------------------------------------- access


def test_staff_can_read_the_plan_but_not_change_it(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    """A server needs to know which table is which; rearranging the room is the owner's job."""
    invite = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/invites", json={"email": STAFF_EMAIL, "role": "staff"}
    )
    assert invite.status_code == 201, invite.text
    auth_client.put(f"/api/v1/tenants/{tenant_id}/floor-plan", json=_plan(_table("el-a1", "A1")))
    _as(auth_client, sign_in, STAFF_EMAIL)

    assert auth_client.get(f"/api/v1/tenants/{tenant_id}/floor-plan").status_code == 200
    refused = auth_client.put(
        f"/api/v1/tenants/{tenant_id}/floor-plan", json=_plan(_table("el-a1", "B1"))
    )
    assert refused.status_code == 403, refused.text


def test_an_outsider_sees_nothing(auth_client: TestClient, sign_in: SignIn, tenant_id: str) -> None:
    """Membership, not the id in the URL, is what grants a look at someone's floor."""
    _as(auth_client, sign_in, OUTSIDER_EMAIL)

    assert auth_client.get(f"/api/v1/tenants/{tenant_id}/floor-plan").status_code == 403


def test_a_platform_admin_can_save_a_plan(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    """Admins hold no membership, so this is the path that ``assert_can_manage_tenant`` covers."""
    _as(auth_client, sign_in, ADMIN_EMAIL)

    response = auth_client.put(
        f"/api/v1/tenants/{tenant_id}/floor-plan", json=_plan(_table("el-a1", "A1"))
    )

    assert response.status_code == 200, response.text


def test_signing_out_closes_the_plan(auth_client: TestClient, tenant_id: str) -> None:
    """No session, no floor."""
    auth_client.cookies.clear()

    assert auth_client.get(f"/api/v1/tenants/{tenant_id}/floor-plan").status_code == 401


def test_renaming_one_table_while_adding_its_old_name_keeps_them_apart(
    auth_client: TestClient, tenant_id: str
) -> None:
    """The auto-namer hands out a name a rename has just freed; both must stay real tables."""
    first = auth_client.put(
        f"/api/v1/tenants/{tenant_id}/floor-plan", json=_plan(_table("el-a1", "A1"))
    ).json()
    original = first["tables"][0]["id"]

    second = auth_client.put(
        f"/api/v1/tenants/{tenant_id}/floor-plan",
        json=_plan(
            _table("el-a1", "B1", table_id=original),
            _table("el-new", "A1", x=300),
        ),
    )

    assert second.status_code == 200, second.text
    body = second.json()
    assert {t["label"] for t in body["tables"]} == {"A1", "B1"}
    ids = [e["table_id"] for e in body["elements"]]
    assert len(set(ids)) == 2, ids
    assert next(t["id"] for t in body["tables"] if t["label"] == "B1") == original


def test_one_table_cannot_be_drawn_twice(auth_client: TestClient, tenant_id: str) -> None:
    """A table answering to two places on the floor is a lost table, not a layout choice."""
    first = auth_client.put(
        f"/api/v1/tenants/{tenant_id}/floor-plan", json=_plan(_table("el-a1", "A1"))
    ).json()
    table_id = first["tables"][0]["id"]

    response = auth_client.put(
        f"/api/v1/tenants/{tenant_id}/floor-plan",
        json=_plan(
            _table("el-a1", "A1", table_id=table_id),
            _table("el-a2", "A2", x=300, table_id=table_id),
        ),
    )

    assert response.status_code == 422, response.text
