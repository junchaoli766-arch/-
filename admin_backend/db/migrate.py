"""数据迁移脚本：将现有文件系统数据导入 SQLite 数据库。

执行内容
--------
1. 建表   — 调用 init_db()，已存在的表不重建（idempotent）。
2. 导入数字人 — 扫描 video_data/<uuid>/ 目录，将有效条目写入
               digital_humans 表，已存在的记录跳过（不覆盖）。
3. 初始化配置 — 在 system_config 表中写入默认配置键，已存在的键
               保持不变，新键写入占位值（用户需在管理面板中更新）。

设计原则
--------
- 幂等：多次运行结果相同，不会重复插入或覆盖已有数据。
- 只读原文件系统：不修改、不删除任何现有文件。
- 明确报告：打印每一步的结果，方便排查问题。

用法
----
    # 在项目根目录下执行
    python -m admin_backend.db.migrate
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .database import AsyncSessionLocal, init_db
from .models import DigitalHuman, SystemConfig

# ── 路径常量 ──────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
VIDEO_DATA_DIR = _PROJECT_ROOT / "video_data"
ACTIVE_DH_FILE = VIDEO_DATA_DIR / "active_dh.txt"

# ── 系统配置默认值 ─────────────────────────────────────────────────────────
# 占位值说明：
#   - 敏感字段（is_sensitive=True）写入空字符串，提示用户在管理面板中填写。
#   - 非敏感字段使用合理默认值。
#   - 若同名环境变量存在，优先使用环境变量（方便 CI / Docker 场景）。
_DEFAULT_CONFIGS: list[dict] = [
    {
        "key": "llm_api_key",
        "value": os.environ.get("LLM_API_KEY", ""),
        "is_sensitive": True,
        "description": "大语言模型 API Key（DeepSeek / 豆包 / OpenAI 等）",
    },
    {
        "key": "llm_base_url",
        "value": os.environ.get("LLM_BASE_URL", "https://api.deepseek.com"),
        "is_sensitive": False,
        "description": "LLM API 地址（兼容 OpenAI SDK）",
    },
    {
        "key": "llm_model_name",
        "value": os.environ.get("LLM_MODEL_NAME", "deepseek-chat"),
        "is_sensitive": False,
        "description": "LLM 模型名称",
    },
    {
        "key": "llm_enable_search",
        "value": os.environ.get("LLM_ENABLE_SEARCH", "true"),
        "is_sensitive": False,
        "description": "是否启用 LLM 联网搜索（true / false）",
    },
    {
        "key": "asr_model",
        "value": os.environ.get("ASR_MODEL", "zipformer-bilingual"),
        "is_sensitive": False,
        "description": "ASR 模型名称（zipformer-bilingual / sensevoice / paraformer-trilingual）",
    },
    {
        "key": "tts_model",
        "value": os.environ.get("TTS_MODEL", "sherpa-onnx-vits-zh-ll"),
        "is_sensitive": False,
        "description": "TTS 模型名称（sherpa-onnx-vits-zh-ll / vits-zh-hf-theresa / vits-melo-tts-zh_en）",
    },
    {
        "key": "admin_token",
        "value": os.environ.get("ADMIN_TOKEN", ""),
        "is_sensitive": True,
        "description": "管理后台访问令牌（留空则不鉴权，生产环境必须设置）",
    },
]


# ── 工具函数 ──────────────────────────────────────────────────────────────

def _read_active_uuid() -> Optional[str]:
    """读取 active_dh.txt 中记录的当前激活 UUID。

    Returns:
        激活的 UUID 字符串，或 None（文件不存在或内容为空）。
    """
    if ACTIVE_DH_FILE.exists():
        content = ACTIVE_DH_FILE.read_text(encoding="utf-8").strip()
        return content if content else None
    return None


def _parse_created_at(raw: Optional[str]) -> datetime:
    """将 metadata.json 中的时间字符串解析为带时区的 datetime（UTC）。

    metadata.json 中的时间格式为 "YYYY-MM-DD HH:MM:SS"（本地时间无时区）。
    迁移时统一视为 UTC，保留原始值不做转换。

    Args:
        raw: 原始时间字符串，可为 None。

    Returns:
        带 UTC 时区的 datetime 对象，解析失败时返回当前 UTC 时间。
    """
    if not raw:
        return datetime.now(tz=timezone.utc)
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(tz=timezone.utc)


def _scan_video_data() -> list[dict]:
    """扫描 video_data/ 目录，返回所有有效数字人的原始数据列表。

    有效条目必须同时具备：
    - metadata.json（包含 uuid 和 name 字段）
    - assets/ 子目录

    Returns:
        每个元素包含 metadata 内容及目录路径信息的字典列表。
    """
    results: list[dict] = []

    if not VIDEO_DATA_DIR.exists():
        return results

    for item in VIDEO_DATA_DIR.iterdir():
        if not item.is_dir():
            continue

        metadata_path = item / "metadata.json"
        assets_path = item / "assets"

        if not metadata_path.exists() or not assets_path.exists():
            continue

        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  ⚠️  跳过 {item.name}：metadata.json 读取失败 ({exc})")
            continue

        uuid = metadata.get("uuid", "").strip()
        name = metadata.get("name", "").strip()

        if not uuid or not name:
            print(f"  ⚠️  跳过 {item.name}：metadata.json 缺少 uuid 或 name 字段")
            continue

        results.append(
            {
                "uuid": uuid,
                "name": name,
                "asset_path": str(assets_path.resolve()),
                "created_at": _parse_created_at(metadata.get("created_at")),
                "dir_name": item.name,
            }
        )

    return results


# ── 迁移步骤 ──────────────────────────────────────────────────────────────

async def _step_init_tables() -> None:
    """步骤 1：建表（已存在的表不重建）。"""
    print("📦 步骤 1/3：初始化数据库表...")
    await init_db()
    print("  ✅ 表结构就绪")


async def _step_import_digital_humans() -> tuple[int, int]:
    """步骤 2：将文件系统中的数字人导入 digital_humans 表。

    Returns:
        (imported_count, skipped_count) 导入数和跳过数。
    """
    print("\n👥 步骤 2/3：导入数字人数据...")

    records = _scan_video_data()
    if not records:
        print(f"  ℹ️  {VIDEO_DATA_DIR} 中未找到有效的数字人目录")
        return 0, 0

    active_uuid = _read_active_uuid()
    imported = skipped = 0

    async with AsyncSessionLocal() as session:
        for rec in records:
            # 检查是否已存在（幂等：跳过已有记录）
            existing = await session.scalar(
                select(DigitalHuman).where(DigitalHuman.uuid == rec["uuid"])
            )
            if existing:
                print(f"  ⏭️  跳过「{rec['name']}」({rec['uuid'][:8]}…) — 已存在")
                skipped += 1
                continue

            is_active = rec["uuid"] == active_uuid
            dh = DigitalHuman(
                uuid=rec["uuid"],
                name=rec["name"],
                asset_path=rec["asset_path"],
                is_active=is_active,
                created_at=rec["created_at"],
                updated_at=rec["created_at"],
            )
            session.add(dh)
            status = "✅ 激活" if is_active else "  ✅"
            print(f"  {status} 导入「{rec['name']}」({rec['uuid'][:8]}…)")
            imported += 1

        await session.commit()

    return imported, skipped


async def _step_seed_system_config() -> tuple[int, int]:
    """步骤 3：写入系统配置默认值。

    已存在的键保持原值不变（不覆盖用户已配置的内容）。

    Returns:
        (inserted_count, skipped_count) 新写入数和跳过数。
    """
    print("\n⚙️  步骤 3/3：初始化系统配置...")

    inserted = skipped = 0

    async with AsyncSessionLocal() as session:
        for cfg in _DEFAULT_CONFIGS:
            existing = await session.scalar(
                select(SystemConfig).where(SystemConfig.key == cfg["key"])
            )
            if existing:
                print(f"  ⏭️  跳过 {cfg['key']} — 已存在，保留原值")
                skipped += 1
                continue

            session.add(
                SystemConfig(
                    key=cfg["key"],
                    value=cfg["value"],
                    is_sensitive=cfg["is_sensitive"],
                    description=cfg["description"],
                )
            )
            value_display = "***" if cfg["is_sensitive"] else (cfg["value"] or "<空，请在管理面板填写>")
            print(f"  ✅ 写入 {cfg['key']} = {value_display}")
            inserted += 1

        await session.commit()

    return inserted, skipped


async def _print_summary(
    dh_imported: int,
    dh_skipped: int,
    cfg_inserted: int,
    cfg_skipped: int,
) -> None:
    """打印迁移完成摘要和后续操作提示。"""
    print("\n" + "─" * 50)
    print("🎉 迁移完成！")
    print(f"   数字人：导入 {dh_imported} 条，跳过 {dh_skipped} 条")
    print(f"   系统配置：新增 {cfg_inserted} 条，跳过 {cfg_skipped} 条")

    # 提示用户补充敏感配置
    sensitive_empty = [
        c["key"] for c in _DEFAULT_CONFIGS
        if c["is_sensitive"] and not c["value"]
    ]
    if sensitive_empty:
        print("\n⚠️  以下敏感配置项为空，请在管理面板中填写：")
        for key in sensitive_empty:
            desc = next(c["description"] for c in _DEFAULT_CONFIGS if c["key"] == key)
            print(f"   • {key}  — {desc}")
        print("   或通过环境变量设置（如 export LLM_API_KEY=sk-xxx）后重新运行迁移")

    print("─" * 50)


# ── 主入口 ────────────────────────────────────────────────────────────────

async def run_migration() -> None:
    """执行完整迁移流程。"""
    print("=" * 50)
    print("🚀 数字人后台管理系统 — 数据迁移")
    print(f"   数据源：{VIDEO_DATA_DIR}")
    print(f"   数据库：{_PROJECT_ROOT / 'admin.db'}")
    print("=" * 50 + "\n")

    await _step_init_tables()
    dh_imported, dh_skipped = await _step_import_digital_humans()
    cfg_inserted, cfg_skipped = await _step_seed_system_config()
    await _print_summary(dh_imported, dh_skipped, cfg_inserted, cfg_skipped)


if __name__ == "__main__":
    asyncio.run(run_migration())
