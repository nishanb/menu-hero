"""The POS flow: seat a table, build the order, send tickets, bill, close.

These talk to a real MongoDB through the app and skip when none is reachable (see
``tests/conftest.py``).
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import SignIn
from fastapi.testclient import TestClient

OWNER_EMAIL = "owner@example.com"
STAFF_EMAIL = "server@example.com"
OUTSIDER_EMAIL = "stranger@example.com"


def _as(client: TestClient, sign_in: SignIn, email: str) -> None:
    client.cookies.clear()
    response = sign_in(email)
    assert response.status_code == 302, response.text


class Floor:
    """A restaurant with two tables and three dishes, ready to take an order."""

    def __init__(self, tenant_id: str, tables: dict[str, str], items: dict[str, str]) -> None:
        self.tenant_id = tenant_id
        self.tables = tables
        self.items = items


@pytest.fixture
def floor(auth_client: TestClient, sign_in: SignIn) -> Floor:
    _as(auth_client, sign_in, OWNER_EMAIL)
    tenant_id = auth_client.post("/api/v1/tenants", json={"name": "Spice Garden"}).json()["id"]

    plan = auth_client.put(
        f"/api/v1/tenants/{tenant_id}/floor-plan",
        json={
            "width": 1200,
            "height": 800,
            "elements": [
                {
                    "id": "e1",
                    "kind": "table",
                    "shape": "square",
                    "label": "A1",
                    "seats": 4,
                    "x": 40,
                    "y": 40,
                    "width": 90,
                    "height": 90,
                },
                {
                    "id": "e2",
                    "kind": "table",
                    "shape": "square",
                    "label": "A2",
                    "seats": 2,
                    "x": 200,
                    "y": 40,
                    "width": 90,
                    "height": 90,
                },
            ],
        },
    )
    assert plan.status_code == 200, plan.text
    tables = {table["label"]: table["id"] for table in plan.json()["tables"]}

    items: dict[str, str] = {}
    for body in (
        {"name": "Neer Dosa", "category": "Breakfast", "price": 60, "diet": "veg"},
        {
            "name": "Chicken Meals",
            "category": "Meals",
            "price": 0,
            "diet": "non-veg",
            "variations": [
                {"name": "Boiled Rice", "price": 249},
                {"name": "White Rice", "price": 259},
            ],
        },
        {"name": "Crab Curry", "category": "Sea Food", "price": 499, "is_available": False},
    ):
        created = auth_client.post(f"/api/v1/tenants/{tenant_id}/menu/items", json=body)
        assert created.status_code == 201, created.text
        items[body["name"]] = created.json()["id"]
    return Floor(tenant_id, tables, items)


def _open(
    client: TestClient, floor: Floor, table: str | None = "A1", **extra: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {**extra}
    if table:
        body["table_id"] = floor.tables[table]
    response = client.post(f"/api/v1/tenants/{floor.tenant_id}/orders", json=body)
    assert response.status_code == 201, response.text
    order: dict[str, Any] = response.json()
    return order


def _add(client: TestClient, floor: Floor, order_id: str, *lines: dict[str, Any]) -> Any:
    return client.post(
        f"/api/v1/tenants/{floor.tenant_id}/orders/{order_id}/lines", json={"lines": list(lines)}
    )


def _dosa(line_id: str = "l1", quantity: int = 1, floor: Floor | None = None) -> dict[str, Any]:
    assert floor is not None
    return {"id": line_id, "item_id": floor.items["Neer Dosa"], "quantity": quantity}


# ----------------------------------------------------------------------------- opening


def test_seating_a_table_opens_an_order_with_a_number(
    auth_client: TestClient, floor: Floor
) -> None:
    order = _open(auth_client, floor)

    assert order["number"] == 1
    assert order["kind"] == "dine-in"
    assert order["status"] == "open"
    assert order["table_label"] == "A1"
    assert order["lines"] == []


def test_seating_the_same_table_twice_returns_the_same_order(
    auth_client: TestClient, floor: Floor
) -> None:
    """Two servers tapping A1 at once is the ordinary case, not a second order."""
    first = _open(auth_client, floor)
    second = _open(auth_client, floor)

    assert second["id"] == first["id"]
    assert second["number"] == 1


def test_order_numbers_are_sequential(auth_client: TestClient, floor: Floor) -> None:
    assert _open(auth_client, floor, "A1")["number"] == 1
    assert _open(auth_client, floor, "A2")["number"] == 2
    assert _open(auth_client, floor, None, idempotency_key="t-1")["number"] == 3


def test_a_takeaway_bill_has_no_table_and_a_key_to_stop_double_taps(
    auth_client: TestClient, floor: Floor
) -> None:
    first = _open(auth_client, floor, None, idempotency_key="counter-abc")
    second = _open(auth_client, floor, None, idempotency_key="counter-abc")

    assert first["kind"] == "takeaway"
    assert first["table_id"] is None
    assert second["id"] == first["id"]


def test_a_table_not_on_the_floor_plan_cannot_be_seated(
    auth_client: TestClient, floor: Floor
) -> None:
    response = auth_client.post(
        f"/api/v1/tenants/{floor.tenant_id}/orders", json={"table_id": "665f1a2b3c4d5e6f7a8b9c0d"}
    )

    assert response.status_code == 404, response.text


# ----------------------------------------------------------------------------- lines


def test_lines_snapshot_the_menu_price(auth_client: TestClient, floor: Floor) -> None:
    """The bill says what the table was charged, not what the dish costs later."""
    order = _open(auth_client, floor)
    added = _add(auth_client, floor, order["id"], _dosa("l1", 2, floor))
    assert added.status_code == 200, added.text

    # Reprice the dish on the menu; the line must not move.
    auth_client.patch(
        f"/api/v1/tenants/{floor.tenant_id}/menu/items/{floor.items['Neer Dosa']}",
        json={"price": 999},
    )

    fetched = auth_client.get(f"/api/v1/tenants/{floor.tenant_id}/orders/{order['id']}").json()
    assert fetched["lines"][0]["unit_price"] == 60
    assert fetched["lines"][0]["total"] == 120
    assert fetched["subtotal"] == 120


def test_a_dish_with_variations_needs_one_chosen(auth_client: TestClient, floor: Floor) -> None:
    order = _open(auth_client, floor)

    refused = _add(
        auth_client, floor, order["id"], {"id": "l1", "item_id": floor.items["Chicken Meals"]}
    )
    assert refused.status_code == 400, refused.text
    assert "Choose how" in refused.json()["detail"]

    chosen = _add(
        auth_client,
        floor,
        order["id"],
        {"id": "l1", "item_id": floor.items["Chicken Meals"], "variation": "white rice"},
    )
    assert chosen.status_code == 200, chosen.text
    line = chosen.json()["lines"][0]
    assert line["variation"] == {"name": "White Rice", "price": 259}
    assert line["unit_price"] == 259


def test_a_dish_that_is_off_the_menu_is_refused(auth_client: TestClient, floor: Floor) -> None:
    """The kitchen has said it cannot make it; adding it silently would be a lie to the table."""
    order = _open(auth_client, floor)

    refused = _add(
        auth_client, floor, order["id"], {"id": "l1", "item_id": floor.items["Crab Curry"]}
    )

    assert refused.status_code == 409, refused.text
    assert "off the menu" in refused.json()["detail"]


def test_a_pending_line_can_be_changed_and_removed(auth_client: TestClient, floor: Floor) -> None:
    order = _open(auth_client, floor)
    _add(auth_client, floor, order["id"], _dosa("l1", 1, floor), _dosa("l2", 1, floor))
    base = f"/api/v1/tenants/{floor.tenant_id}/orders/{order['id']}/lines"

    changed = auth_client.patch(f"{base}/l1", json={"quantity": 3, "note": "less spicy"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["lines"][0]["quantity"] == 3
    assert changed.json()["lines"][0]["note"] == "less spicy"

    removed = auth_client.delete(f"{base}/l2")
    assert removed.status_code == 200, removed.text
    assert [line["id"] for line in removed.json()["lines"]] == ["l1"]


# ----------------------------------------------------------------------------- the kitchen


def test_sending_a_kot_stamps_the_pending_lines(auth_client: TestClient, floor: Floor) -> None:
    order = _open(auth_client, floor)
    _add(auth_client, floor, order["id"], _dosa("l1", 2, floor))
    base = f"/api/v1/tenants/{floor.tenant_id}/orders/{order['id']}"

    sent = auth_client.post(f"{base}/kot")

    assert sent.status_code == 201, sent.text
    kot = sent.json()
    assert kot["number"] == 1
    assert kot["order_number"] == 1
    assert kot["table_label"] == "A1"
    assert kot["lines"] == [
        {"line_id": "l1", "name": "Neer Dosa", "variation": "", "quantity": 2, "note": ""}
    ]

    after = auth_client.get(base).json()
    assert after["lines"][0]["kot_id"] == kot["id"]
    assert after["pending_count"] == 0
    assert after["kot_ids"] == [kot["id"]]


def test_a_second_round_gets_its_own_ticket(auth_client: TestClient, floor: Floor) -> None:
    """A table sends several tickets; each carries only what is new."""
    order = _open(auth_client, floor)
    base = f"/api/v1/tenants/{floor.tenant_id}/orders/{order['id']}"
    _add(auth_client, floor, order["id"], _dosa("l1", 1, floor))
    first = auth_client.post(f"{base}/kot").json()
    _add(auth_client, floor, order["id"], _dosa("l2", 4, floor))

    second = auth_client.post(f"{base}/kot").json()

    assert second["number"] == first["number"] + 1
    assert [line["line_id"] for line in second["lines"]] == ["l2"]
    kots = auth_client.get(f"{base}/kots").json()["kots"]
    assert [kot["number"] for kot in kots] == [1, 2]


def test_a_kot_with_nothing_pending_is_refused(auth_client: TestClient, floor: Floor) -> None:
    order = _open(auth_client, floor)
    base = f"/api/v1/tenants/{floor.tenant_id}/orders/{order['id']}"
    _add(auth_client, floor, order["id"], _dosa("l1", 1, floor))
    auth_client.post(f"{base}/kot")

    again = auth_client.post(f"{base}/kot")

    assert again.status_code == 409, again.text


def test_a_sent_line_cannot_be_changed(auth_client: TestClient, floor: Floor) -> None:
    """Changing the record without changing the ticket is how kitchens get lied to."""
    order = _open(auth_client, floor)
    base = f"/api/v1/tenants/{floor.tenant_id}/orders/{order['id']}"
    _add(auth_client, floor, order["id"], _dosa("l1", 1, floor))
    auth_client.post(f"{base}/kot")

    assert auth_client.patch(f"{base}/lines/l1", json={"quantity": 9}).status_code == 409
    assert auth_client.delete(f"{base}/lines/l1").status_code == 409


# ----------------------------------------------------------------------------- the counter


def test_the_bill_waits_for_the_kitchen(auth_client: TestClient, floor: Floor) -> None:
    """A bill for food the kitchen has not been asked to make is the mistake to prevent."""
    order = _open(auth_client, floor)
    base = f"/api/v1/tenants/{floor.tenant_id}/orders/{order['id']}"
    _add(auth_client, floor, order["id"], _dosa("l1", 1, floor))

    early = auth_client.post(f"{base}/bill")
    assert early.status_code == 409, early.text
    assert "pending" in early.json()["detail"]

    auth_client.post(f"{base}/kot")
    billed = auth_client.post(f"{base}/bill")
    assert billed.status_code == 200, billed.text
    assert billed.json()["status"] == "billed"
    assert billed.json()["total"] == 60


def test_an_empty_order_cannot_be_billed(auth_client: TestClient, floor: Floor) -> None:
    order = _open(auth_client, floor)

    response = auth_client.post(f"/api/v1/tenants/{floor.tenant_id}/orders/{order['id']}/bill")

    assert response.status_code == 409, response.text


def test_nothing_is_added_after_the_bill(auth_client: TestClient, floor: Floor) -> None:
    order = _open(auth_client, floor)
    base = f"/api/v1/tenants/{floor.tenant_id}/orders/{order['id']}"
    _add(auth_client, floor, order["id"], _dosa("l1", 1, floor))
    auth_client.post(f"{base}/kot")
    auth_client.post(f"{base}/bill")

    late = _add(auth_client, floor, order["id"], _dosa("l2", 1, floor))

    assert late.status_code == 409, late.text


def test_paying_closes_the_order_and_frees_the_table(auth_client: TestClient, floor: Floor) -> None:
    order = _open(auth_client, floor)
    base = f"/api/v1/tenants/{floor.tenant_id}/orders/{order['id']}"
    _add(auth_client, floor, order["id"], _dosa("l1", 1, floor))
    auth_client.post(f"{base}/kot")

    assert auth_client.post(f"{base}/close").status_code == 409  # not billed yet
    auth_client.post(f"{base}/bill")
    closed = auth_client.post(f"{base}/close")
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"

    # The table is free again: seating it opens a new order, not the old one.
    fresh = _open(auth_client, floor)
    assert fresh["id"] != order["id"]
    assert fresh["number"] == 2


def test_a_paid_order_cannot_be_cancelled(auth_client: TestClient, floor: Floor) -> None:
    order = _open(auth_client, floor)
    base = f"/api/v1/tenants/{floor.tenant_id}/orders/{order['id']}"
    _add(auth_client, floor, order["id"], _dosa("l1", 1, floor))
    auth_client.post(f"{base}/kot")
    auth_client.post(f"{base}/bill")
    auth_client.post(f"{base}/close")

    assert auth_client.post(f"{base}/cancel").status_code == 409


def test_an_open_order_can_be_cancelled(auth_client: TestClient, floor: Floor) -> None:
    order = _open(auth_client, floor)

    cancelled = auth_client.post(f"/api/v1/tenants/{floor.tenant_id}/orders/{order['id']}/cancel")

    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert _open(auth_client, floor)["id"] != order["id"]


# ----------------------------------------------------------------------------- the floor


def test_the_floor_lists_what_is_still_running(auth_client: TestClient, floor: Floor) -> None:
    a1 = _open(auth_client, floor, "A1")
    a2 = _open(auth_client, floor, "A2")
    base = f"/api/v1/tenants/{floor.tenant_id}/orders"
    _add(auth_client, floor, a2["id"], _dosa("l1", 1, floor))
    auth_client.post(f"{base}/{a2['id']}/kot")
    auth_client.post(f"{base}/{a2['id']}/bill")
    auth_client.post(f"{base}/{a2['id']}/close")

    active = auth_client.get(base).json()["orders"]
    recent = auth_client.get(base, params={"scope": "recent"}).json()["orders"]

    assert [order["id"] for order in active] == [a1["id"]]
    assert {order["id"] for order in recent} == {a1["id"], a2["id"]}


def test_the_kitchen_queue_is_what_nobody_has_seen_yet(
    auth_client: TestClient, floor: Floor
) -> None:
    """Oldest first; a paid order's tickets leave with it, an acknowledged ticket leaves alone."""
    a1 = _open(auth_client, floor, "A1")
    a2 = _open(auth_client, floor, "A2")
    base = f"/api/v1/tenants/{floor.tenant_id}/orders"
    for order in (a1, a2):
        _add(auth_client, floor, order["id"], _dosa("l1", 1, floor))
        auth_client.post(f"{base}/{order['id']}/kot")
    _add(auth_client, floor, a1["id"], _dosa("l2", 2, floor))
    third = auth_client.post(f"{base}/{a1['id']}/kot").json()
    auth_client.post(f"{base}/{a2['id']}/bill")
    auth_client.post(f"{base}/{a2['id']}/close")

    queue = auth_client.get(f"/api/v1/tenants/{floor.tenant_id}/kots")
    assert queue.status_code == 200, queue.text
    assert [kot["number"] for kot in queue.json()["kots"]] == [1, 3]

    auth_client.post(f"/api/v1/tenants/{floor.tenant_id}/kots/{third['id']}/acknowledge")

    after = auth_client.get(f"/api/v1/tenants/{floor.tenant_id}/kots").json()["kots"]
    assert [kot["number"] for kot in after] == [1]


def test_the_kitchen_acknowledges_a_ticket_once(auth_client: TestClient, floor: Floor) -> None:
    a1 = _open(auth_client, floor, "A1")
    base = f"/api/v1/tenants/{floor.tenant_id}"
    _add(auth_client, floor, a1["id"], _dosa("l1", 1, floor))
    kot = auth_client.post(f"{base}/orders/{a1['id']}/kot").json()
    assert kot["source"] == "pos"
    assert kot["sent_by_name"]
    assert kot["acknowledged_at"] is None

    first = auth_client.post(f"{base}/kots/{kot['id']}/acknowledge")
    again = auth_client.post(f"{base}/kots/{kot['id']}/acknowledge")

    assert first.status_code == 200, first.text
    assert first.json()["acknowledged_at"] is not None
    assert again.json()["acknowledged_at"] == first.json()["acknowledged_at"]


def test_billing_can_be_switched_off(auth_client: TestClient, floor: Floor) -> None:
    """With billing off the POS is a kitchen display: nothing opens, tables or takeaway."""
    base = f"/api/v1/tenants/{floor.tenant_id}"
    changed = auth_client.patch(base, json={"pos": {"billing": False}})
    assert changed.status_code == 200, changed.text
    assert changed.json()["pos"] == {"billing": False}

    seated = auth_client.post(f"{base}/orders", json={"table_id": floor.tables["A1"]})
    takeaway = auth_client.post(f"{base}/orders", json={"idempotency_key": "counter-1"})

    assert seated.status_code == 409, seated.text
    assert takeaway.status_code == 409, takeaway.text


def test_staff_run_the_pos(auth_client: TestClient, sign_in: SignIn, floor: Floor) -> None:
    """The POS is the floor's tool; a server who cannot send a ticket is not much use."""
    invite = auth_client.post(
        f"/api/v1/tenants/{floor.tenant_id}/invites", json={"email": STAFF_EMAIL, "role": "staff"}
    )
    assert invite.status_code == 201, invite.text
    _as(auth_client, sign_in, STAFF_EMAIL)

    order = _open(auth_client, floor)
    assert _add(auth_client, floor, order["id"], _dosa("l1", 1, floor)).status_code == 200
    base = f"/api/v1/tenants/{floor.tenant_id}/orders/{order['id']}"
    assert auth_client.post(f"{base}/kot").status_code == 201
    assert auth_client.post(f"{base}/bill").status_code == 200
    assert auth_client.post(f"{base}/close").status_code == 200


def test_an_outsider_sees_no_orders(auth_client: TestClient, sign_in: SignIn, floor: Floor) -> None:
    _as(auth_client, sign_in, OUTSIDER_EMAIL)

    assert auth_client.get(f"/api/v1/tenants/{floor.tenant_id}/orders").status_code == 403


def test_an_order_of_another_restaurant_is_not_found(auth_client: TestClient, floor: Floor) -> None:
    order = _open(auth_client, floor)
    other = auth_client.post("/api/v1/tenants", json={"name": "Second Place"}).json()["id"]

    assert auth_client.get(f"/api/v1/tenants/{other}/orders/{order['id']}").status_code == 404


# ----------------------------------------------------------------------------- the table


def test_the_table_sees_the_menu_without_signing_in(auth_client: TestClient, floor: Floor) -> None:
    """Available dishes only, no costs or codes, and the table the code was on."""
    auth_client.cookies.clear()
    response = auth_client.get(
        f"/api/v1/public/restaurants/{floor.tenant_id}/menu", params={"table": floor.tables["A2"]}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["restaurant"]["name"] == "Spice Garden"
    assert body["table"]["label"] == "A2"
    names = {item["name"] for section in body["sections"] for item in section["items"]}
    assert names == {"Neer Dosa", "Chicken Meals"}  # Crab Curry is off the menu
    dosa = next(i for s in body["sections"] for i in s["items"] if i["name"] == "Neer Dosa")
    assert "short_code" not in dosa and "profit_margin" not in dosa


def test_the_table_orders_straight_to_the_kitchen(
    auth_client: TestClient, sign_in: SignIn, floor: Floor
) -> None:
    """Seats itself, sends at once, and the board says which table - twice on one order."""
    auth_client.cookies.clear()
    base = f"/api/v1/public/restaurants/{floor.tenant_id}/orders"
    first = auth_client.post(
        base,
        json={
            "table_id": floor.tables["A1"],
            "lines": [
                {"item_id": floor.items["Neer Dosa"], "quantity": 2, "note": "less spicy"},
                {"item_id": floor.items["Chicken Meals"], "variation": "White Rice"},
            ],
        },
    )
    assert first.status_code == 201, first.text
    assert first.json()["table_label"] == "A1"
    again = auth_client.post(
        base,
        json={"table_id": floor.tables["A1"], "lines": [{"item_id": floor.items["Neer Dosa"]}]},
    )
    assert again.status_code == 201, again.text
    assert again.json()["order_number"] == first.json()["order_number"]
    assert again.json()["kot_number"] == first.json()["kot_number"] + 1

    _as(auth_client, sign_in, OWNER_EMAIL)
    queue = auth_client.get(f"/api/v1/tenants/{floor.tenant_id}/kots").json()["kots"]
    assert [kot["source"] for kot in queue] == ["diner", "diner"]
    assert queue[0]["sent_by_name"] == "Table A1"
    assert queue[0]["lines"][0]["note"] == "less spicy"
    floor_orders = auth_client.get(f"/api/v1/tenants/{floor.tenant_id}/orders").json()["orders"]
    assert [o["table_label"] for o in floor_orders] == ["A1"]
    assert floor_orders[0]["pending_count"] == 0


def test_the_table_cannot_order_what_is_off_or_where_there_is_no_table(
    auth_client: TestClient, floor: Floor
) -> None:
    auth_client.cookies.clear()
    base = f"/api/v1/public/restaurants/{floor.tenant_id}/orders"
    off = auth_client.post(
        base,
        json={"table_id": floor.tables["A1"], "lines": [{"item_id": floor.items["Crab Curry"]}]},
    )
    nowhere = auth_client.post(
        base, json={"table_id": floor.tenant_id, "lines": [{"item_id": floor.items["Neer Dosa"]}]}
    )
    assert off.status_code == 409, off.text
    assert nowhere.status_code == 404, nowhere.text


def test_the_table_still_orders_with_the_till_off(auth_client: TestClient, floor: Floor) -> None:
    """Billing off is about the POS; the QR flow is how such a restaurant takes orders."""
    auth_client.patch(f"/api/v1/tenants/{floor.tenant_id}", json={"pos": {"billing": False}})
    auth_client.cookies.clear()
    placed = auth_client.post(
        f"/api/v1/public/restaurants/{floor.tenant_id}/orders",
        json={"table_id": floor.tables["A1"], "lines": [{"item_id": floor.items["Neer Dosa"]}]},
    )
    assert placed.status_code == 201, placed.text
