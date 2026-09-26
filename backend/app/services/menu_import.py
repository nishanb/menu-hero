"""Reading a menu out of a POS item export.

Pure parsing: this module never touches the database. It takes the bytes of a CSV and gives
back items, the sections it found, and a list of what it could not make sense of - so the
owner sees the damage *before* anything is written, which is the rule HLD 9.1 sets for
ingestion ("nothing is published from an import without a person reading it first").

The format is the one Petpooja and its lookalikes export, and it is awkward in three specific
ways that any real implementation has to survive:

1. **The header repeats itself.** ``Variation``, ``Variation_Price``, ``Variation_Sap_Code``
   and ``Variation_Packing_Charges`` appear three times over, once per variation slot. A
   ``DictReader`` silently keeps only the last of each, so this reads by *position* instead.
2. **Rows are ragged.** In the export this was built against they are 21, 30 or 34 fields
   long depending on how many variations the dish has; indexing past the end is the normal
   case, not an error.
3. **A dish with variations has ``Price`` 0** and is priced by its variations. Treating that
   0 as the price would put a menu full of free food on the table.

Nothing here raises on a bad row. A single unreadable line out of four hundred should cost
that line, not the import - so the row is skipped and said out loud in ``warnings``.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from app.models.menu_item import (
    DIET_PATTERN,
    MAX_ITEMS_PER_TENANT,
    MAX_VARIATIONS,
    AddonGroup,
    GstType,
    Variation,
)
from app.services.image_store import data_url_type

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
"""25 MB. The 407-item export is 64 KB; the headroom is for pictures carried inline."""

MAX_WARNINGS = 50
"""Enough to show the shape of the problem without printing a book."""

ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
"""Tried in order. A POS export from a Windows machine is very often cp1252."""

NAME_COLUMN = "Name"

IMAGE_COLUMNS = ("Image", "Item_Image", "Image_Base64", "Photo", "Image_URL")
"""Names a POS might give the picture column. The first one present is used; none is normal."""
VARIATION_COLUMN = "Variation"
VARIATION_BLOCK = (
    "Variation",
    "Variation_Price",
    "Variation_Sap_Code",
    "Variation_Packing_Charges",
)
"""One variation slot, in the order the columns appear."""

REQUIRED_COLUMNS = (NAME_COLUMN,)
"""The only column without which the file is not a menu at all."""


class MenuImportError(ValueError):
    """The file could not be read as a menu export. The message is safe to show the caller."""


@dataclass(slots=True)
class ParsedItem:
    """One row, mapped to the fields :class:`~app.models.menu_item.MenuItem` stores."""

    name: str
    online_name: str = ""
    description: str = ""
    category: str = ""
    parent_category: str = ""
    short_code: str = ""
    short_code_2: str = ""
    sap_code: str = ""
    hsn_code: str = ""
    diet: str = ""
    gst_type: str = ""
    #: An ``https://`` URL as given, or a ``data:image/...;base64,...`` waiting to be stored.
    image: str = ""
    price: float = 0.0
    packing_charges: float = 0.0
    rank: int = 0
    variations: list[Variation] = field(default_factory=list)
    addon_group: AddonGroup | None = None


@dataclass(slots=True)
class ParsedMenu:
    """What one file turned out to contain."""

    items: list[ParsedItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    #: Rows that carried no usable name, and so could not become anything.
    skipped: int = 0

    @property
    def images(self) -> int:
        """How many rows carry a picture. Reported by the preview, stored by the commit."""
        return sum(1 for item in self.items if item.image)

    @property
    def categories(self) -> list[str]:
        """The sections the file mentions, in the order they first appear.

        First-appearance order, not alphabetical: a POS export lists a menu roughly the way
        the menu reads, and that is a better starting order than the alphabet.
        """
        seen: list[str] = []
        for item in self.items:
            if item.category and item.category not in seen:
                seen.append(item.category)
        return seen

    def warn(self, message: str) -> None:
        """Record a problem, up to the cap; the last entry says how many were left out."""
        if len(self.warnings) < MAX_WARNINGS:
            self.warnings.append(message)
        elif len(self.warnings) == MAX_WARNINGS:
            self.warnings.append("More problems were found; only the first 50 are listed.")


def parse_items_csv(payload: bytes) -> ParsedMenu:
    """Read a POS item export into a :class:`ParsedMenu`.

    Raises :class:`MenuImportError` only when the file as a whole is unusable - not readable
    as text, empty, or missing the one column that makes it a menu.
    """
    text = _decode(payload)
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise MenuImportError("That file is empty.")

    header = [cell.strip() for cell in rows[0]]
    missing = [column for column in REQUIRED_COLUMNS if column not in header]
    if missing:
        raise MenuImportError(
            "That does not look like a menu export: it has no "
            + " or ".join(f"'{column}'" for column in missing)
            + " column."
        )

    columns = _single_columns(header)
    slots = _variation_slots(header)
    menu = ParsedMenu()

    for number, row in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in row):
            continue  # a blank line between sections; not worth mentioning
        item = _read_row(row, number=number, columns=columns, slots=slots, menu=menu)
        if item is None:
            menu.skipped += 1
            continue
        menu.items.append(item)
        if len(menu.items) > MAX_ITEMS_PER_TENANT:
            raise MenuImportError(
                f"That file has more than {MAX_ITEMS_PER_TENANT} items, which is more than "
                "one menu can hold."
            )

    if not menu.items:
        raise MenuImportError("No menu items were found in that file.")
    logger.info(
        "menu export parsed: items=%d categories=%d skipped=%d warnings=%d",
        len(menu.items),
        len(menu.categories),
        menu.skipped,
        len(menu.warnings),
    )
    return menu


# ------------------------------------------------------------------ the awkward bits


def _decode(payload: bytes) -> str:
    """Text out of bytes, trying the encodings a POS actually writes."""
    if not payload:
        raise MenuImportError("That file is empty.")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise MenuImportError("That file is too large; the limit is 5 MB.")
    for encoding in ENCODINGS:
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise MenuImportError("That file is not text this can read. Export it again as CSV.")


def _single_columns(header: list[str]) -> dict[str, int]:
    """First position of each column that appears once. Later duplicates are variation slots."""
    positions: dict[str, int] = {}
    for index, name in enumerate(header):
        positions.setdefault(name, index)
    return positions


def _variation_slots(header: list[str]) -> list[int]:
    """Where each variation block starts.

    A block is a ``Variation`` column followed by its price, code and packing columns. The
    check that the three that follow are the expected ones is what stops a differently
    ordered export from being read as nonsense.
    """
    slots: list[int] = []
    for index, name in enumerate(header):
        if name != VARIATION_COLUMN:
            continue
        block = header[index : index + len(VARIATION_BLOCK)]
        if list(block) == list(VARIATION_BLOCK):
            slots.append(index)
    return slots[:MAX_VARIATIONS]


def _read_row(
    row: list[str],
    *,
    number: int,
    columns: dict[str, int],
    slots: list[int],
    menu: ParsedMenu,
) -> ParsedItem | None:
    """One CSV row as an item, or ``None`` when it carries no name to hang anything on."""

    def cell(column: str) -> str:
        index = columns.get(column)
        if index is None or index >= len(row):
            return ""
        return row[index].strip()

    name = cell(NAME_COLUMN)
    if not name:
        menu.warn(f"Row {number} has no name, so it was skipped.")
        return None

    item = ParsedItem(
        name=name,
        online_name=cell("Online_Name"),
        # POS exports sometimes wrap a description in its own quotes on the way out.
        description=cell("Description").strip("'"),
        category=cell("Category"),
        parent_category=cell("Parent_Category"),
        short_code=cell("Short_Code"),
        short_code_2=cell("Short_Code_2"),
        sap_code=cell("Sap_Code"),
        hsn_code=cell("HSN_Code"),
        diet=_diet(cell("Attributes"), row=number, menu=menu),
        gst_type=_gst_type(cell("Goods_Services")),
        image=_image(cell, row=number, menu=menu),
        price=_number(cell("Price"), row=number, field_name="price", menu=menu),
        packing_charges=_number(
            cell("Packing_Charges"), row=number, field_name="packing charge", menu=menu
        ),
        rank=int(_number(cell("Rank"), row=number, field_name="rank", menu=menu)),
        variations=_read_variations(row, number=number, columns=columns, slots=slots, menu=menu),
        addon_group=_read_addon_group(cell),
    )
    if not item.variations and not item.price:
        # Not fatal - a combo thrown in free is a real thing - but 16 of these in one export
        # is usually a column that did not survive, and the owner should see them first.
        menu.warn(f"Row {number} ('{name}') has no price.")
    if item.variations and item.price:
        # Both a price and variations: the variations are what a diner actually chooses
        # between, so they win and the row price is reported rather than silently dropped.
        menu.warn(
            f"Row {number} ('{name}') has both a price and variations; the variation prices "
            "were used."
        )
        item.price = 0.0
    return item


def _read_variations(
    row: list[str],
    *,
    number: int,
    columns: dict[str, int],
    slots: list[int],
    menu: ParsedMenu,
) -> list[Variation]:
    """The filled variation slots of one row, in the order the columns run."""
    group = ""
    group_index = columns.get("Variation_group_name")
    if group_index is not None and group_index < len(row):
        group = row[group_index].strip()

    variations: list[Variation] = []
    for start in slots:
        values = [
            row[index].strip() if index < len(row) else "" for index in range(start, start + 4)
        ]
        variation_name = values[0]
        if not variation_name:
            continue
        variations.append(
            Variation(
                group=group,
                name=variation_name,
                price=_number(values[1], row=number, field_name="variation price", menu=menu),
                sap_code=values[2],
                packing_charges=_number(
                    values[3], row=number, field_name="variation packing charge", menu=menu
                ),
            )
        )
    return variations


def _read_addon_group(cell: Callable[[str], str]) -> AddonGroup | None:
    """The add-on group a row references, if it references one.

    Only the group's shape travels in the items file; what is *in* the group lives in the
    separate add-ons export, which is not read here.
    """
    name = cell("Addon_Group_Name")
    if not name:
        return None
    return AddonGroup(
        name=name,
        selection=cell("Addon_Group_Selection") or "single",
        minimum=int(_to_float(cell("Addon_Group_Min"), 0)),
        maximum=int(_to_float(cell("Addon_Group_Max"), 1)),
    )


def _image(cell: Callable[[str], str], *, row: int, menu: ParsedMenu) -> str:
    """The picture a row carries: an https link as given, or base64 to be stored on commit.

    Only checked here, never decoded: the dry run must not write anything, and a 2 MB decode
    per row would make the preview cost as much as the import.
    """
    raw = next((cell(column) for column in IMAGE_COLUMNS if cell(column)), "")
    if not raw:
        return ""
    if raw.startswith("https://"):
        return raw
    if data_url_type(raw) is not None:
        return raw
    menu.warn(f"Row {row} has something in its image column that is not a picture we store.")
    return ""


def _gst_type(raw: str) -> str:
    """``Goods_Services`` -> ``services`` / ``goods``. Blank stays blank rather than guessing:
    an item whose tax treatment nobody stated should say so, not pick one."""
    value = raw.strip().lower()
    return value if value in {member.value for member in GstType} else ""


def _diet(raw: str, *, row: int, menu: ParsedMenu) -> str:
    """The dietary attribute, normalised the way the item model will store it.

    Normalised *here* rather than left to the model: the preview has to show what the commit
    will actually write, and an attribute that silently disappears between the two would make
    the preview a lie.
    """
    if not raw:
        return ""
    diet = re.sub(r"\s+", " ", raw.strip().lower())
    if DIET_PATTERN.match(diet):
        return diet
    menu.warn(f"Row {row} has an unreadable dietary attribute ('{raw}'), so none was set.")
    return ""


def _number(raw: str, *, row: int, field_name: str, menu: ParsedMenu) -> float:
    """A number out of a cell, or 0 with a warning. Never raises: one odd cell is not a file."""
    if not raw:
        return 0.0
    try:
        return max(0.0, float(raw.replace(",", "")))
    except ValueError:
        menu.warn(f"Row {row} has an unreadable {field_name} ('{raw}'), so 0 was used.")
        return 0.0


def _to_float(raw: str, fallback: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return fallback


__all__ = [
    "MAX_UPLOAD_BYTES",
    "MenuImportError",
    "ParsedItem",
    "ParsedMenu",
    "parse_items_csv",
]
