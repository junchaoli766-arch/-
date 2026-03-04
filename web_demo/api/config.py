from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure sibling package "admin_backend" can be imported when running
# "python web_demo/server_realtime.py".
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from admin_backend.db.database import DB_PATH, get_session  # noqa: E402
from admin_backend.db.models import SystemConfig  # noqa: E402

router = APIRouter(prefix="/api/config", tags=["config"])


class ConfigItemOut(BaseModel):
    key: str
    value: str
    is_sensitive: bool
    description: Optional[str] = None
    has_value: bool
    updated_at: Optional[datetime] = None


class ConfigUpsertIn(BaseModel):
    key: str = Field(..., min_length=1, max_length=100)
    value: str = ""
    is_sensitive: bool = False
    description: Optional[str] = Field(default=None, max_length=500)


class ConfigBatchUpsertIn(BaseModel):
    items: list[ConfigUpsertIn]


def _mask_value(value: str, is_sensitive: bool) -> str:
    if not is_sensitive:
        return value
    return "***" if value else ""


def _db_file_path() -> str:
    env_path = os.environ.get("ADMIN_DB_PATH")
    if env_path:
        return env_path
    return DB_PATH


def load_configs_sync(keys: Iterable[str]) -> dict[str, str]:
    """Synchronous helper for runtime modules (e.g. llm.py)."""
    keys = list(keys)
    if not keys:
        return {}

    db_path = _db_file_path()
    if not os.path.exists(db_path):
        return {}

    placeholders = ",".join("?" for _ in keys)
    sql = f"SELECT key, value FROM system_config WHERE key IN ({placeholders})"
    result: dict[str, str] = {}

    try:
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(sql, keys).fetchall()
            for key, value in rows:
                result[str(key)] = "" if value is None else str(value)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        print(f"[config] read system_config failed: {exc}")

    return result


@router.get("", response_model=list[ConfigItemOut])
async def list_configs(session: AsyncSession = Depends(get_session)) -> list[ConfigItemOut]:
    rows = (
        await session.execute(
            select(SystemConfig).order_by(SystemConfig.key.asc())
        )
    ).scalars().all()

    return [
        ConfigItemOut(
            key=row.key,
            value=_mask_value(row.value, row.is_sensitive),
            is_sensitive=row.is_sensitive,
            description=row.description,
            has_value=bool(row.value),
            updated_at=row.updated_at,
        )
        for row in rows
    ]


@router.get("/{key}", response_model=ConfigItemOut)
async def get_config(key: str, session: AsyncSession = Depends(get_session)) -> ConfigItemOut:
    row = await session.scalar(select(SystemConfig).where(SystemConfig.key == key))
    if not row:
        raise HTTPException(status_code=404, detail=f"Config key not found: {key}")

    return ConfigItemOut(
        key=row.key,
        value=_mask_value(row.value, row.is_sensitive),
        is_sensitive=row.is_sensitive,
        description=row.description,
        has_value=bool(row.value),
        updated_at=row.updated_at,
    )


@router.put("", response_model=ConfigItemOut)
async def upsert_config(
    payload: ConfigUpsertIn,
    session: AsyncSession = Depends(get_session),
) -> ConfigItemOut:
    stmt = sqlite_insert(SystemConfig).values(
        key=payload.key,
        value=payload.value,
        is_sensitive=payload.is_sensitive,
        description=payload.description,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[SystemConfig.key],
        set_={
            "value": payload.value,
            "is_sensitive": payload.is_sensitive,
            "description": payload.description,
        },
    )
    await session.execute(stmt)
    await session.commit()

    row = await session.scalar(select(SystemConfig).where(SystemConfig.key == payload.key))
    assert row is not None
    return ConfigItemOut(
        key=row.key,
        value=_mask_value(row.value, row.is_sensitive),
        is_sensitive=row.is_sensitive,
        description=row.description,
        has_value=bool(row.value),
        updated_at=row.updated_at,
    )


@router.put("/batch")
async def batch_upsert_configs(
    payload: ConfigBatchUpsertIn,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if not payload.items:
        return {"updated": 0}

    for item in payload.items:
        stmt = sqlite_insert(SystemConfig).values(
            key=item.key,
            value=item.value,
            is_sensitive=item.is_sensitive,
            description=item.description,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[SystemConfig.key],
            set_={
                "value": item.value,
                "is_sensitive": item.is_sensitive,
                "description": item.description,
            },
        )
        await session.execute(stmt)

    await session.commit()
    return {"updated": len(payload.items)}

