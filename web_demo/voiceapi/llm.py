import os
import sqlite3
from pathlib import Path
from typing import Optional

from openai import OpenAI

LLM_KEYS = (
    "llm_api_key",
    "llm_base_url",
    "llm_model_name",
    "llm_enable_search",
)

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL_NAME = "deepseek-chat"
DEFAULT_ENABLE_SEARCH = True
DEFAULT_SYSTEM_PROMPT = "你是人工智能助手"


class MockStream:
    def __init__(self, text):
        self.text = text
        self.index = 0
        self.chunk_size = 5

    def __iter__(self):
        return self

    def __next__(self):
        if self.index >= len(self.text):
            raise StopIteration

        chunk_text = self.text[self.index:self.index + self.chunk_size]
        self.index += self.chunk_size

        class MockChunk:
            def __init__(self, content):
                class MockChoice:
                    def __init__(self, content):
                        class MockDelta:
                            def __init__(self, content):
                                self.content = content

                        self.delta = MockDelta(content)

                self.choices = [MockChoice(content)]

        return MockChunk(chunk_text)


def _to_bool(raw, default=False):
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_db_path() -> str:
    env_path = os.environ.get("ADMIN_DB_PATH")
    if env_path:
        return env_path
    project_root = Path(__file__).resolve().parents[2]
    return str(project_root / "admin.db")


def _load_llm_config():
    cfg = {
        "llm_api_key": os.environ.get("LLM_API_KEY", ""),
        "llm_base_url": os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL),
        "llm_model_name": os.environ.get("LLM_MODEL_NAME", DEFAULT_MODEL_NAME),
        "llm_enable_search": _to_bool(
            os.environ.get("LLM_ENABLE_SEARCH"),
            DEFAULT_ENABLE_SEARCH,
        ),
    }

    db_path = _get_db_path()
    if not os.path.exists(db_path):
        return cfg

    placeholders = ",".join("?" for _ in LLM_KEYS)
    sql = f"SELECT key, value FROM system_config WHERE key IN ({placeholders})"

    try:
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(sql, LLM_KEYS).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        print(f"读取数据库配置失败，使用环境变量/默认值: {exc}")
        return cfg

    for key, value in rows:
        if key == "llm_enable_search":
            cfg[key] = _to_bool(value, DEFAULT_ENABLE_SEARCH)
            continue

        text_value = "" if value is None else str(value).strip()
        # 空值不覆盖环境变量/默认值，避免因数据库占位空串触发降级
        if not text_value:
            continue
        cfg[key] = text_value

    return cfg


def _mock_stream_for_error(prompt, err_msg):
    mock_answer = (
        f"抱歉，LLM API 调用失败（{err_msg}）。"
        f"您的问题是：{prompt}。这是一个模拟回答，请检查后台配置后重试。"
    )
    return MockStream(mock_answer)


def llm_stream(prompt, use_search=None, system_prompt: Optional[str] = None):
    """
    调用大模型生成流式响应。

    Args:
        prompt: 用户输入的提示词。
        use_search: 是否使用联网搜索，None 时读取配置。
        system_prompt: 角色系统提示词，传入后覆盖默认提示。
    """
    cfg = _load_llm_config()
    if use_search is None:
        use_search = cfg["llm_enable_search"]

    api_key = cfg["llm_api_key"]
    base_url = cfg["llm_base_url"] or DEFAULT_BASE_URL
    model_name = cfg["llm_model_name"] or DEFAULT_MODEL_NAME

    if not api_key:
        print("llm_api_key 为空，降级使用模拟回答")
        return _mock_stream_for_error(prompt, "llm_api_key 未配置")

    try:
        llm_client = OpenAI(
            base_url=base_url,
            api_key=api_key,
        )

        prompt_text = (system_prompt or "").strip() or DEFAULT_SYSTEM_PROMPT
        if use_search:
            prompt_text += (
                "。你可以使用联网搜索功能来获取最新的实时信息，"
                "包括新闻、天气、股票、技术文档等。"
                "当用户询问需要最新信息的问题时，请使用联网搜索功能。"
            )

        api_params = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": prompt_text},
                {"role": "user", "content": prompt},
            ],
            "stream": True,
        }
        return llm_client.chat.completions.create(**api_params)
    except Exception as e:
        print(f"LLM API 调用失败: {e}")
        print("降级使用模拟回答")
        return _mock_stream_for_error(prompt, str(e))
