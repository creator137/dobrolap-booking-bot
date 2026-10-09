"""SQLite persistence for customers and bookings."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import aiosqlite

from dobrolap_bot.domain.enums import BookingStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL UNIQUE,
    name TEXT,
    contact TEXT,
    consent_at TEXT
);

CREATE TABLE IF NOT EXISTS bookings (
    id TEXT PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    date_from TEXT NOT NULL,
    date_to TEXT NOT NULL,
    status TEXT NOT NULL,
    unit_id TEXT,
    price_total INTEGER,
    deposit_amount INTEGER,
    owner_note TEXT,
    sheet_external_id TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    hold_expires_at TEXT,
    last_reminder_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);
CREATE INDEX IF NOT EXISTS idx_bookings_customer ON bookings(customer_id);
CREATE INDEX IF NOT EXISTS idx_bookings_hold ON bookings(status, hold_expires_at);
"""

MIGRATIONS = [
    "ALTER TABLE bookings ADD COLUMN hold_expires_at TEXT",
    "ALTER TABLE bookings ADD COLUMN last_reminder_at TEXT",
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class BookingRecord:
    id: str
    customer_id: int
    date_from: date
    date_to: date
    status: BookingStatus
    unit_id: str | None
    price_total: int | None
    deposit_amount: int | None
    owner_note: str | None
    sheet_external_id: str | None
    payload: dict = field(default_factory=dict)
    hold_expires_at: datetime | None = None
    last_reminder_at: datetime | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    customer_telegram_id: int | None = None
    customer_name: str | None = None
    customer_contact: str | None = None


class SqliteRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        for sql in MIGRATIONS:
            try:
                await self._db.execute(sql)
            except aiosqlite.OperationalError:
                pass  # column already exists
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SqliteRepository is not open")
        return self._db

    async def upsert_customer(
        self,
        *,
        telegram_user_id: int,
        name: str | None = None,
        contact: str | None = None,
        consent_at: datetime | None = None,
    ) -> int:
        await self.db.execute(
            """
            INSERT INTO customers (telegram_user_id, name, contact, consent_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET
                name = COALESCE(excluded.name, customers.name),
                contact = COALESCE(excluded.contact, customers.contact),
                consent_at = COALESCE(excluded.consent_at, customers.consent_at)
            """,
            (
                telegram_user_id,
                name,
                contact,
                consent_at.isoformat() if consent_at else None,
            ),
        )
        cur = await self.db.execute(
            "SELECT id FROM customers WHERE telegram_user_id = ?", (telegram_user_id,)
        )
        row = await cur.fetchone()
        await self.db.commit()
        return int(row["id"])

    async def get_customer_telegram_id(self, customer_id: int) -> int | None:
        cur = await self.db.execute(
            "SELECT telegram_user_id FROM customers WHERE id = ?",
            (customer_id,),
        )
        row = await cur.fetchone()
        return int(row["telegram_user_id"]) if row else None

    async def save_booking(self, record: BookingRecord) -> None:
        await self.db.execute(
            """
            INSERT INTO bookings (
                id, customer_id, date_from, date_to, status, unit_id,
                price_total, deposit_amount, owner_note, sheet_external_id,
                payload_json, hold_expires_at, last_reminder_at,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                date_from=excluded.date_from,
                date_to=excluded.date_to,
                status=excluded.status,
                unit_id=excluded.unit_id,
                price_total=excluded.price_total,
                deposit_amount=excluded.deposit_amount,
                owner_note=excluded.owner_note,
                sheet_external_id=excluded.sheet_external_id,
                payload_json=excluded.payload_json,
                hold_expires_at=excluded.hold_expires_at,
                last_reminder_at=excluded.last_reminder_at,
                updated_at=excluded.updated_at
            """,
            (
                record.id,
                record.customer_id,
                record.date_from.isoformat(),
                record.date_to.isoformat(),
                record.status.value,
                record.unit_id,
                record.price_total,
                record.deposit_amount,
                record.owner_note,
                record.sheet_external_id,
                json.dumps(record.payload, ensure_ascii=False),
                record.hold_expires_at.isoformat() if record.hold_expires_at else None,
                record.last_reminder_at.isoformat() if record.last_reminder_at else None,
                record.created_at.isoformat(),
                record.updated_at.isoformat(),
            ),
        )
        await self.db.commit()

    async def has_prior_placement(self, customer_id: int) -> bool:
        """Existing active booking or a booking that was confirmed in this bot."""
        cur = await self.db.execute(
            """
            SELECT 1 FROM bookings
            WHERE customer_id = ? AND (
                status IN ('WAITING_OWNER', 'OWNER_APPROVED', 'WAITING_PAYMENT', 'CONFIRMED')
                OR json_extract(payload_json, '$.ever_confirmed') = 1
            ) LIMIT 1
            """,
            (customer_id,),
        )
        return await cur.fetchone() is not None

    async def has_prior_placement_by_telegram(
        self, telegram_user_id: int, contact: str | None = None
    ) -> bool:
        cur = await self.db.execute(
            """
            SELECT 1 FROM bookings b JOIN customers c ON c.id = b.customer_id
            WHERE (c.telegram_user_id = ? OR (? IS NOT NULL AND c.contact = ?))
              AND (b.status IN ('WAITING_OWNER', 'OWNER_APPROVED', 'WAITING_PAYMENT', 'CONFIRMED')
                   OR json_extract(b.payload_json, '$.ever_confirmed') = 1)
            LIMIT 1
            """,
            (telegram_user_id, contact, contact),
        )
        return await cur.fetchone() is not None

    async def save_first_placement_booking(self, record: BookingRecord) -> bool:
        """Atomically claim the first-placement promo across bot processes."""
        async with aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute(
                """
                SELECT 1 FROM bookings b JOIN customers c ON c.id = b.customer_id
                WHERE (b.customer_id = ? OR (c.contact IS NOT NULL AND c.contact = (
                    SELECT contact FROM customers WHERE id = ?)))
                  AND (b.status IN ('WAITING_OWNER', 'OWNER_APPROVED', 'WAITING_PAYMENT', 'CONFIRMED')
                       OR json_extract(b.payload_json, '$.ever_confirmed') = 1)
                LIMIT 1
                """,
                (record.customer_id, record.customer_id),
            )
            if await cur.fetchone():
                await db.rollback()
                return False
            await db.execute(
                """
                INSERT INTO bookings (
                    id, customer_id, date_from, date_to, status, unit_id,
                    price_total, deposit_amount, owner_note, sheet_external_id,
                    payload_json, hold_expires_at, last_reminder_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id, record.customer_id, record.date_from.isoformat(),
                    record.date_to.isoformat(), record.status.value, record.unit_id,
                    record.price_total, record.deposit_amount, record.owner_note,
                    record.sheet_external_id, json.dumps(record.payload, ensure_ascii=False),
                    None, None, record.created_at.isoformat(), record.updated_at.isoformat(),
                ),
            )
            await db.commit()
            return True

    async def save_booking_if_status(
        self, record: BookingRecord, *, expected_status: BookingStatus
    ) -> bool:
        """Atomic status write. Returns False if status changed concurrently."""
        cur = await self.db.execute(
            """
            UPDATE bookings SET
                date_from=?, date_to=?, status=?, unit_id=?,
                price_total=?, deposit_amount=?, owner_note=?, sheet_external_id=?,
                payload_json=?, hold_expires_at=?, last_reminder_at=?, updated_at=?
            WHERE id=? AND status=?
            """,
            (
                record.date_from.isoformat(),
                record.date_to.isoformat(),
                record.status.value,
                record.unit_id,
                record.price_total,
                record.deposit_amount,
                record.owner_note,
                record.sheet_external_id,
                json.dumps(record.payload, ensure_ascii=False),
                record.hold_expires_at.isoformat() if record.hold_expires_at else None,
                record.last_reminder_at.isoformat() if record.last_reminder_at else None,
                record.updated_at.isoformat(),
                record.id,
                expected_status.value,
            ),
        )
        await self.db.commit()
        return cur.rowcount > 0

    async def list_waiting_payment_holds(self) -> list[BookingRecord]:
        cur = await self.db.execute(
            """
            SELECT b.*, c.telegram_user_id AS customer_telegram_id,
                   c.name AS customer_name, c.contact AS customer_contact
            FROM bookings b
            JOIN customers c ON c.id = b.customer_id
            WHERE b.status = ?
            ORDER BY CASE WHEN b.hold_expires_at IS NULL THEN 1 ELSE 0 END,
                     b.hold_expires_at ASC
            """,
            (BookingStatus.WAITING_PAYMENT.value,),
        )
        return [self._from_row(row) for row in await cur.fetchall()]

    async def get_booking(self, booking_id: str) -> BookingRecord | None:
        cur = await self.db.execute(
            """
            SELECT b.*, c.telegram_user_id AS customer_telegram_id,
                   c.name AS customer_name, c.contact AS customer_contact
            FROM bookings b
            JOIN customers c ON c.id = b.customer_id
            WHERE b.id = ?
            """,
            (booking_id,),
        )
        row = await cur.fetchone()
        return self._from_row(row) if row else None

    async def find_latest_by_telegram(
        self,
        telegram_user_id: int,
        *,
        statuses: list[BookingStatus] | None = None,
    ) -> BookingRecord | None:
        sql = """
            SELECT b.*, c.telegram_user_id AS customer_telegram_id,
                   c.name AS customer_name, c.contact AS customer_contact
            FROM bookings b
            JOIN customers c ON c.id = b.customer_id
            WHERE c.telegram_user_id = ?
        """
        params: list = [telegram_user_id]
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            sql += f" AND b.status IN ({placeholders})"
            params.extend(s.value for s in statuses)
        sql += " ORDER BY b.updated_at DESC LIMIT 1"
        cur = await self.db.execute(sql, params)
        row = await cur.fetchone()
        return self._from_row(row) if row else None

    async def list_by_telegram(
        self, telegram_user_id: int, *, statuses: list[BookingStatus]
    ) -> list[BookingRecord]:
        if not statuses:
            return []
        placeholders = ",".join("?" for _ in statuses)
        cur = await self.db.execute(
            f"""
            SELECT b.*, c.telegram_user_id AS customer_telegram_id,
                   c.name AS customer_name, c.contact AS customer_contact
            FROM bookings b
            JOIN customers c ON c.id = b.customer_id
            WHERE c.telegram_user_id = ? AND b.status IN ({placeholders})
            ORDER BY b.updated_at DESC
            """,
            [telegram_user_id, *(status.value for status in statuses)],
        )
        return [self._from_row(row) for row in await cur.fetchall()]

    async def list_bookings(
        self,
        *,
        statuses: list[BookingStatus] | None = None,
        limit: int = 30,
    ) -> list[BookingRecord]:
        sql = """
            SELECT b.*, c.telegram_user_id AS customer_telegram_id,
                   c.name AS customer_name, c.contact AS customer_contact
            FROM bookings b
            JOIN customers c ON c.id = b.customer_id
        """
        params: list = []
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            sql += f" WHERE b.status IN ({placeholders})"
            params.extend(s.value for s in statuses)
        sql += " ORDER BY b.updated_at DESC LIMIT ?"
        params.append(limit)
        cur = await self.db.execute(sql, params)
        return [self._from_row(row) for row in await cur.fetchall()]

    async def count_by_status(self) -> dict[str, int]:
        cur = await self.db.execute(
            "SELECT status, COUNT(*) AS n FROM bookings GROUP BY status"
        )
        return {str(row["status"]): int(row["n"]) for row in await cur.fetchall()}

    async def list_customers(self, *, limit: int = 40) -> list[dict]:
        cur = await self.db.execute(
            """
            SELECT
                c.id,
                c.telegram_user_id,
                c.name,
                c.contact,
                COUNT(b.id) AS bookings_total,
                SUM(CASE WHEN b.status IN (
                    'WAITING_OWNER', 'OWNER_APPROVED', 'WAITING_PAYMENT', 'CONFIRMED'
                ) THEN 1 ELSE 0 END) AS bookings_active
            FROM customers c
            LEFT JOIN bookings b ON b.customer_id = c.id
            GROUP BY c.id
            ORDER BY COALESCE(MAX(b.updated_at), c.consent_at, '') DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cur.fetchall()
        return [
            {
                "id": int(row["id"]),
                "telegram_user_id": int(row["telegram_user_id"]),
                "name": row["name"],
                "contact": row["contact"],
                "bookings_total": int(row["bookings_total"] or 0),
                "bookings_active": int(row["bookings_active"] or 0),
            }
            for row in rows
        ]

    def _from_row(self, row: aiosqlite.Row) -> BookingRecord:
        keys = row.keys()

        def _dt(col: str) -> datetime | None:
            if col not in keys:
                return None
            raw = row[col]
            return datetime.fromisoformat(raw) if raw else None

        return BookingRecord(
            id=row["id"],
            customer_id=row["customer_id"],
            date_from=date.fromisoformat(row["date_from"]),
            date_to=date.fromisoformat(row["date_to"]),
            status=BookingStatus(row["status"]),
            unit_id=row["unit_id"],
            price_total=row["price_total"],
            deposit_amount=row["deposit_amount"],
            owner_note=row["owner_note"],
            sheet_external_id=row["sheet_external_id"],
            payload=json.loads(row["payload_json"] or "{}"),
            hold_expires_at=_dt("hold_expires_at"),
            last_reminder_at=_dt("last_reminder_at"),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            customer_telegram_id=(
                int(row["customer_telegram_id"]) if "customer_telegram_id" in keys else None
            ),
            customer_name=row["customer_name"] if "customer_name" in keys else None,
            customer_contact=(
                row["customer_contact"] if "customer_contact" in keys else None
            ),
        )
