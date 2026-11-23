import json
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from app.models.schemas import RunState, Vault


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.db: aiosqlite.Connection | None = None

    async def open(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(self.path)
        await self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS vault (
                id INTEGER PRIMARY KEY CHECK(id=1), facts TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, updated TEXT NOT NULL, status TEXT NOT NULL,
                url TEXT NOT NULL, goal TEXT NOT NULL, audit TEXT NOT NULL
            );
        """)

    async def close(self):
        if self.db:
            await self.db.close()

    async def vault(self) -> Vault:
        async with self.db.execute("SELECT facts FROM vault WHERE id=1") as cursor:
            row = await cursor.fetchone()
        return Vault.model_validate_json(row[0]) if row else Vault()

    async def save_vault(self, vault: Vault) -> Vault:
        await self.db.execute("INSERT INTO vault VALUES(1, ?) ON CONFLICT(id) DO UPDATE SET facts=excluded.facts",
                              (vault.model_dump_json(),))
        await self.db.commit()
        return vault

    async def save_run(self, state: RunState, changes: list[dict]):
        updated = datetime.now(timezone.utc).isoformat()
        audit = state.model_dump(mode="json", exclude={"approval", "form"})
        audit["changes"] = changes
        await self.db.execute("""
            INSERT INTO runs VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET updated=excluded.updated, status=excluded.status,
            url=excluded.url, audit=excluded.audit
        """, (state.session_id, updated, state.status, state.url, state.goal, json.dumps(audit)))
        await self.db.commit()

    async def history(self) -> list[dict]:
        async with self.db.execute("SELECT id, updated, status, url, goal FROM runs ORDER BY updated DESC LIMIT 40") as cursor:
            rows = await cursor.fetchall()
        return [dict(zip(("session_id", "updated", "status", "url", "goal"), row)) for row in rows]

    async def audit(self, session_id: str) -> dict | None:
        async with self.db.execute("SELECT audit FROM runs WHERE id=?", (session_id,)) as cursor:
            row = await cursor.fetchone()
        return json.loads(row[0]) if row else None
