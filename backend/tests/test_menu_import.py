"""Reading a POS item export, and turning it into a menu.

The parser tests need no database. The endpoint tests talk to a real MongoDB through the app
and skip when none is reachable (see ``tests/conftest.py``).

``tests/fixtures/pos_items.csv`` mirrors the shape of a real Petpooja export, awkwardness and
all: 34 header columns with ``Variation`` repeated three times, rows that stop early, a blank
line in the middle, and a row whose price and dietary attribute are both nonsense.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import ADMIN_EMAIL, SignIn
from fastapi.testclient import TestClient
from httpx import Response

from app.services.menu_import import MenuImportError, parse_items_csv

FIXTURE = Path(__file__).parent / "fixtures" / "pos_items.csv"

OWNER_EMAIL = "owner@example.com"
STAFF_EMAIL = "server@example.com"


def _payload() -> bytes:
    return FIXTURE.read_bytes()


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


def _import(
    client: TestClient, tenant_id: str, *, dry_run: bool = True, payload: bytes | None = None
) -> Response:
    return client.post(
        f"/api/v1/tenants/{tenant_id}/menu/import",
        params={"dry_run": str(dry_run).lower()},
        files={"file": ("items.csv", payload if payload is not None else _payload(), "text/csv")},
    )


# ----------------------------------------------------------------------------- the parser


def test_every_named_row_becomes_an_item() -> None:
    """The blank line is not an item and not a complaint; the named rows all are."""
    menu = parse_items_csv(_payload())

    assert [item.name for item in menu.items] == [
        "Neer Dosa + Chicken Curry Combo",
        "Onion Neer Dosa",
        "Bangude / Mackrel",
        "Chicken Meals",
        "Chapati Combo",
        "Free Water",
        "Odd Price Item",
    ]
    assert menu.skipped == 0


def test_the_repeated_variation_columns_are_read_by_position() -> None:
    """A DictReader keeps only the last of each duplicate header, which loses two of three."""
    menu = parse_items_csv(_payload())
    meals = next(item for item in menu.items if item.name == "Chicken Meals")
    chapati = next(item for item in menu.items if item.name == "Chapati Combo")

    assert [(v.group, v.name, v.price) for v in meals.variations] == [
        ("Preparation", "Boiled Rice", 249.0),
        ("Preparation", "White Rice", 259.0),
    ]
    assert len(chapati.variations) == 3
    assert chapati.variations[2].name == "Kerala Porota"
    assert chapati.variations[2].price == 199.0


def test_a_dish_priced_by_its_variations_keeps_a_zero_of_its_own() -> None:
    """Its ``Price`` column is 0; reading that as the price puts free food on the menu."""
    menu = parse_items_csv(_payload())
    meals = next(item for item in menu.items if item.name == "Chicken Meals")

    assert meals.price == 0.0
    assert min(v.price for v in meals.variations) == 249.0


def test_short_rows_are_normal() -> None:
    """Rows stop as soon as a dish has no variations; indexing past the end is the usual case."""
    menu = parse_items_csv(_payload())
    dosa = next(item for item in menu.items if item.name == "Onion Neer Dosa")

    assert dosa.price == 189.0
    assert dosa.variations == []
    assert dosa.addon_group is None


def test_an_addon_group_reference_comes_through() -> None:
    menu = parse_items_csv(_payload())
    fish = next(item for item in menu.items if item.name == "Bangude / Mackrel")

    assert fish.addon_group is not None
    assert fish.addon_group.name == "Fish Preparation"
    assert fish.addon_group.selection == "single"
    assert (fish.addon_group.minimum, fish.addon_group.maximum) == (1, 1)


def test_a_bad_cell_costs_the_cell_and_not_the_file() -> None:
    """One unreadable price out of four hundred rows must not lose the other 399."""
    menu = parse_items_csv(_payload())
    odd = next(item for item in menu.items if item.name == "Odd Price Item")

    assert odd.price == 0.0
    assert odd.diet == ""  # 'unknown attribute!' is not a shape the model accepts
    assert any("unreadable price" in warning for warning in menu.warnings)
    assert any("unreadable dietary attribute" in warning for warning in menu.warnings)


def test_items_with_no_price_are_called_out() -> None:
    """Not fatal - a free combo is real - but the owner should see them before committing."""
    menu = parse_items_csv(_payload())

    assert any("'Free Water'" in warning and "no price" in warning for warning in menu.warnings)


def test_a_description_loses_the_quotes_the_pos_wrapped_it_in() -> None:
    menu = parse_items_csv(_payload())

    assert menu.items[0].description == "Three soft neer dosas with chicken curry"


def test_categories_come_out_in_the_order_the_file_introduces_them() -> None:
    """A POS export runs roughly the way the menu reads, which beats the alphabet."""
    menu = parse_items_csv(_payload())

    assert menu.categories == [
        "NeerDosa - NonVeg Combos",
        "Onion NeerDosa",
        "Sea Food - Chef Special",
        "Meals",
        "Chapati",
        "Beverages",
    ]


def test_a_file_that_is_not_a_menu_is_refused() -> None:
    with pytest.raises(MenuImportError, match="no 'Name' column"):
        parse_items_csv(b"Foo,Bar\n1,2\n")


def test_an_empty_file_is_refused() -> None:
    with pytest.raises(MenuImportError, match="empty"):
        parse_items_csv(b"")


def test_a_header_with_no_rows_is_refused() -> None:
    with pytest.raises(MenuImportError, match="No menu items"):
        parse_items_csv(b"Name,Price\n")


def test_a_windows_encoded_export_is_read() -> None:
    """A POS on Windows writes cp1252, and its curly quotes must not kill the import."""
    text = "Name,Category,Price\nCafé Latte,Beverages,120\n"

    menu = parse_items_csv(text.encode("cp1252"))

    assert menu.items[0].name == "Café Latte"


# ----------------------------------------------------------------------------- the endpoint


def test_a_dry_run_reports_without_writing(auth_client: TestClient, tenant_id: str) -> None:
    """The point of the preview: the owner sees the damage before the menu changes."""
    response = _import(auth_client, tenant_id, dry_run=True)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["committed"] is False
    assert body["item_count"] == 7
    assert body["items_written"] == 0
    assert len(body["new_categories"]) == 6
    assert body["existing_categories"] == []
    assert body["sample"][0]["name"] == "Neer Dosa + Chicken Curry Combo"
    assert auth_client.get(f"/api/v1/tenants/{tenant_id}/menu/items").json()["total"] == 0


def test_committing_writes_the_items_and_the_sections(
    auth_client: TestClient, tenant_id: str
) -> None:
    response = _import(auth_client, tenant_id, dry_run=False)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["committed"] is True
    assert body["items_written"] == 7
    assert body["items_replaced"] == 0

    items = auth_client.get(f"/api/v1/tenants/{tenant_id}/menu/items").json()
    assert items["total"] == 7
    meals = next(item for item in items["items"] if item["name"] == "Chicken Meals")
    assert meals["price"] == 0
    assert meals["price_from"] == 249
    assert len(meals["variations"]) == 2

    categories = auth_client.get(f"/api/v1/tenants/{tenant_id}/categories").json()["categories"]
    assert [c["name"] for c in categories] == [
        "NeerDosa - NonVeg Combos",
        "Onion NeerDosa",
        "Sea Food - Chef Special",
        "Meals",
        "Chapati",
        "Beverages",
    ]


def test_importing_again_replaces_the_menu_rather_than_doubling_it(
    auth_client: TestClient, tenant_id: str
) -> None:
    """An export is somebody saying "this is my menu", not a patch to merge."""
    _import(auth_client, tenant_id, dry_run=False)

    second = _import(auth_client, tenant_id, dry_run=False)

    assert second.json()["items_replaced"] == 7
    assert second.json()["items_written"] == 7
    assert auth_client.get(f"/api/v1/tenants/{tenant_id}/menu/items").json()["total"] == 7


def test_a_second_import_leaves_the_owners_categories_alone(
    auth_client: TestClient, tenant_id: str
) -> None:
    """Rank and hidden/active are the owner's decisions; an import has no business on them."""
    _import(auth_client, tenant_id, dry_run=False)
    listed = auth_client.get(f"/api/v1/tenants/{tenant_id}/categories").json()["categories"]
    beverages = next(c for c in listed if c["name"] == "Beverages")
    auth_client.patch(
        f"/api/v1/tenants/{tenant_id}/categories/{beverages['id']}",
        json={"rank": 0, "status": "hidden"},
    )

    _import(auth_client, tenant_id, dry_run=False)

    again = auth_client.get(f"/api/v1/tenants/{tenant_id}/categories").json()["categories"]
    kept = next(c for c in again if c["name"] == "Beverages")
    assert kept["id"] == beverages["id"]
    assert kept["status"] == "hidden"
    assert len(again) == 6


def test_a_file_that_is_not_a_menu_is_a_400(auth_client: TestClient, tenant_id: str) -> None:
    response = _import(auth_client, tenant_id, payload=b"Foo,Bar\n1,2\n")

    assert response.status_code == 400, response.text
    assert "Name" in response.json()["detail"]


def test_staff_cannot_import(auth_client: TestClient, sign_in: SignIn, tenant_id: str) -> None:
    """Replacing the whole menu is an owner's decision."""
    invite = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/invites", json={"email": STAFF_EMAIL, "role": "staff"}
    )
    assert invite.status_code == 201, invite.text
    _as(auth_client, sign_in, STAFF_EMAIL)

    assert _import(auth_client, tenant_id).status_code == 403
    assert auth_client.get(f"/api/v1/tenants/{tenant_id}/menu/items").status_code == 200


def test_a_platform_admin_can_import(
    auth_client: TestClient, sign_in: SignIn, tenant_id: str
) -> None:
    _as(auth_client, sign_in, ADMIN_EMAIL)

    assert _import(auth_client, tenant_id, dry_run=False).status_code == 200


def test_signing_out_closes_the_menu(auth_client: TestClient, tenant_id: str) -> None:
    auth_client.cookies.clear()

    assert auth_client.get(f"/api/v1/tenants/{tenant_id}/menu/items").status_code == 401


# ----------------------------------------------------------------------------- pictures

IMAGE_FIXTURE = Path(__file__).parent / "fixtures" / "pos_items_with_images.csv"


def _image_payload() -> bytes:
    return IMAGE_FIXTURE.read_bytes()


def test_a_picture_column_is_optional() -> None:
    """The export this was built against has none, and that is not a problem."""
    menu = parse_items_csv(_payload())

    assert menu.images == 0
    assert all(item.image == "" for item in menu.items)


def test_the_parser_keeps_pictures_without_decoding_them() -> None:
    """The dry run must not do 2 MB of work per row to tell you what is in the file."""
    menu = parse_items_csv(_image_payload())

    assert menu.images == 3  # two base64 rows and one link
    coffee = next(item for item in menu.items if item.name == "Filter Coffee")
    assert coffee.image == "https://cdn.example.com/coffee.jpg"


def test_a_cell_that_is_not_a_picture_is_dropped_with_a_warning() -> None:
    """One bad photo costs the photo, not the row and not the import."""
    menu = parse_items_csv(_image_payload())
    broken = next(item for item in menu.items if item.name == "Broken Photo")

    assert broken.image == ""
    assert broken.price == 40.0
    assert any("image column" in warning for warning in menu.warnings)


def test_an_svg_never_counts_as_a_picture() -> None:
    """Refused at preview, not at commit: the count has to mean what it says."""
    menu = parse_items_csv(_image_payload())

    svg = next(item for item in menu.items if item.name == "Wrong Type")
    assert svg.image == ""


def test_a_dry_run_reports_pictures_without_storing_them(
    auth_client: TestClient, tenant_id: str
) -> None:
    response = _import(auth_client, tenant_id, dry_run=True, payload=_image_payload())

    assert response.status_code == 200, response.text
    assert response.json()["images"] == 3


def test_committing_stores_the_bytes_and_keeps_only_a_url(
    auth_client: TestClient, tenant_id: str
) -> None:
    """A data URL on four hundred documents is megabytes nobody can cache."""
    response = _import(auth_client, tenant_id, dry_run=False, payload=_image_payload())
    assert response.status_code == 200, response.text

    items = auth_client.get(f"/api/v1/tenants/{tenant_id}/menu/items").json()["items"]
    dosa = next(item for item in items if item["name"] == "Masala Dosa")
    assert dosa["image_url"].startswith("/api/v1/images/")
    assert "base64" not in dosa["image_url"]

    served = auth_client.get(dosa["image_url"])
    assert served.status_code == 200, served.text
    assert served.headers["content-type"] == "image/png"


def test_one_picture_used_twice_is_stored_once(auth_client: TestClient, tenant_id: str) -> None:
    """A POS export repeats one placeholder across dozens of rows; storing it dozens of
    times is the difference between a 2 MB import and a 100 MB one."""
    _import(auth_client, tenant_id, dry_run=False, payload=_image_payload())

    items = auth_client.get(f"/api/v1/tenants/{tenant_id}/menu/items").json()["items"]
    dosa = next(item for item in items if item["name"] == "Masala Dosa")
    set_dosa = next(item for item in items if item["name"] == "Set Dosa")

    assert dosa["image_url"] == set_dosa["image_url"]


def test_an_https_link_is_left_alone(auth_client: TestClient, tenant_id: str) -> None:
    """It is already on somebody's CDN; re-hosting it would be the wrong favour."""
    _import(auth_client, tenant_id, dry_run=False, payload=_image_payload())

    items = auth_client.get(f"/api/v1/tenants/{tenant_id}/menu/items").json()["items"]
    coffee = next(item for item in items if item["name"] == "Filter Coffee")

    assert coffee["image_url"] == "https://cdn.example.com/coffee.jpg"


def test_an_svg_is_refused(auth_client: TestClient, tenant_id: str) -> None:
    """An SVG is a document that can carry script, not a picture."""
    _import(auth_client, tenant_id, dry_run=False, payload=_image_payload())

    items = auth_client.get(f"/api/v1/tenants/{tenant_id}/menu/items").json()["items"]
    wrong = next(item for item in items if item["name"] == "Wrong Type")

    assert wrong["image_url"] == ""


def test_a_picture_is_served_to_anyone(auth_client: TestClient, tenant_id: str) -> None:
    """The diner's menu shows pictures to whoever scanned the code, so no session is asked."""
    _import(auth_client, tenant_id, dry_run=False, payload=_image_payload())
    items = auth_client.get(f"/api/v1/tenants/{tenant_id}/menu/items").json()["items"]
    url = next(i["image_url"] for i in items if i["name"] == "Masala Dosa")
    auth_client.cookies.clear()

    served = auth_client.get(url)
    assert served.status_code == 200, served.text
    assert served.headers["content-type"].startswith("image/")


# ----------------------------------------------------------------------------- uploads

PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000a49444154789c6360000002000100055c0b8a000000"
    "0049454e44ae426082"
)


def test_a_picture_can_be_uploaded_for_one_dish(auth_client: TestClient, tenant_id: str) -> None:
    """The item form needs a URL to put on the dish; the bytes are not its business."""
    response = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/menu/images",
        files={"file": ("dosa.png", PNG_BYTES, "image/png")},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["url"].startswith("/api/v1/images/")
    assert body["content_type"] == "image/png"
    served = auth_client.get(body["url"])
    assert served.status_code == 200
    assert served.content == PNG_BYTES


def test_an_uploaded_picture_can_be_put_on_an_item(auth_client: TestClient, tenant_id: str) -> None:
    url = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/menu/images",
        files={"file": ("dosa.png", PNG_BYTES, "image/png")},
    ).json()["url"]
    created = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/menu/items", json={"name": "Neer Dosa"}
    ).json()

    response = auth_client.patch(
        f"/api/v1/tenants/{tenant_id}/menu/items/{created['id']}", json={"image_url": url}
    )

    assert response.status_code == 200, response.text
    assert response.json()["image_url"] == url


def test_uploading_the_same_picture_twice_stores_it_once(
    auth_client: TestClient, tenant_id: str
) -> None:
    """Content-addressed, the same as the import: one placeholder on forty dishes is one copy."""
    first = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/menu/images",
        files={"file": ("a.png", PNG_BYTES, "image/png")},
    ).json()["url"]
    second = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/menu/images",
        files={"file": ("b.png", PNG_BYTES, "image/png")},
    ).json()["url"]

    assert first == second


def test_a_pdf_is_not_a_picture(auth_client: TestClient, tenant_id: str) -> None:
    response = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/menu/images",
        files={"file": ("menu.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 400, response.text
    assert "not an image type" in response.json()["detail"]


def test_an_svg_upload_is_refused(auth_client: TestClient, tenant_id: str) -> None:
    """Same rule as the import: an SVG is a document that can carry script."""
    response = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/menu/images",
        files={"file": ("logo.svg", b"<svg></svg>", "image/svg+xml")},
    )

    assert response.status_code == 400, response.text


def test_staff_cannot_upload(auth_client: TestClient, sign_in: SignIn, tenant_id: str) -> None:
    invite = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/invites", json={"email": STAFF_EMAIL, "role": "staff"}
    )
    assert invite.status_code == 201, invite.text
    _as(auth_client, sign_in, STAFF_EMAIL)

    response = auth_client.post(
        f"/api/v1/tenants/{tenant_id}/menu/images",
        files={"file": ("dosa.png", PNG_BYTES, "image/png")},
    )

    assert response.status_code == 403, response.text
