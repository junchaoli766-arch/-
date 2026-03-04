import os.path
import json
import shutil
import gradio as gr
import subprocess
import time
import uuid
from datetime import datetime
from typing import Optional
from data_preparation_mini import data_preparation_mini
from data_preparation_web import data_preparation_web


# 自定义 CSS 样式
css = """
#video-output video {
    max-width: 300px;
    max-height: 300px;
    display: block;
    margin: 0 auto;
}
"""

ACTIVE_DH_FILE = "video_data/active_dh.txt"
VIDEO_DATA_DIR = "video_data"

_ASR_MODEL_DIRS = {
    "zipformer-bilingual": "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20",
    "sensevoice": "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
    "paraformer-trilingual": "sherpa-onnx-paraformer-trilingual-zh-cantonese-en",
}

_TTS_MODEL_DIRS = {
    "sherpa-onnx-vits-zh-ll": "sherpa-onnx-vits-zh-ll",
    "vits-zh-hf-theresa": "vits-zh-hf-theresa",
    "vits-melo-tts-zh_en": "vits-melo-tts-zh_en",
}

video_dir_path = ""


# ──────────────────────────── 数字人持久化管理 ────────────────────────────

def _get_active_uuid() -> Optional[str]:
    """读取当前激活的数字人 UUID。"""
    if os.path.exists(ACTIVE_DH_FILE):
        with open(ACTIVE_DH_FILE, "r") as f:
            saved = f.read().strip()
        if saved:
            return saved
    return None


def _set_active_uuid(dh_uuid: str) -> None:
    """持久化激活的数字人 UUID。"""
    os.makedirs(VIDEO_DATA_DIR, exist_ok=True)
    with open(ACTIVE_DH_FILE, "w") as f:
        f.write(dh_uuid)


def _init_active_dh() -> None:
    """启动时从持久化文件恢复激活的数字人路径。"""
    global video_dir_path
    dh_uuid = _get_active_uuid()
    if dh_uuid:
        dh_path = os.path.join(VIDEO_DATA_DIR, dh_uuid)
        if os.path.exists(dh_path):
            video_dir_path = dh_path


_init_active_dh()


def _save_metadata(dh_path: str, name: str, dh_uuid: str) -> None:
    """保存数字人元数据到 metadata.json。"""
    metadata = {
        "name": name,
        "uuid": dh_uuid,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(os.path.join(dh_path, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)


def list_digital_humans() -> list:
    """返回所有已完整创建的数字人元数据列表（按创建时间倒序）。

    只列出同时具备 metadata.json 和 assets 目录的条目（即完整创建的数字人）。
    """
    if not os.path.exists(VIDEO_DATA_DIR):
        return []
    active_uuid = _get_active_uuid()
    dh_list = []
    for item in os.listdir(VIDEO_DATA_DIR):
        item_path = os.path.join(VIDEO_DATA_DIR, item)
        metadata_path = os.path.join(item_path, "metadata.json")
        assets_path = os.path.join(item_path, "assets")
        if (
            os.path.isdir(item_path)
            and os.path.exists(metadata_path)
            and os.path.exists(assets_path)
        ):
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                metadata["is_active"] = metadata.get("uuid") == active_uuid
                dh_list.append(metadata)
            except Exception:
                pass
    dh_list.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return dh_list


def get_dh_choices() -> list:
    """返回供 Dropdown 使用的 (显示标签, uuid) 元组列表。"""
    choices = []
    for dh in list_digital_humans():
        active_mark = "  ✅ 已激活" if dh["is_active"] else ""
        label = f"{dh['name']}  |  {dh['created_at']}{active_mark}"
        choices.append((label, dh["uuid"]))
    return choices


# ──────────────────────────── 可用模型检测 ────────────────────────────

def _get_available_asr_models() -> list:
    """返回 models/ 目录下实际存在的 ASR 模型名称列表。"""
    return [name for name, d in _ASR_MODEL_DIRS.items() if os.path.isdir(os.path.join("models", d))]


def _get_available_tts_models() -> list:
    """返回 models/ 目录下实际存在的 TTS 模型名称列表。"""
    return [name for name, d in _TTS_MODEL_DIRS.items() if os.path.isdir(os.path.join("models", d))]


# ──────────────────────────── 核心业务函数 ────────────────────────────

def data_preparation(video1, dh_name: str, resize_option: bool):
    """处理视频，提取数字人特征，保存元数据并自动激活。

    Args:
        video1: 上传的视频文件路径
        dh_name: 数字人名称
        resize_option: 是否转为720P

    Yields:
        (状态消息, Dropdown 更新对象)
    """
    global video_dir_path
    try:
        if video1 is None:
            yield "❌ 错误：请先上传视频文件", gr.update()
            return

        if not os.path.exists(video1):
            yield f"❌ 错误：视频文件不存在：{video1}", gr.update()
            return

        dh_uuid = str(uuid.uuid4())
        dh_path = os.path.join(VIDEO_DATA_DIR, dh_uuid)
        os.makedirs(dh_path, exist_ok=True)

        name = dh_name.strip() if dh_name and dh_name.strip() else f"数字人_{dh_uuid[:8]}"
        _save_metadata(dh_path, name, dh_uuid)

        yield f"⏳ 正在进行人脸检测和特征提取，请耐心等待（约30秒）...", gr.update()

        data_preparation_mini(video1, dh_path, resize_option)

        yield "⏳ 正在生成 Web 资源...", gr.update()

        data_preparation_web(dh_path)

        # 自动激活新创建的数字人
        _set_active_uuid(dh_uuid)
        video_dir_path = dh_path

        choices = get_dh_choices()
        yield (
            f"✅ 数字人「{name}」创建完成，已自动激活！可直接前往第三步启动网页服务。",
            gr.update(choices=choices, value=dh_uuid),
        )

    except ImportError as e:
        yield f"❌ 导入错误：{str(e)}\n请确保所有依赖已正确安装", gr.update()
    except Exception as e:
        import traceback
        traceback.print_exc()
        yield f"❌ 处理视频时发生错误：{str(e)}\n请检查视频格式和文件完整性", gr.update()


def refresh_dh_list():
    """刷新数字人列表，返回更新后的 Dropdown。"""
    choices = get_dh_choices()
    active_uuid = _get_active_uuid()
    return gr.update(choices=choices, value=active_uuid if active_uuid else None)


def activate_digital_human(selected_uuid: Optional[str]):
    """激活选中的数字人。

    Args:
        selected_uuid: 选中的数字人 UUID

    Returns:
        (操作结果消息, 更新后的 Dropdown)
    """
    global video_dir_path
    if not selected_uuid:
        return "❌ 请先选择一个数字人", gr.update()

    dh_path = os.path.join(VIDEO_DATA_DIR, selected_uuid)
    if not os.path.exists(dh_path):
        return "❌ 数字人目录不存在，请点击「刷新」后重试", gr.update(choices=get_dh_choices())

    with open(os.path.join(dh_path, "metadata.json"), "r", encoding="utf-8") as f:
        metadata = json.load(f)

    _set_active_uuid(selected_uuid)
    video_dir_path = dh_path

    choices = get_dh_choices()
    return (
        f"✅ 已激活数字人「{metadata['name']}」，现在可以点击「启动网页」",
        gr.update(choices=choices, value=selected_uuid),
    )


def delete_digital_human(selected_uuid: Optional[str]):
    """删除选中的数字人（不可恢复）。

    Args:
        selected_uuid: 选中的数字人 UUID

    Returns:
        (操作结果消息, 更新后的 Dropdown)
    """
    global video_dir_path
    if not selected_uuid:
        return "❌ 请先选择一个数字人", gr.update()

    dh_path = os.path.join(VIDEO_DATA_DIR, selected_uuid)
    if not os.path.exists(dh_path):
        return "❌ 数字人目录不存在，请点击「刷新」后重试", gr.update(choices=get_dh_choices())

    name = selected_uuid
    metadata_path = os.path.join(dh_path, "metadata.json")
    if os.path.exists(metadata_path):
        with open(metadata_path, "r", encoding="utf-8") as f:
            name = json.load(f).get("name", selected_uuid)

    # 若删除的是当前激活项，清除激活状态
    if selected_uuid == _get_active_uuid():
        if os.path.exists(ACTIVE_DH_FILE):
            os.remove(ACTIVE_DH_FILE)
        video_dir_path = ""

    shutil.rmtree(dh_path)

    choices = get_dh_choices()
    return f"🗑️ 已删除数字人「{name}」", gr.update(choices=choices, value=None)


def demo_mini(audio):
    """使用当前激活的数字人 + 上传音频生成测试视频。"""
    global video_dir_path
    audio_path = audio
    wav_path = "video_data/tmp.wav"
    ffmpeg_cmd = "ffmpeg -i {} -ac 1 -ar 16000 -y {}".format(audio_path, wav_path)
    print(ffmpeg_cmd)
    os.system(ffmpeg_cmd)
    output_video_name = "video_data/tmp.mp4"
    asset_path = os.path.join(video_dir_path, "assets")
    from demo_mini import interface_mini
    interface_mini(asset_path, wav_path, output_video_name)
    return output_video_name


def launch_server(asr_model: str, tts_model: str):
    """启动真实大模型对话网页服务。

    Args:
        asr_model: ASR 模型名称
        tts_model: TTS 模型名称

    Yields:
        启动过程各阶段状态提示
    """
    global video_dir_path

    # 若运行时 video_dir_path 为空，尝试从持久化文件恢复
    if not video_dir_path:
        active_uuid = _get_active_uuid()
        if active_uuid:
            dh_path = os.path.join(VIDEO_DATA_DIR, active_uuid)
            if os.path.exists(dh_path):
                video_dir_path = dh_path

    if not video_dir_path:
        yield "❌ 错误：请先在「数字人管理」面板中激活一个数字人"
        return

    asset_path = os.path.join(video_dir_path, "assets")
    target_path = os.path.join("web_demo", "static", "assets")

    yield "⏳ 正在拷贝视频资源..."

    if os.path.exists(target_path):
        shutil.rmtree(target_path)
    shutil.copytree(asset_path, target_path)

    # 把数字人名称写入 dh_config.json，供网页前端同步显示
    dh_name = "数字人"
    metadata_path = os.path.join(video_dir_path, "metadata.json")
    if os.path.exists(metadata_path):
        with open(metadata_path, "r", encoding="utf-8") as f:
            dh_name = json.load(f).get("name", dh_name)
    config_path = os.path.join("web_demo", "static", "dh_config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump({"name": dh_name}, f, ensure_ascii=False)

    yield "⏳ 正在终止旧进程，等待端口释放..."

    os.system("lsof -ti:8888 | xargs kill -9 2>/dev/null || true")
    time.sleep(1.5)

    yield f"⏳ 正在启动对话服务（ASR: {asr_model} / TTS: {tts_model}）..."

    cmd = [
        "python", "web_demo/server_realtime.py",
        "--models-root", "./models",
        "--asr-model", asr_model,
        "--tts-model", tts_model,
    ]
    subprocess.Popen(cmd)

    yield "✅ 服务启动中，模型加载约需 10 秒。\n访问 http://localhost:8888/static/MiniLive_RealTime.html"


# ──────────────────────────── Gradio UI ────────────────────────────

def create_interface():
    with gr.Blocks(css=css) as demo:
        gr.Markdown("""
        # 🎭 在线生成多风格数字人--生成你想要的数字人

        **欢迎使用数字人生成工具！** 通过上传静默视频和音频，快速创建属于您的专属数字人形象。
        """)

        with gr.Accordion("📖 使用指南（点击展开）", open=False):
            gr.Markdown("""
            ### 🚀 快速开始（三步完成）

            1. **第一步：上传静默视频**
               - 填写数字人名称（方便后续管理，留空自动命名）
               - 上传一个 5-30 秒的静默视频（人物保持闭嘴或微张状态）
               - 点击"处理视频"，完成后自动激活该数字人

            2. **数字人管理**
               - 查看所有已创建的数字人，支持一键切换激活、删除

            3. **第二步：测试生成（可选）**
               - 上传音频文件，测试数字人说话效果
               - 注意：此功能在 Linux 和 MacOS 上可能不支持，可跳过

            4. **第三步：启动网页服务**
               - 点击"启动网页"按钮，启动完整的数字人对话服务
               - 访问生成的网页地址，体验实时对话功能

            ### 💡 功能特点
            - ✅ 支持多个数字人形象管理，随时切换
            - ✅ 支持实时语音对话
            - ✅ 支持文字和语音输入
            - ✅ 支持多种音色和语速调节

            ### ⚠️ 注意事项
            - 静默视频质量直接影响最终效果，请确保视频清晰
            - 建议使用 720P 分辨率以获得最佳兼容性
            - 网页服务需要在 localhost 或 HTTPS 环境下运行
            """)

        # ── 第一步：视频处理 ──────────────────────────────────────────
        gr.Markdown("## 📹 第一步：视频处理")
        gr.Markdown("""
        - **静默视频**：时长建议在 5-30 秒之间，嘴巴不要动（保持闭嘴或微张）。嘴巴如果有动作会影响效果，请认真对待。
        """)

        dh_name_input = gr.Textbox(
            label="数字人名称",
            placeholder="给这个数字人起个名字，方便后续管理（留空则自动命名）",
            max_lines=1,
        )
        with gr.Row():
            with gr.Column():
                video1 = gr.Video(label="上传静默视频", elem_id="video-output")
        resize_option = gr.Checkbox(label="是否转为最高720P（适配手机）", value=True)
        process_button = gr.Button("处理视频", variant="primary")
        process_output = gr.Textbox(label="处理结果")

        gr.Markdown("---")

        # ── 数字人管理面板 ────────────────────────────────────────────
        gr.Markdown("## 👥 数字人管理")
        gr.Markdown("查看所有已创建的数字人，选择后点击「激活」可切换当前使用的形象，点击「删除」可移除不需要的数字人。")

        with gr.Row():
            dh_dropdown = gr.Dropdown(
                label="选择数字人",
                choices=get_dh_choices(),
                value=_get_active_uuid(),
                interactive=True,
                scale=4,
            )
            refresh_btn = gr.Button("🔄 刷新", scale=1, min_width=80)

        with gr.Row():
            activate_btn = gr.Button("✅ 激活选中数字人", variant="primary")
            delete_btn = gr.Button("🗑️ 删除选中数字人", variant="stop")

        mgmt_output = gr.Textbox(label="操作结果")

        gr.Markdown("---")

        # ── 第二步：测试语音生成 ──────────────────────────────────────
        gr.Markdown("## 🎵 第二步：测试语音生成视频（可选）")
        gr.Markdown("""
        > ⚠️ **注意**：此功能在 Linux 和 MacOS 上可能不支持，可以跳过此步骤直接进入第三步。
        """)
        gr.Markdown("""
        - 上传音频文件后，点击"生成视频"按钮，程序会调用 `demo_mini` 函数完成推理并生成视频。
        - 此步骤用于初步验证结果。网页demo请执行第三步。
        """)

        with gr.Row():
            with gr.Column():
                audio = gr.Audio(label="上传音频文件", type="filepath")
                generate_button = gr.Button("生成视频")
            with gr.Column():
                video_output = gr.Video(label="生成的视频", elem_id="video-output")

        gr.Markdown("---")

        # ── 第三步：启动网页 ──────────────────────────────────────────
        gr.Markdown("## 🌐 第三步：启动网页服务")
        gr.Markdown("""
        > **模型说明**：下拉菜单仅列出本地已下载的模型。如需其他模型（sensevoice / paraformer-trilingual / vits-zh-hf-theresa 等），请先按 `web_demo/README.md` 下载后再选择。
        """)
        with gr.Row():
            asr_model_dropdown = gr.Dropdown(
                label="ASR 语音识别模型",
                choices=_get_available_asr_models(),
                value="zipformer-bilingual",
                info="zipformer-bilingual：流式识别（边说边出字）；sensevoice/paraformer：整句识别（准确率更高）",
            )
            tts_model_dropdown = gr.Dropdown(
                label="TTS 语音合成模型",
                choices=_get_available_tts_models(),
                value="sherpa-onnx-vits-zh-ll",
                info="vits-zh-ll：轻量16kHz；vits-theresa：女声22kHz；vits-melo：中英混读44kHz",
            )
        launch_button = gr.Button("启动网页")
        gr.Markdown("""
        - **注意**：本项目使用了 WebCodecs API，该 API 仅在安全上下文（HTTPS 或 localhost）中可用。因此，在部署或测试时，请确保您的网页在 HTTPS 环境下运行，或者使用 localhost 进行本地测试。
        """)
        launch_output = gr.Textbox(label="启动结果")

        gr.Markdown("""
            **🔔 扩展功能提示：**
            > 更多高级功能（实时大模型对话、动态更换任务、音色切换等）请前往
            > `web_demo` 目录按照说明配置后，启动
            > `web_demo/server_realtime.py` 体验完整功能
            """)
        gr.Markdown("""
        - 点击"启动网页"按钮后，会启动 `server.py`，提供一个模拟对话服务。
        - 在 `static/js/dialog.js` 文件中，找到第 1 行，将 server_url=`http://localhost:8888/eb_stream` 替换为您自己的对话服务网址。例如：
          ```bash
          https://your-dialogue-service.com/eb_stream
          ```
        - `server.py` 提供了一个模拟对话服务的示例。它接收 JSON 格式的输入，并流式返回 JSON 格式的响应。
        # API 接口说明
        """)

        # ── 第四部分：高级功能说明 ────────────────────────────────────
        gr.Markdown("## 🔧 高级功能说明")
        gr.Markdown("""
        ### 🎯 完整功能体验

        如果您想体验更多高级功能（如实时大模型对话、动态更换任务、音色切换等），请：

        1. 前往 `web_demo` 目录
        2. 按照 `README.md` 中的说明配置 ASR/TTS/LLM 模型
        3. 启动 `web_demo/server_realtime.py` 体验完整功能

        ### 📚 API 接口说明

        启动网页服务后，您可以通过 API 接口与数字人进行交互：

        **输入格式：**
        - `input_mode`: "text" 或 "audio"（文字或语音输入）
        - `prompt`: 文字内容（当 input_mode 为 "text" 时必填）
        - `audio`: Base64 编码的音频（当 input_mode 为 "audio" 时必填）
        - `voice_speed`: TTS 语速（可选）
        - `voice_id`: TTS 音色（可选）

        **输出格式（流式返回）：**
        - `text`: 对话文本
        - `audio`: Base64 编码的音频数据
        - `endpoint`: 是否为最后一个片段
        """)

        # ── 事件绑定 ──────────────────────────────────────────────────
        process_button.click(
            data_preparation,
            inputs=[video1, dh_name_input, resize_option],
            outputs=[process_output, dh_dropdown],
        )
        generate_button.click(demo_mini, inputs=audio, outputs=video_output)
        launch_button.click(
            launch_server,
            inputs=[asr_model_dropdown, tts_model_dropdown],
            outputs=launch_output,
        )

        refresh_btn.click(refresh_dh_list, outputs=dh_dropdown)
        activate_btn.click(
            activate_digital_human,
            inputs=dh_dropdown,
            outputs=[mgmt_output, dh_dropdown],
        )
        delete_btn.click(
            delete_digital_human,
            inputs=dh_dropdown,
            outputs=[mgmt_output, dh_dropdown],
        )

    return demo


# 创建 Gradio 界面并启动
if __name__ == "__main__":
    demo = create_interface()
    demo.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
        show_api=False,
    )
