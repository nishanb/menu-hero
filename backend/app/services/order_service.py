"""Orders: the single writer HLD 3.3 asks for.

Every change to an order comes through here - the POS, and later the diner chat and the MCP
tools. That is what lets the invariants in :mod:`app.models.order` actually hold: a line's
price is frozen when it is added, a sent line is never edited, and a bill is never printed
with lines the kitchen has not seen.

There is no payment in this file and there will not be. Checkout stops at the KOT; the
counter takes the money and a person presses **Paid**, which is all ``close`` records.

Local MongoDB is often a standalone server, so nothing here uses a transaction. Each mutation
is one document replaced after its invariants are checked in memory, and the two-document
step (send a ticket, then stamp the lines) is ordered so a crash between them leaves a
ticket the kitchen has and lines still marked pending - which resends, and never loses food.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from bson import ObjectId
from pydantic import ValidationError
from pymongo.errors import DuplicateKeyError

from app.core.database import MongoDatabase
from app.models.menu_item import MenuItem, MenuItemRepository
from app.models.order import (
    MAX_LINES,
    Kot,
    KotLine,
    KotRepository,
    KotSource,
    LineVariation,
    Order,
    OrderKind,
    OrderLine,
    OrderRepository,
    OrderStatus,
    SequenceRepository,
)
from app.models.table import TableRepository
from app.models.tenant import TenantRepository
from app.models.user import utcnow
from app.services.auth_service import AuthContext
from app.services.errors import ConflictError, NotFoundError, ValidationFailedError

logger = logging.getLogger(__name__)

ORDER_SEQUENCE = "order"
KOT_SEQUENCE = "kot"


class LineRequest:
    """What the POS sends to add a dish: which item, which form, how many, any note."""

    def __init__(
        self,
        *,
        line_id: str,
        item_id: ObjectId,
        variation: str | None,
        quantity: int,
        note: str,
    ) -> None:
        self.line_id = line_id
        self.item_id = item_id
        self.variation = variation
        self.quantity = quantity
        self.note = note


class OrderService:
    """Use-case layer for ``/tenants/{tenant_id}/orders``."""

    def __init__(self, database: MongoDatabase) -> None:
        self._orders = OrderRepository(database)
        self._kots = KotRepository(database)
        self._sequences = SequenceRepository(database)
        self._tables = TableRepository(database)
        self._items = MenuItemRepository(database)
        self._tenants = TenantRepository(database)

    # ------------------------------------------------------------------ reading

    async def list_active(self, tenant_id: ObjectId) -> list[Order]:
        """Everything that is still on the floor: open, or billed and waiting to be paid."""
        return await self._orders.list_for_tenant(
            tenant_id, statuses=[OrderStatus.OPEN, OrderStatus.BILLED]
        )

    async def list_recent(self, tenant_id: ObjectId, *, limit: int = 100) -> list[Order]:
        """The day's history, newest first, whatever state it ended in."""
        return await self._orders.list_for_tenant(tenant_id, limit=limit)

    async def get(self, *, tenant_id: ObjectId, order_id: ObjectId) -> Order:
        """One order of *this* restaurant, or :class:`NotFoundError`."""
        order = await self._orders.get(order_id)
        if order is None or order.tenant_id != tenant_id:
            raise NotFoundError("Order not found")
        return order

    async def kots_for(self, *, tenant_id: ObjectId, order_id: ObjectId) -> list[Kot]:
        await self.get(tenant_id=tenant_id, order_id=order_id)
        return await self._kots.list_for_order(order_id)

    async def active_kots(self, tenant_id: ObjectId) -> list[Kot]:
        """The kitchen's queue: tickets of orders still on the floor that nobody has seen yet.

        Acknowledging a ticket takes it out; a paid or cancelled order takes its tickets out
        with it. Two reads rather than a join - the active orders are a handful, and the
        floor already fetches them.
        """
        orders = await self.list_active(tenant_id)
        return await self._kots.list_unacknowledged(
            [order.id for order in orders if order.id is not None]
        )

    async def acknowledge_kot(
        self, *, tenant_id: ObjectId, kot_id: ObjectId, actor: AuthContext
    ) -> Kot:
        """The kitchen has seen the ticket. Idempotent: the first tap is the one that counts."""
        kot = await self.get_kot(tenant_id=tenant_id, kot_id=kot_id)
        if kot.acknowledged_at is not None:
            return kot
        updated = await self._kots.update_by_id(
            kot_id, {"acknowledged_at": utcnow(), "acknowledged_by": actor.user_id}
        )
        if updated is None:
            raise NotFoundError("Ticket not found")
        return updated

    async def get_kot(self, *, tenant_id: ObjectId, kot_id: ObjectId) -> Kot:
        kot = await self._kots.get(kot_id)
        if kot is None or kot.tenant_id != tenant_id:
            raise NotFoundError("Ticket not found")
        return kot

    # ------------------------------------------------------------------ opening

    async def open(
        self,
        *,
        tenant_id: ObjectId,
        table_id: ObjectId | None,
        idempotency_key: str | None,
        actor: AuthContext,
    ) -> Order:
        """Seat a table, or start a takeaway bill.

        Seating a table that already has an open order returns that order rather than a
        second one - two servers tapping A1 at once is the ordinary case, not an error, and
        the partial unique index is the guarantee behind the check.
        """
        tenant = await self._tenants.get(tenant_id)
        if tenant is not None and not tenant.pos.billing:
            raise ConflictError("Billing is switched off on the POS for this restaurant.")
        kind = OrderKind.DINE_IN if table_id is not None else OrderKind.TAKEAWAY
        label = ""
        if table_id is not None:
            table = await self._tables.get(table_id)
            if table is None or table.tenant_id != tenant_id or not table.is_active:
                raise NotFoundError("That table is not on the floor plan")
            label = table.label
            existing = await self._orders.open_for_table(tenant_id, table_id)
            if existing is not None:
                return existing
        elif idempotency_key:
            existing = await self._orders.find_one(
                {"tenant_id": tenant_id, "idempotency_key": idempotency_key}
            )
            if existing is not None:
                return existing

        order = Order(
            tenant_id=tenant_id,
            number=await self._sequences.next(tenant_id, ORDER_SEQUENCE),
            kind=kind,
            table_id=table_id,
            table_label=label,
            idempotency_key=idempotency_key or None,
            opened_by=actor.user_id,
        )
        try:
            order.id = await self._orders.insert(order)
        except DuplicateKeyError:
            # Lost the race on the table index. The winner is the order we wanted anyway.
            if table_id is not None:
                winner = await self._orders.open_for_table(tenant_id, table_id)
                if winner is not None:
                    return winner
            raise ConflictError("That order was just opened by somebody else.") from None
        logger.info(
            "order opened: tenant=%s number=%d kind=%s table=%r by=%s",
            tenant_id,
            order.number,
            kind,
            label,
            actor.user.email,
        )
        return order

    # ------------------------------------------------------------------ lines

    async def add_lines(
        self,
        *,
        tenant_id: ObjectId,
        order_id: ObjectId,
        requests: Sequence[LineRequest],
        actor: AuthContext,
    ) -> Order:
        """Put dishes on the ticket, at today's price, frozen.

        The name and price are copied from the menu item *now*: the menu is edited all day,
        and the bill has to say what the table was charged, not what the dish costs later.
        A dish that is off the menu is refused rather than silently added - the kitchen has
        said it cannot make it.
        """
        order = await self._writable(tenant_id=tenant_id, order_id=order_id)
        stored = await self._append(order, requests)
        logger.info(
            "order lines added: tenant=%s number=%d lines=%d by=%s",
            tenant_id,
            stored.number,
            len(requests),
            actor.user.email,
        )
        return stored

    async def _append(self, order: Order, requests: Sequence[LineRequest]) -> Order:
        """The part of adding lines that is the same whoever is adding them."""
        if len(order.lines) + len(requests) > MAX_LINES:
            raise ValidationFailedError(f"An order can hold at most {MAX_LINES} lines.")

        wanted = {request.item_id for request in requests}
        found = await self._items.find({"_id": {"$in": list(wanted)}, "tenant_id": order.tenant_id})
        items = {item.id: item for item in found if item.id is not None}

        existing_ids = {line.id for line in order.lines}
        for request in requests:
            if request.line_id in existing_ids:
                raise ConflictError("That line is already on the order.")
            item = items.get(request.item_id)
            if item is None:
                raise NotFoundError("That dish is not on this menu.")
            if not item.is_available:
                raise ConflictError(f"'{item.name}' is off the menu right now.")
            order.lines.append(self._line_from(request, item))
            existing_ids.add(request.line_id)

        return await self._orders.replace(self._validated(order))

    async def update_line(
        self,
        *,
        tenant_id: ObjectId,
        order_id: ObjectId,
        line_id: str,
        quantity: int | None,
        note: str | None,
        actor: AuthContext,
    ) -> Order:
        """Change how many, or what the kitchen is told - while the kitchen has not been."""
        order = await self._writable(tenant_id=tenant_id, order_id=order_id)
        line = self._pending_line(order, line_id)
        if quantity is not None:
            line.quantity = quantity
        if note is not None:
            line.note = note
        return await self._orders.replace(self._validated(order))

    async def remove_line(
        self, *, tenant_id: ObjectId, order_id: ObjectId, line_id: str, actor: AuthContext
    ) -> Order:
        """Take a dish off before the kitchen starts it."""
        order = await self._writable(tenant_id=tenant_id, order_id=order_id)
        self._pending_line(order, line_id)
        order.lines = [line for line in order.lines if line.id != line_id]
        return await self._orders.replace(self._validated(order))

    # ------------------------------------------------------------------ the kitchen

    async def send_kot(self, *, tenant_id: ObjectId, order_id: ObjectId, actor: AuthContext) -> Kot:
        """Tell the kitchen about everything it has not been told about.

        Ticket first, then the lines: a crash in between leaves a ticket the kitchen has and
        lines still marked pending, which resends the same dishes. That is a duplicate a
        person can catch. The other order would lose food.
        """
        order = await self._writable(tenant_id=tenant_id, order_id=order_id)
        kot = await self._ticket(
            order,
            source=KotSource.POS,
            sent_by=actor.user_id,
            sent_by_name=actor.user.name or actor.user.email,
        )
        logger.info(
            "kot sent: tenant=%s kot=%d order=%d lines=%d by=%s",
            tenant_id,
            kot.number,
            order.number,
            len(kot.lines),
            actor.user.email,
        )
        return kot

    async def _ticket(
        self, order: Order, *, source: KotSource, sent_by: ObjectId | None, sent_by_name: str
    ) -> Kot:
        """Write the ticket for everything pending, then stamp the lines. See `send_kot`."""
        pending = order.pending_lines
        if not pending:
            raise ConflictError("Everything on this order has already gone to the kitchen.")
        assert order.id is not None

        kot = Kot(
            tenant_id=order.tenant_id,
            order_id=order.id,
            number=await self._sequences.next(order.tenant_id, KOT_SEQUENCE),
            order_number=order.number,
            kind=order.kind,
            table_label=order.table_label,
            lines=[
                KotLine(
                    line_id=line.id,
                    name=line.name,
                    variation=line.variation.name if line.variation else "",
                    quantity=line.quantity,
                    note=line.note,
                )
                for line in pending
            ],
            source=source,
            sent_by=sent_by,
            sent_by_name=sent_by_name,
        )
        kot.id = await self._kots.insert(kot)

        sent_ids = {line.id for line in pending}
        for line in order.lines:
            if line.id in sent_ids:
                line.kot_id = kot.id
        order.kot_ids.append(kot.id)
        await self._orders.replace(order)
        return kot

    # ------------------------------------------------------------------ the table itself

    async def place_from_table(
        self, *, tenant_id: ObjectId, table_id: ObjectId, requests: Sequence[LineRequest]
    ) -> Kot:
        """A diner ordered from the QR menu: onto the table's order, straight to the kitchen.

        Nobody is signed in, so this is one call that does what a captain does in three -
        seat the table if it is not seated, add the dishes, send the round - and it sends
        immediately because there is no captain to press Send. It ignores the POS billing
        switch on purpose: that switch is about the till, and a restaurant with the till off
        is exactly one that takes its orders this way. A table that is already billed is
        refused; the diner should be paying, not ordering.
        """
        table = await self._tables.get(table_id)
        if table is None or table.tenant_id != tenant_id or not table.is_active:
            raise NotFoundError("That table is not on the floor plan")

        order = await self._orders.open_for_table(tenant_id, table_id)
        if order is None:
            order = Order(
                tenant_id=tenant_id,
                number=await self._sequences.next(tenant_id, ORDER_SEQUENCE),
                kind=OrderKind.DINE_IN,
                table_id=table_id,
                table_label=table.label,
                opened_by=None,
            )
            try:
                order.id = await self._orders.insert(order)
            except DuplicateKeyError:
                order = await self._orders.open_for_table(tenant_id, table_id)
                if order is None:
                    raise ConflictError("That table was just seated by somebody else.") from None
        if order.status is not OrderStatus.OPEN:
            raise ConflictError("This table is being billed. Ask your server to add anything more.")

        order = await self._append(order, requests)
        kot = await self._ticket(
            order, source=KotSource.DINER, sent_by=None, sent_by_name=f"Table {table.label}"
        )
        logger.info(
            "kot sent by table: tenant=%s kot=%d order=%d table=%r lines=%d",
            tenant_id,
            kot.number,
            order.number,
            table.label,
            len(kot.lines),
        )
        return kot

    # ------------------------------------------------------------------ the counter

    async def bill(self, *, tenant_id: ObjectId, order_id: ObjectId, actor: AuthContext) -> Order:
        """Put the bill on the table. Nothing may be added after this.

        Refused while lines are pending: a bill for food the kitchen has not been asked to
        make is the one mistake this flow exists to prevent.
        """
        order = await self._writable(tenant_id=tenant_id, order_id=order_id)
        if not order.lines:
            raise ConflictError("There is nothing on this order to bill.")
        if order.pending_lines:
            raise ConflictError("Send the pending lines to the kitchen before billing.")
        order.status = OrderStatus.BILLED
        order.billed_at = order.billed_at or utcnow()
        stored = await self._orders.replace(order)
        logger.info(
            "order billed: tenant=%s number=%d by=%s", tenant_id, stored.number, actor.user.email
        )
        return stored

    async def close(self, *, tenant_id: ObjectId, order_id: ObjectId, actor: AuthContext) -> Order:
        """The counter has been paid. The table is free."""
        order = await self.get(tenant_id=tenant_id, order_id=order_id)
        if order.status is OrderStatus.CLOSED:
            return order
        if order.status is not OrderStatus.BILLED:
            raise ConflictError("Print the bill before marking it paid.")
        order.status = OrderStatus.CLOSED
        order.closed_at = utcnow()
        stored = await self._orders.replace(order)
        logger.info(
            "order closed: tenant=%s number=%d by=%s", tenant_id, stored.number, actor.user.email
        )
        return stored

    async def cancel(self, *, tenant_id: ObjectId, order_id: ObjectId, actor: AuthContext) -> Order:
        """Void the order. Allowed until it is paid; a paid order is history, not a mistake."""
        order = await self.get(tenant_id=tenant_id, order_id=order_id)
        if order.status is OrderStatus.CANCELLED:
            return order
        if order.status is OrderStatus.CLOSED:
            raise ConflictError("A paid order cannot be cancelled.")
        order.status = OrderStatus.CANCELLED
        order.cancelled_at = utcnow()
        stored = await self._orders.replace(order)
        logger.warning(
            "order cancelled: tenant=%s number=%d sent_kots=%d by=%s",
            tenant_id,
            stored.number,
            len(stored.kot_ids),
            actor.user.email,
        )
        return stored

    # ------------------------------------------------------------------ helpers

    async def _writable(self, *, tenant_id: ObjectId, order_id: ObjectId) -> Order:
        """An order that may still change. Billed, paid and cancelled ones may not."""
        order = await self.get(tenant_id=tenant_id, order_id=order_id)
        if order.status is not OrderStatus.OPEN:
            raise ConflictError(f"This order is {order.status.value} and cannot be changed.")
        return order

    @staticmethod
    def _pending_line(order: Order, line_id: str) -> OrderLine:
        line = next((line for line in order.lines if line.id == line_id), None)
        if line is None:
            raise NotFoundError("That line is not on the order.")
        if line.sent:
            raise ConflictError("That line has gone to the kitchen and cannot be changed here.")
        return line

    @staticmethod
    def _line_from(request: LineRequest, item: MenuItem) -> OrderLine:
        """Snapshot a menu item into a line, resolving the chosen variation's price."""
        assert item.id is not None
        variation: LineVariation | None = None
        unit_price = item.price
        if request.variation:
            chosen = next(
                (v for v in item.variations if v.name.casefold() == request.variation.casefold()),
                None,
            )
            if chosen is None:
                raise ValidationFailedError(
                    f"'{item.name}' does not come as '{request.variation}'."
                )
            variation = LineVariation(name=chosen.name, price=chosen.price)
            unit_price = chosen.price
        elif item.variations:
            raise ValidationFailedError(f"Choose how '{item.name}' should come.")
        return OrderLine(
            id=request.line_id,
            item_id=item.id,
            name=item.name,
            variation=variation,
            quantity=request.quantity,
            unit_price=unit_price,
            note=request.note,
        )

    @staticmethod
    def _validated(order: Order) -> Order:
        try:
            return Order.model_validate(order.model_dump(by_alias=True))
        except ValidationError as exc:
            raise ValidationFailedError(_first_message(exc)) from exc


def _first_message(error: ValidationError) -> str:
    for item in error.errors():
        message = str(item.get("msg", "")).removeprefix("Value error, ").strip()
        if message:
            return message
    return "That order could not be saved"


__all__ = ["LineRequest", "OrderService"]
