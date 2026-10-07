from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from dobrolap_bot.config.loader import Catalog
from dobrolap_bot.domain.enums import BookingStatus, FeedingOption
from dobrolap_bot.domain.models import PetProfile, PriceQuote
from dobrolap_bot.integrations.google_sheets import SheetsGateway
from dobrolap_bot.repositories.sqlite import BookingRecord, SqliteRepository
from dobrolap_bot.services.placement import PlacementService
from dobrolap_bot.services.pricing import PricingService

_ALLOWED: dict[BookingStatus, set[BookingStatus]] = {
    BookingStatus.DRAFT: {
        BookingStatus.WAITING_OWNER,
        BookingStatus.CANCELLED,
    },
    BookingStatus.WAITING_OWNER: {
        BookingStatus.OWNER_APPROVED,
        BookingStatus.OWNER_REJECTED,
        BookingStatus.CANCELLED,
        BookingStatus.EXPIRED,
        BookingStatus.DRAFT,
    },
    BookingStatus.OWNER_APPROVED: {
        BookingStatus.WAITING_PAYMENT,
        BookingStatus.CANCELLED,
        BookingStatus.EXPIRED,
        BookingStatus.WAITING_OWNER,
    },
    BookingStatus.WAITING_PAYMENT: {
        BookingStatus.CONFIRMED,
        BookingStatus.CANCELLED,
        BookingStatus.EXPIRED,
        BookingStatus.WAITING_OWNER,
    },
    BookingStatus.CONFIRMED: {
        BookingStatus.CANCELLED,
    },
    BookingStatus.OWNER_REJECTED: set(),
    BookingStatus.CANCELLED: set(),
    BookingStatus.EXPIRED: set(),
}


class InvalidTransitionError(ValueError):
    pass


def can_transition(current: BookingStatus, new: BookingStatus) -> bool:
    if current == new:
        return True
    return new in _ALLOWED.get(current, set())


def transition(current: BookingStatus, new: BookingStatus) -> BookingStatus:
    if not can_transition(current, new):
        raise InvalidTransitionError(f"{current} → {new} is not allowed")
    return new


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BookingService:
    """Orchestrates booking lifecycle across SQLite, placement, pricing and Sheets."""

    def __init__(
        self,
        *,
        repo: SqliteRepository,
        catalog: Catalog,
        sheets: SheetsGateway,
    ) -> None:
        self.repo = repo
        self.catalog = catalog
        self.sheets = sheets
        self.placement = PlacementService(catalog)
        self.pricing = PricingService(catalog)

    def sheet_labels(self, unit_id: str) -> list[str]:
        """Calendar row label(s) for a catalog unit (pool-aware)."""
        acc = self.catalog.get_accommodation(unit_id)
        if acc is None:
            return [unit_id]
        return acc.calendar_labels()

    def sheet_label(self, unit_id: str) -> str:
        """Primary calendar label (first pool slot)."""
        labels = self.sheet_labels(unit_id)
        return labels[0] if labels else unit_id

    def resolve_free_sheet_label(
        self,
        unit_id: str,
        date_from: date,
        date_to: date,
        *,
        exclude_booking_id: str | None = None,
    ) -> str:
        """Pick first free calendar row for catalog unit; raise if pool full."""
        occupied = {
            x.strip().lower()
            for x in self.sheets.occupied_unit_ids(
                date_from, date_to, exclude_booking_id=exclude_booking_id
            )
        }
        for label in self.sheet_labels(unit_id):
            if label.strip().lower() not in occupied:
                return label
        raise ValueError("unit_occupied")

    def occupied_catalog_ids(
        self,
        date_from: date,
        date_to: date,
        *,
        exclude_booking_id: str | None = None,
    ) -> set[str]:
        """Catalog units with no free calendar slot in the range."""
        occupied_labels = {
            x.strip().lower()
            for x in self.sheets.occupied_unit_ids(
                date_from, date_to, exclude_booking_id=exclude_booking_id
            )
        }
        out: set[str] = set()
        for acc in self.catalog.accommodations:
            labels = [x.strip().lower() for x in acc.calendar_labels()]
            if not labels:
                continue
            # Pool: unit is unavailable only when every slot is busy.
            if all(label in occupied_labels for label in labels):
                out.add(acc.id)
        return out

    async def submit_booking(
        self,
        *,
        telegram_user_id: int,
        customer_name: str | None,
        username: str | None,
        consent_at: datetime | None,
        date_from: date,
        date_to: date,
        pets: list[PetProfile],
        unit_id: str | None,
        feeding: FeedingOption | None,
        service_ids: list[str],
        placement_flags: list[str],
        manual_matching: bool,
        promo_code: str | None = None,
    ) -> tuple[BookingRecord, PriceQuote | None]:
        customer_id = await self.repo.upsert_customer(
            telegram_user_id=telegram_user_id,
            name=customer_name or username,
            contact=f"@{username}" if username else None,
            consent_at=consent_at,
        )

        quote: PriceQuote | None = None
        unit = self.catalog.get_accommodation(unit_id) if unit_id else None
        if unit is not None and unit_id is not None:
            occupied = self.occupied_catalog_ids(date_from, date_to)
            if unit_id in occupied:
                raise ValueError("selected_unit_occupied")
            quote = self.pricing.quote(
                pets=pets,
                unit=unit,
                date_from=date_from,
                date_to=date_to,
                feeding=feeding,
                service_ids=service_ids,
                promo_code=promo_code,
            )

        now = _utcnow()
        booking_id = uuid.uuid4().hex[:12]
        payload: dict[str, Any] = {
            "pets": [p.model_dump(mode="json") for p in pets],
            "feeding": feeding.value if feeding else None,
            "service_ids": service_ids,
            "placement_flags": placement_flags,
            "manual_matching": manual_matching,
            "promo_code": promo_code,
            "quote_lines": [ln.model_dump(mode="json") for ln in quote.lines] if quote else [],
            "quote_explanation": quote.explanation if quote else None,
            "quote_provisional": quote.provisional if quote else True,
            "client_username": username,
            "receipt_file_ids": [],
            "owner_messages": [],
        }
        record = BookingRecord(
            id=booking_id,
            customer_id=customer_id,
            date_from=date_from,
            date_to=date_to,
            status=BookingStatus.WAITING_OWNER,
            unit_id=unit_id,
            price_total=quote.total_rub if quote else None,
            deposit_amount=(
                quote.deposit_rub
                if quote
                else self.pricing.deposit_amount(len(pets) or 1)
            ),
            owner_note=None,
            sheet_external_id=booking_id,
            payload=payload,
            created_at=now,
            updated_at=now,
            customer_telegram_id=telegram_user_id,
            customer_name=customer_name or username,
        )
        await self.repo.save_booking(record)
        return record, quote

    async def get(self, booking_id: str) -> BookingRecord | None:
        return await self.repo.get_booking(booking_id)

    async def _set_status(
        self,
        booking: BookingRecord,
        new_status: BookingStatus,
        *,
        extra_payload: dict[str, Any] | None = None,
        unit_id: str | None = None,
        price_total: int | None = None,
        deposit_amount: int | None = None,
        owner_note: str | None = None,
    ) -> BookingRecord:
        booking.status = transition(booking.status, new_status)
        booking.updated_at = _utcnow()
        if extra_payload:
            booking.payload = {**booking.payload, **extra_payload}
        if unit_id is not None:
            booking.unit_id = unit_id
        if price_total is not None:
            booking.price_total = price_total
        if deposit_amount is not None:
            booking.deposit_amount = deposit_amount
        if owner_note is not None:
            booking.owner_note = owner_note
        await self.repo.save_booking(booking)
        return booking

    async def approve(self, booking_id: str) -> BookingRecord:
        booking = await self._require(booking_id)
        sheet_label: str | None = None
        if booking.unit_id:
            try:
                sheet_label = self.resolve_free_sheet_label(
                    booking.unit_id,
                    booking.date_from,
                    booking.date_to,
                    exclude_booking_id=booking.id,
                )
                self.sheets.reserve_booking(
                    booking_id=booking.id,
                    unit_id=sheet_label,
                    date_from=booking.date_from,
                    date_to=booking.date_to,
                    status=BookingStatus.WAITING_PAYMENT.value,
                )
            except ValueError as exc:
                if "unit_occupied" in str(exc):
                    raise ValueError("unit_occupied_on_approve") from exc
                raise

        extra = {"sheet_label": sheet_label} if sheet_label else None
        booking = await self._set_status(
            booking, BookingStatus.OWNER_APPROVED, extra_payload=extra
        )
        booking = await self._set_status(booking, BookingStatus.WAITING_PAYMENT)
        return booking

    async def reject(self, booking_id: str, reason: str | None = None) -> BookingRecord:
        booking = await self._require(booking_id)
        booking = await self._set_status(
            booking,
            BookingStatus.OWNER_REJECTED,
            owner_note=reason,
            extra_payload={"reject_reason": reason},
        )
        held = booking.payload.get("sheet_label")
        self.sheets.release_booking(
            booking_id=booking.id,
            unit_id=held or (self.sheet_label(booking.unit_id) if booking.unit_id else None),
        )
        return booking

    async def cancel(self, booking_id: str, reason: str | None = None) -> BookingRecord:
        booking = await self._require(booking_id)
        booking = await self._set_status(
            booking,
            BookingStatus.CANCELLED,
            owner_note=reason,
            extra_payload={"cancel_reason": reason},
        )
        held = booking.payload.get("sheet_label")
        self.sheets.release_booking(
            booking_id=booking.id,
            unit_id=held or (self.sheet_label(booking.unit_id) if booking.unit_id else None),
        )
        return booking

    async def add_owner_question(self, booking_id: str, text: str) -> BookingRecord:
        booking = await self._require(booking_id)
        messages = list(booking.payload.get("owner_messages") or [])
        messages.append({"role": "owner", "text": text, "at": _utcnow().isoformat()})
        booking.payload = {**booking.payload, "owner_messages": messages}
        booking.updated_at = _utcnow()
        await self.repo.save_booking(booking)
        return booking

    async def add_client_reply(self, booking_id: str, text: str) -> BookingRecord:
        booking = await self._require(booking_id)
        messages = list(booking.payload.get("owner_messages") or [])
        messages.append({"role": "client", "text": text, "at": _utcnow().isoformat()})
        booking.payload = {**booking.payload, "owner_messages": messages}
        booking.updated_at = _utcnow()
        await self.repo.save_booking(booking)
        return booking

    async def suggest_unit(self, booking_id: str, unit_id: str) -> tuple[BookingRecord, PriceQuote]:
        booking = await self._require(booking_id)
        unit = self.catalog.get_accommodation(unit_id)
        if unit is None:
            raise ValueError("unknown_unit")
        occupied = self.occupied_catalog_ids(
            booking.date_from,
            booking.date_to,
            exclude_booking_id=booking.id,
        )
        if unit_id in occupied:
            raise ValueError("unit_occupied")

        pets = [PetProfile.model_validate(p) for p in booking.payload.get("pets") or []]
        feeding_raw = booking.payload.get("feeding")
        feeding = FeedingOption(feeding_raw) if feeding_raw else None
        service_ids = list(booking.payload.get("service_ids") or [])
        quote = self.pricing.quote(
            pets=pets,
            unit=unit,
            date_from=booking.date_from,
            date_to=booking.date_to,
            feeding=feeding,
            service_ids=service_ids,
            promo_code=booking.payload.get("promo_code"),
        )
        target = BookingStatus.WAITING_OWNER
        if booking.status != target and not can_transition(booking.status, target):
            raise InvalidTransitionError(f"{booking.status} → {target} is not allowed")
        booking.status = target
        booking.unit_id = unit_id
        booking.price_total = quote.total_rub
        booking.deposit_amount = quote.deposit_rub
        booking.payload = {
            **booking.payload,
            "quote_lines": [ln.model_dump(mode="json") for ln in quote.lines],
            "quote_explanation": quote.explanation,
            "quote_provisional": quote.provisional,
            "suggested_by_owner": True,
            "manual_matching": False,
        }
        booking.updated_at = _utcnow()
        await self.repo.save_booking(booking)
        return booking, quote

    async def attach_receipt(self, booking_id: str, file_id: str) -> BookingRecord:
        booking = await self._require(booking_id)
        if booking.status != BookingStatus.WAITING_PAYMENT:
            raise InvalidTransitionError("receipt only accepted in WAITING_PAYMENT")
        receipts = list(booking.payload.get("receipt_file_ids") or [])
        receipts.append(file_id)
        booking.payload = {**booking.payload, "receipt_file_ids": receipts}
        booking.updated_at = _utcnow()
        await self.repo.save_booking(booking)
        return booking

    async def confirm_payment(self, booking_id: str) -> BookingRecord:
        booking = await self._require(booking_id)
        receipts = list(booking.payload.get("receipt_file_ids") or [])
        if not receipts:
            raise ValueError("receipt_required")
        if booking.unit_id:
            label = booking.payload.get("sheet_label") or self.resolve_free_sheet_label(
                booking.unit_id,
                booking.date_from,
                booking.date_to,
                exclude_booking_id=booking.id,
            )
            self.sheets.reserve_booking(
                booking_id=booking.id,
                unit_id=label,
                date_from=booking.date_from,
                date_to=booking.date_to,
                status=BookingStatus.CONFIRMED.value,
            )
        return await self._set_status(booking, BookingStatus.CONFIRMED)

    async def _require(self, booking_id: str) -> BookingRecord:
        booking = await self.repo.get_booking(booking_id)
        if booking is None:
            raise KeyError(booking_id)
        return booking
