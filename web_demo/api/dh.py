from __future__ import annotations

import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure sibling package "admin_backend" can be imported when running
# "python web_demo/server_realtime.py".
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from admin_backend.db.database import get_session  # noqa: E402
from admin_backend.db.models import DigitalHuman  # noqa: E402

VIDEO_DATA_DIR = PROJECT_ROOT / "video_data"
ACTIVE_DH_FILE = VIDEO_DATA_DIR / "active_dh.txt"

router = APIRouter(prefix="/api/dh", tags=["digital-human"])


class DigitalHumanOut(BaseModel):
    id: int
    uuid: str
    name: str
    asset_path: str
    thumbnail_path: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DigitalHumanCreateIn(BaseModel):
    uuid: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=100)
    asset_path: str = Field(..., min_length=1, max_length=512)
    thumbnail_path: Optional[str] = Field(default=None, max_length=512)
    is_active: bool = False


class DigitalHumanUpdateIn(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    asset_path: Optional[str] = Field(default=None, min_length=1, max_length=512)
    thumbnail_path: Optional[str] = Field(default=None, max_length=512)
    is_active: Optional[bool] = None


def _to_out(row: DigitalHuman) -> DigitalHumanOut:
    return DigitalHumanOut(
        id=row.id,
        uuid=row.uuid,
        name=row.name,
        asset_path=row.asset_path,
        thumbnail_path=row.thumbnail_path,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _persist_active_uuid(dh_uuid: Optional[str]) -> None:
    VIDEO_DATA_DIR.mkdir(parents=True, exist_ok=True)
    if dh_uuid:
        ACTIVE_DH_FILE.write_text(dh_uuid, encoding="utf-8")
        return
    if ACTIVE_DH_FILE.exists():
        ACTIVE_DH_FILE.unlink()


async def _set_only_active(
    session: AsyncSession,
    active_uuid: str,
) -> None:
    await session.execute(
        update(DigitalHuman).values(is_active=False).where(DigitalHuman.uuid != active_uuid)
    )
    await session.execute(
        update(DigitalHuman).values(is_active=True).where(DigitalHuman.uuid == active_uuid)
    )


@router.get("", response_model=list[DigitalHumanOut])
async def list_digital_humans(session: AsyncSession = Depends(get_session)) -> list[DigitalHumanOut]:
    rows = (
        await session.execute(
            select(DigitalHuman).order_by(DigitalHuman.created_at.desc(), DigitalHuman.id.desc())
        )
    ).scalars().all()
    return [_to_out(row) for row in rows]


@router.get("/active", response_model=DigitalHumanOut)
async def get_active_digital_human(session: AsyncSession = Depends(get_session)) -> DigitalHumanOut:
    row = await session.scalar(select(DigitalHuman).where(DigitalHuman.is_active.is_(True)))
    if not row:
        raise HTTPException(status_code=404, detail="No active digital human")
    return _to_out(row)


@router.get("/{dh_uuid}", response_model=DigitalHumanOut)
async def get_digital_human(dh_uuid: str, session: AsyncSession = Depends(get_session)) -> DigitalHumanOut:
    row = await session.scalar(select(DigitalHuman).where(DigitalHuman.uuid == dh_uuid))
    if not row:
        raise HTTPException(status_code=404, detail=f"Digital human not found: {dh_uuid}")
    return _to_out(row)


@router.post("", response_model=DigitalHumanOut)
async def create_digital_human(
    payload: DigitalHumanCreateIn,
    session: AsyncSession = Depends(get_session),
) -> DigitalHumanOut:
    dh_uuid = payload.uuid or str(uuid.uuid4())

    existing = await session.scalar(select(DigitalHuman).where(DigitalHuman.uuid == dh_uuid))
    if existing:
        raise HTTPException(status_code=409, detail=f"Digital human uuid already exists: {dh_uuid}")

    row = DigitalHuman(
        uuid=dh_uuid,
        name=payload.name,
        asset_path=payload.asset_path,
        thumbnail_path=payload.thumbnail_path,
        is_active=payload.is_active,
    )
    session.add(row)
    await session.flush()

    if payload.is_active:
        await _set_only_active(session, dh_uuid)
        _persist_active_uuid(dh_uuid)

    await session.commit()
    await session.refresh(row)
    return _to_out(row)


@router.put("/{dh_uuid}", response_model=DigitalHumanOut)
async def update_digital_human(
    dh_uuid: str,
    payload: DigitalHumanUpdateIn,
    session: AsyncSession = Depends(get_session),
) -> DigitalHumanOut:
    row = await session.scalar(select(DigitalHuman).where(DigitalHuman.uuid == dh_uuid))
    if not row:
        raise HTTPException(status_code=404, detail=f"Digital human not found: {dh_uuid}")

    was_active = row.is_active

    if payload.name is not None:
        row.name = payload.name
    if payload.asset_path is not None:
        row.asset_path = payload.asset_path
    if payload.thumbnail_path is not None:
        row.thumbnail_path = payload.thumbnail_path
    if payload.is_active is not None:
        row.is_active = payload.is_active

    if payload.is_active is True:
        await _set_only_active(session, dh_uuid)
        _persist_active_uuid(dh_uuid)
    elif payload.is_active is False and was_active:
        current_active = await session.scalar(
            select(DigitalHuman).where(DigitalHuman.is_active.is_(True))
        )
        if not current_active:
            _persist_active_uuid(None)

    await session.commit()
    await session.refresh(row)
    return _to_out(row)


@router.post("/{dh_uuid}/activate", response_model=DigitalHumanOut)
async def activate_digital_human(
    dh_uuid: str,
    session: AsyncSession = Depends(get_session),
) -> DigitalHumanOut:
    row = await session.scalar(select(DigitalHuman).where(DigitalHuman.uuid == dh_uuid))
    if not row:
        raise HTTPException(status_code=404, detail=f"Digital human not found: {dh_uuid}")

    await _set_only_active(session, dh_uuid)
    _persist_active_uuid(dh_uuid)

    await session.commit()
    await session.refresh(row)
    return _to_out(row)


@router.delete("/{dh_uuid}")
async def delete_digital_human(dh_uuid: str, session: AsyncSession = Depends(get_session)) -> dict:
    row = await session.scalar(select(DigitalHuman).where(DigitalHuman.uuid == dh_uuid))
    if not row:
        raise HTTPException(status_code=404, detail=f"Digital human not found: {dh_uuid}")

    was_active = row.is_active
    await session.delete(row)
    await session.commit()

    if was_active:
        _persist_active_uuid(None)

    return {"deleted": dh_uuid}
