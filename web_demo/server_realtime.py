import json
import os
import sys
from contextlib import asynccontextmanager
import re
import asyncio
import base64
from pathlib import Path
from typing import Optional
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, Request, UploadFile, File,HTTPException,WebSocketDisconnect,WebSocket
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

# 允许导入项目根目录下的 admin_backend 包
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from admin_backend.db.database import AsyncSessionLocal, init_db
from admin_backend.db.models import DigitalHuman
from api.config import router as config_router
from api.dh import router as dh_router
from voiceapi.asr import start_asr_stream, ASRResult,ASREngineManager
import uvicorn
import argparse
from voiceapi.llm import llm_stream
from voiceapi.tts import get_audio,TTSEngineManager

# 2. 生命周期管理
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 确保数据库表结构存在
    await init_db()
    # 服务启动时初始化模型（示例参数）
    print("ASR模型正在初始化，请稍等")
    ASREngineManager.initialize(samplerate=16000, args = args)
    print("TTS模型正在初始化，请稍等")
    TTSEngineManager.initialize(args = args)
    yield
    # 服务关闭时清理资源（OnlineRecognizer 不一定有 cleanup 方法，用 hasattr 保护）
    engine = ASREngineManager.get_engine()
    if engine and hasattr(engine, 'cleanup'):
        engine.cleanup()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config_router)
app.include_router(dh_router)

# 挂载静态文件
app.mount("/static", StaticFiles(directory="web_demo/static"), name="static")


def split_sentence(sentence, min_length=10):
    # 定义包括小括号在内的主要标点符号
    punctuations = r'[。？！；…，、()（）]'
    # 使用正则表达式切分句子，保留标点符号
    parts = re.split(f'({punctuations})', sentence)
    parts = [p for p in parts if p]  # 移除空字符串
    sentences = []
    current = ''
    for part in parts:
        if current:
            # 如果当前片段加上新片段长度超过最小长度，则将当前片段添加到结果中
            if len(current) + len(part) >= min_length:
                sentences.append(current + part)
                current = ''
            else:
                current += part
        else:
            current = part
    # 将剩余的片段添加到结果中
    if len(current) >= 2:
        sentences.append(current)
    return sentences

PUNCTUATION_SET = {
    '，', " ", '。', '！', '？', '；', '：', '、', '（', '）', '【', '】', '“', '”',
    ',', '.', '!', '?', ';', ':', '(', ')', '[', ']', '"', "'"
}

VIDEO_DATA_DIR = PROJECT_ROOT / "video_data"
ACTIVE_DH_FILE = VIDEO_DATA_DIR / "active_dh.txt"


def _read_active_uuid_from_file():
    if not ACTIVE_DH_FILE.exists():
        return None
    content = ACTIVE_DH_FILE.read_text(encoding="utf-8").strip()
    return content or None


def _read_dh_name_from_metadata(dh_uuid: Optional[str]) -> Optional[str]:
    if not dh_uuid:
        return None
    metadata_path = VIDEO_DATA_DIR / dh_uuid / "metadata.json"
    if not metadata_path.exists():
        return None
    try:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    name = str(data.get("name", "")).strip()
    return name or None


def _build_system_prompt(
    dh: Optional[DigitalHuman],
    character_asset: str,
    fallback_name: Optional[str] = None,
) -> Optional[str]:
    if dh and dh.system_prompt and dh.system_prompt.strip():
        return dh.system_prompt.strip()
    if dh:
        return (
            f"你正在扮演数字人「{dh.name}」。"
            "请始终保持该角色口吻，回答自然、简洁、友好。"
        )
    if fallback_name:
        return (
            f"你正在扮演数字人「{fallback_name}」。"
            "请始终保持该角色口吻，回答自然、简洁、友好。"
        )
    if character_asset == "assets2":
        return "你是一位温柔、耐心的女性数字人助手，请使用自然亲和的中文风格对话。"
    return None


def _normalize_voice_id(raw_voice_id):
    if raw_voice_id in ("", None):
        return None
    try:
        return int(raw_voice_id)
    except (TypeError, ValueError):
        return 0


async def _resolve_digital_human(dh_uuid: Optional[str], character_asset: str) -> Optional[DigitalHuman]:
    target_uuid = (dh_uuid or "").strip()
    if not target_uuid and character_asset == "assets":
        target_uuid = _read_active_uuid_from_file() or ""

    async with AsyncSessionLocal() as session:
        if target_uuid:
            row = await session.scalar(
                select(DigitalHuman).where(DigitalHuman.uuid == target_uuid)
            )
            if row:
                return row

        if character_asset == "assets":
            return await session.scalar(
                select(DigitalHuman).where(DigitalHuman.is_active.is_(True))
            )
    return None


async def gen_stream(prompt, asr = False, voice_speed=None, voice_id=None, system_prompt=None):
    print("gen_stream", voice_speed, voice_id)
    if asr:
        chunk = {
            "prompt": prompt
        }
        yield f"{json.dumps(chunk)}\n"  # 使用换行符分隔 JSON 块

    # Streaming:
    print("----- streaming request -----")
    stream = llm_stream(prompt, system_prompt=system_prompt)
    llm_answer_cache = ""
    for chunk in stream:
        if not chunk.choices:
            continue
        llm_answer_cache += chunk.choices[0].delta.content

        # 查找第一个标点符号的位置
        punctuation_pos = -1
        for i, char in enumerate(llm_answer_cache[8:]):
            if char in PUNCTUATION_SET:
                punctuation_pos = i + 8
                break
        # 如果找到标点符号且第一小句字数大于8
        if punctuation_pos != -1:
            # 获取第一小句
            first_sentence = llm_answer_cache[:punctuation_pos + 1]
            # 剩余的文字
            remaining_text = llm_answer_cache[punctuation_pos + 1:]
            print("get_audio: ", first_sentence)
            base64_string = await get_audio(first_sentence, voice_id=voice_id, voice_speed=voice_speed)
            chunk = {
                "text": first_sentence,
                "audio": base64_string,
                "endpoint": False
            }

            # 更新缓存为剩余的文字
            llm_answer_cache = remaining_text
            yield f"{json.dumps(chunk)}\n"  # 使用换行符分隔 JSON 块
            await asyncio.sleep(0.2)  # 模拟异步延迟
    print("get_audio: ", llm_answer_cache)
    if len(llm_answer_cache) >= 2:
        base64_string = await get_audio(llm_answer_cache, voice_id=voice_id, voice_speed=voice_speed)
    else:
        base64_string = ""
    chunk = {
            "text": llm_answer_cache,
            "audio": base64_string,
            "endpoint": True
    }
    yield f"{json.dumps(chunk)}\n"  # 使用换行符分隔 JSON 块

@app.websocket("/asr")
async def websocket_asr(websocket: WebSocket, samplerate: int = 16000):
    await websocket.accept()

    asr_stream = await start_asr_stream(samplerate, args)
    if not asr_stream:
        print("failed to start ASR stream")
        await websocket.close()
        return

    async def task_recv_pcm():
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive(), timeout=1.0)
                # print(f"message: {data}")
            except asyncio.TimeoutError:
                continue  # 没有数据到达，继续循环

            if "text" in data.keys():
                print(f"Received text message: {data}")
                data = data["text"]
                if data.strip() == "vad":
                    print("VAD signal received")
                    await asr_stream.vad_touched()
            elif "bytes" in data.keys():
                pcm_bytes = data["bytes"]
                print("XXXX pcm_bytes", len(pcm_bytes))
                if not pcm_bytes:
                    return
                await asr_stream.write(pcm_bytes)


    async def task_send_result():
        while True:
            result: ASRResult = await asr_stream.read()
            if not result:
                return
            await websocket.send_json(result.to_dict())
    try:
        await asyncio.gather(task_recv_pcm(), task_send_result())
    except WebSocketDisconnect:
        print("asr: disconnected")
    finally:
        await asr_stream.close()

@app.post("/eb_stream")    # 前端调用的path
async def eb_stream(request: Request):
    try:
        body = await request.json()
        input_mode = body.get("input_mode")
        voice_speed = body.get("voice_speed", 1.0)
        voice_id = _normalize_voice_id(body.get("voice_id"))
        dh_uuid = body.get("dh_uuid")
        character_asset = body.get("character_asset", "assets")
        dh = await _resolve_digital_human(dh_uuid, character_asset)
        fallback_uuid = (dh_uuid or "").strip() or _read_active_uuid_from_file()
        fallback_name = _read_dh_name_from_metadata(fallback_uuid)
        system_prompt = _build_system_prompt(dh, character_asset, fallback_name=fallback_name)

        if voice_speed == "":
            voice_speed = 1.0
        if voice_id is None:
            if dh and dh.default_voice_id is not None:
                voice_id = dh.default_voice_id
            else:
                voice_id = 0

        if input_mode == "text":
            prompt = body.get("prompt")
            return StreamingResponse(
                gen_stream(
                    prompt,
                    asr=False,
                    voice_speed=voice_speed,
                    voice_id=voice_id,
                    system_prompt=system_prompt,
                ),
                media_type="application/json",
            )
        else:
            raise HTTPException(status_code=400, detail="Invalid input mode")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 启动Uvicorn服务器
if __name__ == "__main__":
    models_root = './models'

    for d in ['.', '..', 'web_demo']:
        if os.path.isdir(f'{d}/models'):
            models_root = f'{d}/models'
            break

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8888, help="port number")
    parser.add_argument("--addr", type=str,
                        default="0.0.0.0", help="serve address")

    parser.add_argument("--asr-provider", type=str,
                        default="cpu", help="asr provider, cpu or cuda")
    parser.add_argument("--tts-provider", type=str,
                        default="cpu", help="tts provider, cpu or cuda")

    parser.add_argument("--threads", type=int, default=2,
                        help="number of threads")

    parser.add_argument("--models-root", type=str, default=models_root,
                        help="model root directory")

    parser.add_argument("--asr-model", type=str, default='zipformer-bilingual',
                        help="ASR model name: zipformer-bilingual, sensevoice, paraformer-trilingual, paraformer-en, whisper-medium")

    parser.add_argument("--asr-lang", type=str, default='zh',
                        help="ASR language, zh, en, ja, ko, yue")

    parser.add_argument("--tts-model", type=str, default='sherpa-onnx-vits-zh-ll',
                        help="TTS model name: vits-zh-hf-theresa, vits-melo-tts-zh_en")

    args = parser.parse_args()

    if args.tts_model == 'vits-melo-tts-zh_en' and args.tts_provider == 'cuda':
        print(
            "vits-melo-tts-zh_en does not support CUDA fallback to CPU")
        args.tts_provider = 'cpu'

    uvicorn.run(app, host=args.addr, port=args.port)
