import json
import os
from pathlib import Path

import aiosqlite

DB_PATH = Path(os.environ.get("SIGNAGE_DB_PATH", Path(__file__).parent.parent / "signage.db"))

DEFAULT_SETTINGS = {
    "rotation_interval_seconds": "60",
}


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS slides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                name TEXT NOT NULL,
                position INTEGER NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                config TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        for key, value in DEFAULT_SETTINGS.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value)
            )
        await db.commit()


def _row_to_slide(row: aiosqlite.Row) -> dict:
    return {
        "id": row["id"],
        "type": row["type"],
        "name": row["name"],
        "position": row["position"],
        "enabled": bool(row["enabled"]),
        "config": json.loads(row["config"]),
    }


async def list_slides(enabled_only: bool = False) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM slides"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY position ASC"
        async with db.execute(query) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_slide(row) for row in rows]


async def get_slide(slide_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM slides WHERE id = ?", (slide_id,)) as cursor:
            row = await cursor.fetchone()
            return _row_to_slide(row) if row else None


async def add_slide(slide_type: str, name: str, config: dict) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM slides") as cursor:
            (next_position,) = await cursor.fetchone()
        cursor = await db.execute(
            "INSERT INTO slides (type, name, position, enabled, config) VALUES (?, ?, ?, 1, ?)",
            (slide_type, name, next_position, json.dumps(config)),
        )
        await db.commit()
        return cursor.lastrowid


async def update_slide(slide_id: int, name: str, config: dict) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE slides SET name = ?, config = ? WHERE id = ?",
            (name, json.dumps(config), slide_id),
        )
        await db.commit()


async def delete_slide(slide_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM slides WHERE id = ?", (slide_id,))
        await db.commit()


async def toggle_slide(slide_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE slides SET enabled = 1 - enabled WHERE id = ?", (slide_id,)
        )
        await db.commit()


async def move_slide(slide_id: int, direction: str) -> None:
    slides = await list_slides()
    ids = [s["id"] for s in slides]
    idx = ids.index(slide_id)
    swap_idx = idx - 1 if direction == "up" else idx + 1
    if swap_idx < 0 or swap_idx >= len(slides):
        return
    a, b = slides[idx], slides[swap_idx]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE slides SET position = ? WHERE id = ?", (b["position"], a["id"]))
        await db.execute("UPDATE slides SET position = ? WHERE id = ?", (a["position"], b["id"]))
        await db.commit()


async def get_setting(key: str, default: str | None = None) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else default


async def set_setting(key: str, value: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()
