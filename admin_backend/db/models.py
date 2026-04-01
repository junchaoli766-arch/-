"""ORM 数据模型定义。

共 5 张表，职责清晰：
  - DigitalHuman   : 数字人元数据注册表（指向文件系统资产目录）
  - Conversation   : 每次对话会话的聚合信息
  - Message        : 会话内的逐条消息记录
  - SystemConfig   : 系统配置键值对（API Key 等敏感信息加密存储）
  - ApiCallLog     : LLM/ASR/TTS API 调用日志，用于用量统计与计费

设计原则
--------
- 大文件（视频、模型）永远存文件系统，数据库只存元数据和路径。
- UUID 作为业务主键，与现有 video_data/<uuid>/ 目录一一对应。
- 时间字段统一使用 UTC，由数据库层自动填充。
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


# ---------------------------------------------------------------------------
# 枚举类型
# ---------------------------------------------------------------------------

class InputMode(str, enum.Enum):
    """对话输入模式。"""

    TEXT = "text"
    AUDIO = "audio"


class MessageRole(str, enum.Enum):
    """消息角色。"""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ApiProvider(str, enum.Enum):
    """外部 API 服务提供商。"""

    LLM = "llm"
    ASR = "asr"
    TTS = "tts"


# ---------------------------------------------------------------------------
# 数字人（DigitalHuman）
# ---------------------------------------------------------------------------

class DigitalHuman(Base):
    """数字人元数据注册表。

    每条记录对应 video_data/<uuid>/ 目录下的一个数字人形象。
    资产文件（视频、OpenGL 资源）保留在文件系统，数据库只存路径和元信息。

    Attributes:
        id: 自增主键（内部用）。
        uuid: 业务主键，与文件系统目录名保持一致。
        name: 用户设定的显示名称。
        asset_path: 资产目录绝对路径，例如 /…/video_data/<uuid>/assets。
        thumbnail_path: 封面图路径（可选，用于管理面板展示）。
        system_prompt: 该数字人的对话系统提示词（人设）。
        default_voice_id: 默认音色 ID（前端未传时作为兜底）。
        is_active: 当前是否为激活状态（全局只有 1 个为 True）。
        created_at: 创建时间（UTC）。
        updated_at: 最后更新时间（UTC）。
    """

    __tablename__ = "digital_humans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    asset_path: Mapped[str] = mapped_column(String(512), nullable=False)
    thumbnail_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    default_voice_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # 关联：一个数字人拥有多条对话
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation", back_populates="digital_human", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<DigitalHuman uuid={self.uuid} name={self.name} active={self.is_active}>"


# ---------------------------------------------------------------------------
# 对话会话（Conversation）
# ---------------------------------------------------------------------------

class Conversation(Base):
    """对话会话聚合记录。

    一次完整的用户与数字人交互过程。会话结束后更新 ended_at 和统计字段。

    Attributes:
        id: 自增主键。
        session_id: 前端生成的会话 ID（UUID）。
        dh_uuid: 关联的数字人 UUID（外键）。
        input_mode: 本次会话的主要输入模式（文字 / 语音）。
        total_messages: 消息总条数（冗余字段，方便快速统计）。
        started_at: 会话开始时间（UTC）。
        ended_at: 会话结束时间（UTC），进行中为 None。
    """

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    dh_uuid: Mapped[str] = mapped_column(
        String(36), ForeignKey("digital_humans.uuid", ondelete="CASCADE"), nullable=False, index=True
    )
    input_mode: Mapped[InputMode] = mapped_column(
        Enum(InputMode), default=InputMode.TEXT, nullable=False
    )
    total_messages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # 关联
    digital_human: Mapped["DigitalHuman"] = relationship(
        "DigitalHuman", back_populates="conversations"
    )
    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Conversation session={self.session_id} dh={self.dh_uuid}>"


# ---------------------------------------------------------------------------
# 消息（Message）
# ---------------------------------------------------------------------------

class Message(Base):
    """会话内的单条消息记录。

    存储用户输入和 AI 回复，不存储音频原始数据（仅存文本内容），
    以控制数据库体积。

    Attributes:
        id: 自增主键。
        conversation_id: 所属会话 ID（外键）。
        role: 消息角色（user / assistant / system）。
        content: 消息文本内容。
        latency_ms: 从收到请求到首 token 的延迟（毫秒），AI 消息专用。
        created_at: 消息创建时间（UTC）。
    """

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # 关联
    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="messages"
    )

    def __repr__(self) -> str:
        return f"<Message role={self.role} conv={self.conversation_id}>"


# ---------------------------------------------------------------------------
# 系统配置（SystemConfig）
# ---------------------------------------------------------------------------

class SystemConfig(Base):
    """系统配置键值对存储。

    替代代码中硬编码的 API Key 和模型参数。敏感字段（api_key 等）
    由应用层在写入前加密，读取后解密（使用 ADMIN_SECRET_KEY 环境变量）。

    常用 key 示例
    -------------
    - llm_api_key      : LLM 服务 API Key（加密存储）
    - llm_base_url     : LLM API 地址
    - llm_model_name   : 模型名称
    - asr_model        : ASR 模型名称
    - tts_model        : TTS 模型名称
    - admin_token      : 管理后台访问令牌（加密存储）

    Attributes:
        key: 配置项名称（主键）。
        value: 配置值，敏感项由应用层加密后写入。
        is_sensitive: 标记该值是否为敏感信息（影响日志脱敏）。
        description: 配置项说明，显示在管理面板。
        updated_at: 最后更新时间（UTC）。
    """

    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        display = "***" if self.is_sensitive else self.value[:20]
        return f"<SystemConfig key={self.key} value={display}>"


# ---------------------------------------------------------------------------
# API 调用日志（ApiCallLog）
# ---------------------------------------------------------------------------

class ApiCallLog(Base):
    """外部 API 调用日志。

    记录每次 LLM / ASR / TTS 调用的用量与耗时，用于用量统计和费用估算。
    不存储完整的请求/响应内容，只存统计字段。

    Attributes:
        id: 自增主键。
        provider: 服务提供商类型（llm / asr / tts）。
        model_name: 具体模型名称。
        session_id: 关联的对话会话 ID（可选，部分调用无会话上下文）。
        prompt_tokens: LLM 输入 token 数（LLM 调用专用）。
        completion_tokens: LLM 输出 token 数（LLM 调用专用）。
        latency_ms: 调用耗时（毫秒）。
        success: 调用是否成功。
        error_msg: 失败时的错误摘要（不超过 500 字符）。
        created_at: 调用时间（UTC）。
    """

    __tablename__ = "api_call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[ApiProvider] = mapped_column(Enum(ApiProvider), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    session_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error_msg: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    def __repr__(self) -> str:
        return (
            f"<ApiCallLog provider={self.provider} model={self.model_name} "
            f"success={self.success} latency={self.latency_ms}ms>"
        )
