"""Menu items by hand: adding, editing and removing a dish.

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


def _as(client: TestClient, sign_in: SignIn, email: str) -> None:
    client.cookies.clear()
    response = sign_in(email)
    assert response.status_code == 302, response.text


@pytest.fixture
def tenant_id(auth_client: TestClient, sign_in: SignIn) -> str:
    """A restaurant owned by ``OWNER_EMAIL``, who is left signed in."""
    _as(auth_client, sign_in, OWNER_EMAIL)
    response = auth_client.post("/api/v1/tenants", json={"name": "Spice Garden"})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _add(client: TestClient, tenant_id: str, **fields: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"name": "Neer Dosa", "category": "Breakfast", "price": 60, **fields}
    response = client.post(f"/api/v1/tenants/{tenant_id}/menu/items", json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


# ----------------------------------------------------------------------------- creating


def test_a_dish_can_be_added_by_hand(auth_client: TestClient, tenant_id: str) -> None:
    """Not every restaurant has an export to import."""
    created = _add(auth_client, tenant_id, diet="veg")

    assert created["name"] == "Neer Dosa"
    assert created["price"] == 60
    assert created["price_from"] == 60
    assert created["is_available"] is True


def test_the_form_fields_all_come_back(auth_client: TestClient, tenant_id: str) -> None:
    """Everything the item form collects has to survive a round trip, or it is decoration."""
    created = _add(
        auth_client,
        tenant_id,
        online_name="Neerdosa",
        short_code="ND",
        short_code_2="ND2",
        hsn_code="2106",
        diet="veg",
        packing_charges=5,
        profit_margin=42.5,
        weight=250,
        weight_unit="g",
        gst_type="services",
        order_types=["pickup", "dine-in"],
        expose_in=["captain-app"],
        allow_decimal_quantity=False,
        manufactured_on="2026-09-01T00:00:00Z",
        expires_on="2026-09-30T00:00:00Z",
    )

    assert created["short_code_2"] == "ND2"
    assert created["profit_margin"] == 42.5
    assert (created["weight"], created["weight_unit"]) == (250, "g")
    assert created["gst_type"] == "services"
    assert created["order_types"] == ["pickup", "dine-in"]
    assert created["expose_in"] == ["captain-app"]
    assert created["allow_decimal_quantity"] is False
    assert created["manufactured_on"].startswith("2026-09-01")


def test_a_dish_needs_a_name(auth_client: TestClient, tenant_id: str) -> None:
    response = auth_client.post(f"/api/v1/tenants/{tenant_id}/menu/items", json={"name": "  "})

    assert response.status_code == 400, response.text


def test_an_order_type_outside_the_set_is_refused(auth_client: TestClient, tenant_id: str) -> None:
    """Closed on purpose: each one is a different price and tax treatment."""
    response = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/menu/items",
        json={"name": "Neer Dosa", "order_types": ["telepathy"]},
    )

    assert response.status_code == 400, response.text
    assert "order type" in response.json()["detail"]


def test_an_image_that_is_not_a_url_is_refused(auth_client: TestClient, tenant_id: str) -> None:
    """The field is rendered as an ``<img src>``; a javascript: value would be stored XSS."""
    response = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/menu/items",
        json={"name": "Neer Dosa", "image_url": "javascript:alert(1)"},
    )

    assert response.status_code == 400, response.text


# ----------------------------------------------------------------------------- editing


def test_a_dish_can_be_edited(auth_client: TestClient, tenant_id: str) -> None:
    created = _add(auth_client, tenant_id)

    response = auth_client.patch(
        f"/api/v1/tenants/{tenant_id}/menu/items/{created['id']}",
        json={"price": 79, "is_available": False},
    )

    assert response.status_code == 200, response.text
    assert response.json()["price"] == 79
    assert response.json()["is_available"] is False
    assert response.json()["name"] == "Neer Dosa"  # untouched


def test_a_patch_cannot_smuggle_past_the_validators(
    auth_client: TestClient, tenant_id: str
) -> None:
    """The merged document is re-validated, so a patch is held to the create's standard."""
    created = _add(auth_client, tenant_id)

    response = auth_client.patch(
        f"/api/v1/tenants/{tenant_id}/menu/items/{created['id']}",
        json={"weight_unit": "furlongs"},
    )

    assert response.status_code == 400, response.text


def test_a_dish_of_another_restaurant_is_not_found(auth_client: TestClient, tenant_id: str) -> None:
    """The tenant is checked as well as the id, so an id cannot cross the boundary."""
    mine = _add(auth_client, tenant_id)
    other = auth_client.post("/api/v1/tenants", json={"name": "Second Place"}).json()["id"]

    response = auth_client.patch(
        f"/api/v1/tenants/{other}/menu/items/{mine['id']}", json={"price": 1}
    )

    assert response.status_code == 404, response.text


# ----------------------------------------------------------------------------- removing


def test_a_dish_can_be_removed(auth_client: TestClient, tenant_id: str) -> None:
    created = _add(auth_client, tenant_id)

    removed = auth_client.delete(f"/api/v1/tenants/{tenant_id}/menu/items/{created['id']}")

    assert removed.status_code == 204, removed.text
    assert auth_client.get(f"/api/v1/tenants/{tenant_id}/menu/items").json()["total"] == 0


# ----------------------------------------------------------------------------- options


def test_the_form_is_told_what_the_validators_accept(
    auth_client: TestClient, tenant_id: str
) -> None:
    """Served rather than repeated in the UI, so the two cannot drift apart."""
    response = auth_client.get(f"/api/v1/tenants/{tenant_id}/menu/options")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["order_types"] == ["delivery", "pickup", "dine-in"]
    assert body["gst_types"] == ["services", "goods"]
    assert "veg" in body["diets"]
    assert "g" in body["weight_units"]


# ----------------------------------------------------------------------------- access


def test_staff_can_read_but_not_change(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    invite = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/invites", json={"email": STAFF_EMAIL, "role": "staff"}
    )
    assert invite.status_code == 201, invite.text
    created = _add(auth_client, tenant_id)
    _as(auth_client, sign_in, STAFF_EMAIL)

    assert auth_client.get(f"/api/v1/tenants/{tenant_id}/menu/items").status_code == 200
    refused = auth_client.patch(
        f"/api/v1/tenants/{tenant_id}/menu/items/{created['id']}", json={"price": 1}
    )
    assert refused.status_code == 403, refused.text


def test_a_platform_admin_can_edit(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    _as(auth_client, sign_in, ADMIN_EMAIL)

    assert _add(auth_client, tenant_id)["name"] == "Neer Dosa"


# ----------------------------------------------------------------------------- on / off


def test_a_whole_section_can_be_switched_off(auth_client: TestClient, tenant_id: str) -> None:
    """One decision, one round trip: a section of a real menu runs to 28 dishes."""
    _add(auth_client, tenant_id, name="Neer Dosa", category="Breakfast")
    _add(auth_client, tenant_id, name="Set Dosa", category="Breakfast")
    _add(auth_client, tenant_id, name="Filter Coffee", category="Beverages")

    response = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/menu/availability",
        json={"category": "Breakfast", "on": False},
    )

    assert response.status_code == 200, response.text
    assert response.json()["changed"] == 2
    items = auth_client.get(f"/api/v1/tenants/{tenant_id}/menu/items").json()["items"]
    off = {item["name"] for item in items if not item["is_available"]}
    assert off == {"Neer Dosa", "Set Dosa"}


def test_named_dishes_can_be_switched(auth_client: TestClient, tenant_id: str) -> None:
    first = _add(auth_client, tenant_id, name="Neer Dosa")
    second = _add(auth_client, tenant_id, name="Set Dosa")

    response = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/menu/availability",
        json={"item_ids": [first["id"], second["id"]], "on": False},
    )

    assert response.json()["changed"] == 2


def test_switching_something_already_off_changes_nothing(
    auth_client: TestClient, tenant_id: str
) -> None:
    """Zero is a normal answer, not a failure - it was already like that."""
    created = _add(auth_client, tenant_id, name="Neer Dosa")
    auth_client.post(
        f"/api/v1/tenants/{tenant_id}/menu/availability",
        json={"item_ids": [created["id"]], "on": False},
    )

    again = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/menu/availability",
        json={"item_ids": [created["id"]], "on": False},
    )

    assert again.status_code == 200, again.text
    assert again.json()["changed"] == 0


def test_a_dish_from_another_restaurant_is_not_switched(
    auth_client: TestClient, tenant_id: str
) -> None:
    """The tenant is part of the filter, not just the ids."""
    mine = _add(auth_client, tenant_id, name="Neer Dosa")
    other = auth_client.post("/api/v1/tenants", json={"name": "Second Place"}).json()["id"]

    response = auth_client.post(
        f"/api/v1/tenants/{other}/menu/availability",
        json={"item_ids": [mine["id"]], "on": False},
    )

    assert response.json()["changed"] == 0
    items = auth_client.get(f"/api/v1/tenants/{tenant_id}/menu/items").json()["items"]
    assert items[0]["is_available"] is True


def test_switching_nothing_in_particular_is_refused(
    auth_client: TestClient, tenant_id: str
) -> None:
    """Without a target this would silently switch the whole menu."""
    response = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/menu/availability", json={"on": False}
    )

    assert response.status_code == 400, response.text


def test_staff_cannot_switch_dishes(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    invite = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/invites", json={"email": STAFF_EMAIL, "role": "staff"}
    )
    assert invite.status_code == 201, invite.text
    _as(auth_client, sign_in, STAFF_EMAIL)

    response = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/menu/availability",
        json={"category": "Breakfast", "on": False},
    )

    assert response.status_code == 403, response.text
