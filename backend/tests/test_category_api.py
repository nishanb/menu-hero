"""Menu categories: naming, ordering, hiding and removing the sections of a menu.

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


@pytest.fixture
def tenant_id(auth_client: TestClient, sign_in: SignIn) -> str:
    """A restaurant owned by ``OWNER_EMAIL``, who is left signed in."""
    _as(auth_client, sign_in, OWNER_EMAIL)
    response = auth_client.post("/api/v1/tenants", json={"name": "Spice Garden"})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


def _add(client: TestClient, tenant_id: str, name: str, **extra: Any) -> dict[str, Any]:
    response = client.post(f"/api/v1/tenants/{tenant_id}/categories", json={"name": name, **extra})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


# ----------------------------------------------------------------------------- creating


def test_a_new_category_lands_at_the_bottom(auth_client: TestClient, tenant_id: str) -> None:
    """A section someone has just thought of belongs after the ones already there."""
    assert _add(auth_client, tenant_id, "Starters")["rank"] == 0
    assert _add(auth_client, tenant_id, "Mains")["rank"] == 1
    assert _add(auth_client, tenant_id, "Desserts")["rank"] == 2


def test_a_category_is_active_unless_it_is_not(auth_client: TestClient, tenant_id: str) -> None:
    """Adding a section to a menu means putting it on the menu."""
    assert _add(auth_client, tenant_id, "Starters")["status"] == "active"
    assert _add(auth_client, tenant_id, "Off menu", status="hidden")["status"] == "hidden"


def test_a_rank_can_be_chosen_on_the_way_in(auth_client: TestClient, tenant_id: str) -> None:
    assert _add(auth_client, tenant_id, "Desserts", rank=9)["rank"] == 9


def test_a_blank_name_is_refused(auth_client: TestClient, tenant_id: str) -> None:
    """A heading nobody can read is not a heading.

    A 400 rather than a 422: whitespace passes the request schema's length check and is only
    caught once the model collapses it, so what comes back is the model's own sentence -
    which is the one worth showing the owner.
    """
    response = auth_client.post(f"/api/v1/tenants/{tenant_id}/categories", json={"name": "   "})

    assert response.status_code == 400, response.text
    assert "cannot be blank" in response.json()["detail"]


def test_two_categories_cannot_share_a_name(auth_client: TestClient, tenant_id: str) -> None:
    """Two sections called Starters is a mistake every time, whatever the casing."""
    _add(auth_client, tenant_id, "Starters")

    response = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/categories", json={"name": "  starters "}
    )

    assert response.status_code == 409, response.text
    assert "already has a category" in response.json()["detail"]


def test_two_restaurants_can_both_have_starters(auth_client: TestClient, tenant_id: str) -> None:
    """The uniqueness is per restaurant, not global."""
    _add(auth_client, tenant_id, "Starters")
    other = auth_client.post("/api/v1/tenants", json={"name": "Second Place"}).json()["id"]

    assert _add(auth_client, other, "Starters")["name"] == "Starters"


# ----------------------------------------------------------------------------- reading


def test_categories_come_back_in_reading_order(auth_client: TestClient, tenant_id: str) -> None:
    """Rank decides; the name breaks a tie so the order is stable, not arbitrary."""
    _add(auth_client, tenant_id, "Desserts", rank=2)
    _add(auth_client, tenant_id, "Starters", rank=0)
    _add(auth_client, tenant_id, "Sides", rank=1)
    _add(auth_client, tenant_id, "Drinks", rank=1)

    listed = auth_client.get(f"/api/v1/tenants/{tenant_id}/categories").json()["categories"]

    assert [c["name"] for c in listed] == ["Starters", "Drinks", "Sides", "Desserts"]


def test_hidden_categories_are_listed_too(auth_client: TestClient, tenant_id: str) -> None:
    """This is the owner's list, not the diner's menu: a hidden section is still theirs."""
    _add(auth_client, tenant_id, "Off menu", status="hidden")

    listed = auth_client.get(f"/api/v1/tenants/{tenant_id}/categories").json()["categories"]

    assert [c["status"] for c in listed] == ["hidden"]


# ----------------------------------------------------------------------------- editing


def test_a_category_can_be_renamed_reordered_and_hidden(
    auth_client: TestClient, tenant_id: str
) -> None:
    created = _add(auth_client, tenant_id, "Startres")

    response = auth_client.patch(
        f"/api/v1/tenants/{tenant_id}/categories/{created['id']}",
        json={"name": "Starters", "rank": 5, "status": "hidden"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Starters"
    assert response.json()["rank"] == 5
    assert response.json()["status"] == "hidden"


def test_a_rename_cannot_take_a_name_already_used(auth_client: TestClient, tenant_id: str) -> None:
    _add(auth_client, tenant_id, "Starters")
    mains = _add(auth_client, tenant_id, "Mains")

    response = auth_client.patch(
        f"/api/v1/tenants/{tenant_id}/categories/{mains['id']}", json={"name": "STARTERS"}
    )

    assert response.status_code == 409, response.text


def test_renaming_frees_the_old_name(auth_client: TestClient, tenant_id: str) -> None:
    """The uniqueness key has to move with the name, or the old one stays taken forever."""
    starters = _add(auth_client, tenant_id, "Starters")
    auth_client.patch(
        f"/api/v1/tenants/{tenant_id}/categories/{starters['id']}", json={"name": "Small plates"}
    )

    assert _add(auth_client, tenant_id, "Starters")["name"] == "Starters"


def test_a_category_of_another_restaurant_is_not_found(
    auth_client: TestClient, tenant_id: str
) -> None:
    """The tenant is checked as well as the id, so an id cannot be edited across the boundary."""
    mine = _add(auth_client, tenant_id, "Starters")
    other = auth_client.post("/api/v1/tenants", json={"name": "Second Place"}).json()["id"]

    response = auth_client.patch(
        f"/api/v1/tenants/{other}/categories/{mine['id']}", json={"name": "Stolen"}
    )

    assert response.status_code == 404, response.text


# ----------------------------------------------------------------------------- removing


def test_a_category_can_be_removed(auth_client: TestClient, tenant_id: str) -> None:
    created = _add(auth_client, tenant_id, "Starters")

    removed = auth_client.delete(f"/api/v1/tenants/{tenant_id}/categories/{created['id']}")

    assert removed.status_code == 204, removed.text
    listed = auth_client.get(f"/api/v1/tenants/{tenant_id}/categories").json()["categories"]
    assert listed == []


def test_removing_a_category_twice_is_a_404(auth_client: TestClient, tenant_id: str) -> None:
    created = _add(auth_client, tenant_id, "Starters")
    auth_client.delete(f"/api/v1/tenants/{tenant_id}/categories/{created['id']}")

    again = auth_client.delete(f"/api/v1/tenants/{tenant_id}/categories/{created['id']}")

    assert again.status_code == 404, again.text


# ----------------------------------------------------------------------------- access


def test_staff_can_read_the_categories_but_not_change_them(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    """A server needs to know how the menu is organised; naming the sections is not their job."""
    invite = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/invites", json={"email": STAFF_EMAIL, "role": "staff"}
    )
    assert invite.status_code == 201, invite.text
    _add(auth_client, tenant_id, "Starters")
    _as(auth_client, sign_in, STAFF_EMAIL)

    assert auth_client.get(f"/api/v1/tenants/{tenant_id}/categories").status_code == 200
    refused = auth_client.post(f"/api/v1/tenants/{tenant_id}/categories", json={"name": "Mine now"})
    assert refused.status_code == 403, refused.text


def test_an_outsider_sees_nothing(auth_client: TestClient, sign_in: SignIn, tenant_id: str) -> None:
    _as(auth_client, sign_in, OUTSIDER_EMAIL)

    assert auth_client.get(f"/api/v1/tenants/{tenant_id}/categories").status_code == 403


def test_a_platform_admin_can_manage_categories(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    """Admins hold no membership, so this is the path ``assert_can_manage_tenant`` covers."""
    _as(auth_client, sign_in, ADMIN_EMAIL)

    assert _add(auth_client, tenant_id, "Starters")["name"] == "Starters"


def test_signing_out_closes_the_list(auth_client: TestClient, tenant_id: str) -> None:
    auth_client.cookies.clear()

    assert auth_client.get(f"/api/v1/tenants/{tenant_id}/categories").status_code == 401
