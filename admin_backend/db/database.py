"""数据库引擎与会话工厂。

负责初始化 SQLite 异步引擎，提供 AsyncSession 依赖注入和
create_all 建表入口。数据库文件默认位于项目根目录 admin.db。
"""

import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

# 数据库文件路径：项目根目录 / admin.db
_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
DB_PATH = os.environ.get(
    "ADMIN_DB_PATH",
    os.path.join(_PROJECT_ROOT, "admin.db"),
)
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

engine = create_async_engine(
    DATABASE_URL,
    echo=False,          # 生产环境关闭 SQL 日志
    future=True,
    connect_args={"check_same_thread": False},
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    """所有 ORM 模型的公共基类。"""


async def init_db() -> None:
    """创建所有表（首次启动或测试时调用）。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入：提供数据库会话，请求结束后自动关闭。

    Yields:
        AsyncSession: 当前请求的数据库会话。
    """
    async with AsyncSessionLocal() as session:
        yield session
