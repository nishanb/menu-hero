"""The management flow: tenants, platform roles, invites and team membership.

These talk to a real MongoDB through the app and skip when none is reachable (see
``tests/conftest.py``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import ADMIN_EMAIL, TEST_DATABASE_NAME, TEST_MONGODB_URL, SignIn
from fastapi.testclient import TestClient
from pymongo import AsyncMongoClient

SESSION_COOKIE = "mh_session"
OWNER_EMAIL = "owner@example.com"
STAFF_EMAIL = "server@example.com"


def _as(client: TestClient, sign_in: SignIn, email: str) -> None:
    """Become ``email`` in this browser (a fresh cookie jar, then a full sign-in)."""
    client.cookies.clear()
    response = sign_in(email)
    assert response.status_code == 302, response.text


@pytest.fixture
def tenant_id(auth_client: TestClient, sign_in: SignIn) -> str:
    """A restaurant created by the admin, with ``OWNER_EMAIL`` already signed up as owner."""
    _as(auth_client, sign_in, OWNER_EMAIL)  # the owner must exist to be seeded as one
    _as(auth_client, sign_in, ADMIN_EMAIL)
    response = auth_client.post(
        "/api/v1/tenants", json={"name": "Spice Garden", "owner_email": OWNER_EMAIL}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


# ----------------------------------------------------------------------------- tenants


def test_anyone_signed_in_can_create_a_restaurant_and_owns_it(
    auth_client: TestClient, sign_in: SignIn
) -> None:
    """Self-serve onboarding: someone who belongs to nothing creates their first restaurant."""
    _as(auth_client, sign_in, "nobody@example.com")

    response = auth_client.post("/api/v1/tenants", json={"name": "Cafe One"})

    assert response.status_code == 201, response.text
    assert response.json()["slug"] == "cafe-one"
    me = auth_client.get("/api/v1/auth/me").json()
    assert [m["role"] for m in me["memberships"]] == ["owner"]
    assert me["active_tenant_id"] == response.json()["id"]


def test_a_non_admin_cannot_create_a_restaurant_for_someone_else(
    auth_client: TestClient, sign_in: SignIn
) -> None:
    """``owner_email`` is admin-only; for anyone else the caller owns what they create."""
    _as(auth_client, sign_in, OWNER_EMAIL)
    _as(auth_client, sign_in, "opportunist@example.com")

    response = auth_client.post(
        "/api/v1/tenants", json={"name": "Not Yours", "owner_email": OWNER_EMAIL}
    )

    assert response.status_code == 201, response.text
    tenant_id = response.json()["id"]
    members = auth_client.get(f"/api/v1/tenants/{tenant_id}/members").json()["members"]
    assert [(m["user"]["email"], m["role"]) for m in members] == [
        ("opportunist@example.com", "owner")
    ]


def test_the_onboarding_profile_round_trips(auth_client: TestClient, sign_in: SignIn) -> None:
    """Every field onboarding collects survives a create and comes back on the detail read."""
    _as(auth_client, sign_in, OWNER_EMAIL)
    logo = "data:image/png;base64,iVBORw0KGgo="

    created = auth_client.post(
        "/api/v1/tenants",
        json={
            "name": "Spice Garden",
            "description": "Coastal Karnataka home cooking.",
            "location_url": "https://maps.app.goo.gl/example",
            "logo": logo,
            "services": ["Dining", "delivery", "dining"],
            "diet_options": ["veg", "non-veg", "jain"],
            "extras": {"FSSAI Licence": "12345678901234", "gst_number": "29ABCDE1234F1Z5"},
        },
    )

    assert created.status_code == 201, created.text
    tenant = auth_client.get(f"/api/v1/tenants/{created.json()['id']}").json()
    assert tenant["description"] == "Coastal Karnataka home cooking."
    assert tenant["logo"] == logo
    # Lower-cased and de-duplicated, and the key is normalised to a storable field name.
    assert tenant["services"] == ["dining", "delivery"]
    assert tenant["diet_options"] == ["veg", "non-veg", "jain"]
    assert tenant["extras"]["fssai_licence"] == "12345678901234"


def test_a_logo_that_is_not_an_image_data_url_is_refused(
    auth_client: TestClient, sign_in: SignIn
) -> None:
    """SVG and remote URLs are stored-XSS vectors; only raster data URLs are accepted."""
    _as(auth_client, sign_in, OWNER_EMAIL)

    response = auth_client.post(
        "/api/v1/tenants",
        json={"name": "Sneaky", "logo": "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4="},
    )

    assert response.status_code == 400
    assert "PNG, JPEG or WEBP" in response.json()["detail"]


def test_a_location_that_is_not_https_is_refused(auth_client: TestClient, sign_in: SignIn) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)

    response = auth_client.post(
        "/api/v1/tenants", json={"name": "Sneaky Two", "location_url": "javascript:alert(1)"}
    )

    assert response.status_code == 400
    assert "https://" in response.json()["detail"]


def test_an_owner_edits_the_profile_and_the_slug_stays_put(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)

    patched = auth_client.patch(
        f"/api/v1/tenants/{tenant_id}",
        json={"description": "Now open Sundays.", "slug": "hijacked", "services": ["delivery"]},
    )

    assert patched.status_code == 200, patched.text
    assert patched.json()["description"] == "Now open Sundays."
    assert patched.json()["services"] == ["delivery"]
    assert patched.json()["slug"] == "spice-garden"
    assert patched.json()["name"] == "Spice Garden"  # untouched fields are left alone


def test_staff_cannot_edit_the_restaurant(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)
    _invite(auth_client, tenant_id, STAFF_EMAIL)
    _as(auth_client, sign_in, STAFF_EMAIL)

    response = auth_client.patch(f"/api/v1/tenants/{tenant_id}", json={"name": "Mine Now"})

    assert response.status_code == 403


def test_creating_a_tenant_makes_the_named_owner_an_owner(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)

    me = auth_client.get("/api/v1/auth/me").json()

    assert me["effective_role"] == "owner"
    assert me["portal_path"] == "/owner"
    assert me["memberships"] == [
        {
            "tenant_id": tenant_id,
            "tenant_slug": "spice-garden",
            "tenant_name": "Spice Garden",
            "role": "owner",
        }
    ]


def test_a_repeated_name_gets_a_slug_of_its_own(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    """Two restaurants may share a name; the server finds each a free handle."""
    _as(auth_client, sign_in, "second-owner@example.com")

    response = auth_client.post("/api/v1/tenants", json={"name": "Spice Garden"})

    assert response.status_code == 201, response.text
    assert response.json()["slug"] == "spice-garden-2"


def test_a_name_with_no_latin_letters_still_gets_a_usable_slug(
    auth_client: TestClient, sign_in: SignIn
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)

    response = auth_client.post("/api/v1/tenants", json={"name": "ಮಸಾಲೆ ತೋಟ"})

    assert response.status_code == 201, response.text
    assert response.json()["slug"] == "restaurant"


# ------------------------------------------------------------------- the current restaurant


def test_the_last_restaurant_switched_to_is_remembered(
    auth_client: TestClient, sign_in: SignIn
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)
    first = auth_client.post("/api/v1/tenants", json={"name": "Alpha"}).json()["id"]
    second = auth_client.post("/api/v1/tenants", json={"name": "Beta"}).json()["id"]

    assert auth_client.put(f"/api/v1/tenants/{first}/current").status_code == 200

    # A fresh sign-in is a fresh session, so this proves the choice outlived the cookie.
    _as(auth_client, sign_in, OWNER_EMAIL)
    assert auth_client.get("/api/v1/auth/me").json()["active_tenant_id"] == first
    assert auth_client.get("/api/v1/tenants").json()["active_tenant_id"] == first
    assert second != first


def test_a_remembered_restaurant_you_no_longer_belong_to_is_not_used(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    """``last_tenant_id`` is a preference, never a grant: a revoked membership drops it."""
    _as(auth_client, sign_in, OWNER_EMAIL)
    _invite(auth_client, tenant_id, STAFF_EMAIL)
    _as(auth_client, sign_in, STAFF_EMAIL)
    staff_id = auth_client.get("/api/v1/auth/me").json()["user"]["id"]
    assert auth_client.put(f"/api/v1/tenants/{tenant_id}/current").status_code == 200

    _as(auth_client, sign_in, OWNER_EMAIL)
    assert auth_client.delete(f"/api/v1/tenants/{tenant_id}/members/{staff_id}").status_code == 204

    _as(auth_client, sign_in, STAFF_EMAIL)
    me = auth_client.get("/api/v1/auth/me").json()
    assert me["memberships"] == []
    assert me["active_tenant_id"] is None


def test_being_removed_from_one_restaurant_keeps_the_others_remembered(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    """Only the restaurant they left is forgotten, not whichever one they had chosen."""
    _as(auth_client, sign_in, STAFF_EMAIL)
    own = auth_client.post("/api/v1/tenants", json={"name": "Their Own Place"}).json()["id"]
    staff_id = auth_client.get("/api/v1/auth/me").json()["user"]["id"]

    _as(auth_client, sign_in, OWNER_EMAIL)
    _invite(auth_client, tenant_id, STAFF_EMAIL)
    _as(auth_client, sign_in, STAFF_EMAIL)  # signing in consumes the invite
    assert auth_client.put(f"/api/v1/tenants/{own}/current").status_code == 200

    _as(auth_client, sign_in, OWNER_EMAIL)
    assert auth_client.delete(f"/api/v1/tenants/{tenant_id}/members/{staff_id}").status_code == 204

    _as(auth_client, sign_in, STAFF_EMAIL)
    assert auth_client.get("/api/v1/auth/me").json()["active_tenant_id"] == own


def test_a_name_with_accents_gets_the_slug_the_form_previewed(
    auth_client: TestClient, sign_in: SignIn
) -> None:
    """The backend folds accents exactly as the frontend's preview does."""
    _as(auth_client, sign_in, OWNER_EMAIL)

    response = auth_client.post("/api/v1/tenants", json={"name": "Café Móka"})

    assert response.status_code == 201, response.text
    assert response.json()["slug"] == "cafe-moka"


def test_a_non_member_cannot_switch_to_a_restaurant(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    _as(auth_client, sign_in, "outsider@example.com")
    assert auth_client.put(f"/api/v1/tenants/{tenant_id}/current").status_code == 403


def test_the_options_endpoint_offers_suggestions_not_a_closed_set(
    auth_client: TestClient, sign_in: SignIn
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)

    options = auth_client.get("/api/v1/tenants/options").json()

    assert "dining" in options["services"] and "delivery" in options["services"]
    assert "veg" in options["diet_options"] and "non-veg" in options["diet_options"]
    accepted = auth_client.post(
        "/api/v1/tenants", json={"name": "Novel", "diet_options": ["pescatarian"]}
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["diet_options"] == ["pescatarian"]


def test_listing_tenants_shows_only_your_own(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    _as(auth_client, sign_in, "outsider@example.com")
    assert auth_client.get("/api/v1/tenants").json()["tenants"] == []

    _as(auth_client, sign_in, OWNER_EMAIL)
    mine = auth_client.get("/api/v1/tenants").json()["tenants"]
    assert [t["slug"] for t in mine] == ["spice-garden"]


def test_a_non_member_cannot_read_a_tenant(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    _as(auth_client, sign_in, "outsider@example.com")
    response = auth_client.get(f"/api/v1/tenants/{tenant_id}")
    assert response.status_code == 403


def test_endpoints_require_a_session(auth_client: TestClient) -> None:
    assert auth_client.get("/api/v1/tenants").status_code == 401
    assert auth_client.get("/api/v1/users").status_code == 401


# ----------------------------------------------------------------------------- invites


async def _age_out_invites(email: str) -> None:
    """Expire every pending invite for ``email``, as the passage of time would.

    Its own client: the one the app uses belongs to the TestClient's event loop.
    """
    client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(TEST_MONGODB_URL)
    try:
        await client[TEST_DATABASE_NAME]["invites"].update_many(
            {"email": email, "accepted_at": None},
            {"$set": {"expires_at": datetime.now(UTC) - timedelta(days=1)}},
        )
    finally:
        await client.aclose()


def _invite(client: TestClient, tenant_id: str, email: str, role: str = "staff") -> dict[str, str]:
    response = client.post(
        f"/api/v1/tenants/{tenant_id}/invites", json={"email": email, "role": role}
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def test_an_owner_invites_and_the_invitee_becomes_staff_on_first_sign_in(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)
    created = _invite(auth_client, tenant_id, STAFF_EMAIL)
    assert created["token"] in created["accept_url"]

    _as(auth_client, sign_in, STAFF_EMAIL)
    me = auth_client.get("/api/v1/auth/me").json()

    assert me["effective_role"] == "staff"
    assert me["portal_path"] == "/staff"
    assert [m["role"] for m in me["memberships"]] == ["staff"]


def test_an_accepted_invite_stops_being_pending(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)
    _invite(auth_client, tenant_id, STAFF_EMAIL)
    _as(auth_client, sign_in, STAFF_EMAIL)

    _as(auth_client, sign_in, OWNER_EMAIL)
    pending = auth_client.get(f"/api/v1/tenants/{tenant_id}/invites").json()["invites"]
    assert pending == []


def test_a_signed_in_user_can_accept_an_invite_by_token(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    # The invite arrives while they are already signed in, so the sign-in callback never
    # sees it: keep their session cookie and come back to it instead of signing in again.
    _as(auth_client, sign_in, STAFF_EMAIL)
    staff_session = auth_client.cookies[SESSION_COOKIE]
    _as(auth_client, sign_in, OWNER_EMAIL)
    created = _invite(auth_client, tenant_id, STAFF_EMAIL)

    auth_client.cookies.clear()
    auth_client.cookies.set(SESSION_COOKIE, staff_session)
    accepted = auth_client.post("/api/v1/auth/invites/accept", json={"token": created["token"]})

    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["effective_role"] == "staff"
    assert [m["role"] for m in accepted.json()["memberships"]] == ["staff"]


def test_an_invite_cannot_be_redeemed_by_a_different_address(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)
    created = _invite(auth_client, tenant_id, STAFF_EMAIL)

    _as(auth_client, sign_in, "someone-else@example.com")
    response = auth_client.post("/api/v1/auth/invites/accept", json={"token": created["token"]})

    assert response.status_code == 400
    assert response.json()["detail"] == "This invite was sent to a different address"


def test_a_revoked_invite_stops_working(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)
    created = _invite(auth_client, tenant_id, STAFF_EMAIL)
    invite_id = created["invite"]["id"]  # type: ignore[index]

    revoked = auth_client.delete(f"/api/v1/tenants/{tenant_id}/invites/{invite_id}")

    assert revoked.status_code == 204
    _as(auth_client, sign_in, STAFF_EMAIL)
    assert auth_client.get("/api/v1/auth/me").json()["memberships"] == []


async def test_a_lapsed_invite_can_be_reissued(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    """The pending-invite uniqueness index must not lock an address out for ever."""
    _as(auth_client, sign_in, OWNER_EMAIL)
    _invite(auth_client, tenant_id, STAFF_EMAIL)
    await _age_out_invites(STAFF_EMAIL)

    response = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/invites", json={"email": STAFF_EMAIL, "role": "staff"}
    )

    assert response.status_code == 201, response.text
    pending = auth_client.get(f"/api/v1/tenants/{tenant_id}/invites").json()["invites"]
    assert [i["email"] for i in pending] == [STAFF_EMAIL]


def test_staff_cannot_invite_anyone(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)
    _invite(auth_client, tenant_id, STAFF_EMAIL)
    _as(auth_client, sign_in, STAFF_EMAIL)

    response = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/invites",
        json={"email": "another@example.com", "role": "staff"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Only an owner of this restaurant can manage its team"


def test_inviting_an_existing_member_is_refused(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)
    response = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/invites", json={"email": OWNER_EMAIL, "role": "staff"}
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "That person is already a member of this restaurant"


def test_a_second_pending_invite_for_the_same_address_is_refused(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)
    _invite(auth_client, tenant_id, STAFF_EMAIL)

    response = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/invites", json={"email": STAFF_EMAIL, "role": "staff"}
    )

    assert response.status_code == 409


# ----------------------------------------------------------------------------- team roles


def test_an_owner_promotes_staff_and_the_change_applies_at_once(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)
    _invite(auth_client, tenant_id, STAFF_EMAIL)
    _as(auth_client, sign_in, STAFF_EMAIL)
    staff_id = auth_client.get("/api/v1/auth/me").json()["user"]["id"]

    _as(auth_client, sign_in, OWNER_EMAIL)
    changed = auth_client.patch(
        f"/api/v1/tenants/{tenant_id}/members/{staff_id}", json={"role": "owner"}
    )

    assert changed.status_code == 200
    assert changed.json()["role"] == "owner"
    _as(auth_client, sign_in, STAFF_EMAIL)
    assert auth_client.get("/api/v1/auth/me").json()["effective_role"] == "owner"


def test_the_last_owner_cannot_be_demoted_or_removed(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)
    owner_id = auth_client.get("/api/v1/auth/me").json()["user"]["id"]

    demoted = auth_client.patch(
        f"/api/v1/tenants/{tenant_id}/members/{owner_id}", json={"role": "staff"}
    )
    removed = auth_client.delete(f"/api/v1/tenants/{tenant_id}/members/{owner_id}")

    assert demoted.status_code == 409
    assert removed.status_code == 409
    assert "last owner" in demoted.json()["detail"]


def test_removing_a_member_ends_their_role_immediately(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)
    _invite(auth_client, tenant_id, STAFF_EMAIL)
    _as(auth_client, sign_in, STAFF_EMAIL)
    staff_id = auth_client.get("/api/v1/auth/me").json()["user"]["id"]

    _as(auth_client, sign_in, OWNER_EMAIL)
    assert auth_client.delete(f"/api/v1/tenants/{tenant_id}/members/{staff_id}").status_code == 204

    _as(auth_client, sign_in, STAFF_EMAIL)
    me = auth_client.get("/api/v1/auth/me").json()
    assert me["memberships"] == []
    assert me["effective_role"] == "user"


def test_the_team_list_is_readable_by_members_only(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    _as(auth_client, sign_in, OWNER_EMAIL)
    members = auth_client.get(f"/api/v1/tenants/{tenant_id}/members").json()["members"]
    assert [(m["user"]["email"], m["role"]) for m in members] == [(OWNER_EMAIL, "owner")]

    _as(auth_client, sign_in, "outsider@example.com")
    assert auth_client.get(f"/api/v1/tenants/{tenant_id}/members").status_code == 403


# ----------------------------------------------------------------------------- platform roles


def test_an_admin_promotes_a_user_and_the_change_applies_at_once(
    auth_client: TestClient, sign_in: SignIn
) -> None:
    _as(auth_client, sign_in, "future-admin@example.com")
    user_id = auth_client.get("/api/v1/auth/me").json()["user"]["id"]

    _as(auth_client, sign_in, ADMIN_EMAIL)
    changed = auth_client.patch(f"/api/v1/users/{user_id}/role", json={"role": "admin"})

    assert changed.status_code == 200
    assert changed.json()["platform_role"] == "admin"
    _as(auth_client, sign_in, "future-admin@example.com")
    assert auth_client.get("/api/v1/auth/me").json()["effective_role"] == "admin"


def test_an_admin_cannot_demote_themselves(auth_client: TestClient, sign_in: SignIn) -> None:
    _as(auth_client, sign_in, ADMIN_EMAIL)
    admin_id = auth_client.get("/api/v1/auth/me").json()["user"]["id"]

    response = auth_client.patch(f"/api/v1/users/{admin_id}/role", json={"role": "user"})

    assert response.status_code == 403
    assert response.json()["detail"] == "You cannot change your own platform role"


def test_an_admin_can_demote_another_admin(auth_client: TestClient, sign_in: SignIn) -> None:
    _as(auth_client, sign_in, "second-admin@example.com")
    second_id = auth_client.get("/api/v1/auth/me").json()["user"]["id"]
    _as(auth_client, sign_in, ADMIN_EMAIL)
    assert (
        auth_client.patch(f"/api/v1/users/{second_id}/role", json={"role": "admin"}).status_code
        == 200
    )

    demoted = auth_client.patch(f"/api/v1/users/{second_id}/role", json={"role": "user"})

    assert demoted.status_code == 200
    assert demoted.json()["platform_role"] == "user"
    _as(auth_client, sign_in, "second-admin@example.com")
    assert auth_client.get("/api/v1/auth/me").json()["effective_role"] == "user"


def test_a_bootstrap_address_is_promoted_again_at_the_next_sign_in(
    auth_client: TestClient, sign_in: SignIn
) -> None:
    """The environment variable is the break-glass grant, so it outranks an API demotion."""
    _as(auth_client, sign_in, "second-admin@example.com")
    second_id = auth_client.get("/api/v1/auth/me").json()["user"]["id"]
    _as(auth_client, sign_in, ADMIN_EMAIL)
    admin_id = auth_client.get("/api/v1/auth/me").json()["user"]["id"]
    auth_client.patch(f"/api/v1/users/{second_id}/role", json={"role": "admin"})

    _as(auth_client, sign_in, "second-admin@example.com")
    assert (
        auth_client.patch(f"/api/v1/users/{admin_id}/role", json={"role": "user"}).status_code
        == 200
    )

    _as(auth_client, sign_in, ADMIN_EMAIL)
    assert auth_client.get("/api/v1/auth/me").json()["user"]["platform_role"] == "admin"


def test_a_plain_user_cannot_change_roles(auth_client: TestClient, sign_in: SignIn) -> None:
    _as(auth_client, sign_in, "nobody@example.com")
    user_id = auth_client.get("/api/v1/auth/me").json()["user"]["id"]

    response = auth_client.patch(f"/api/v1/users/{user_id}/role", json={"role": "admin"})

    assert response.status_code == 403
