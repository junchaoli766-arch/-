作者：xiaoer.ljc    目前处于   数字人在线应用系统2.0---（有待升级，后续可以引入插件模式。比如直接用ifarme可以嵌入此页面工程）

具体的启动命令：
方式 1：基础网页演示（推荐，最简单）
# 进入项目目录
cd /Users/xiniuyiliao/Desktop/在线多风格数字人/DH_live-main
# 激活虚拟环境
source venv/bin/activate
# 启动基础演示服务器
python web_demo/server.py
访问：http://localhost:8888/static/MiniLive.html

🎙️ 方式 2：实时语音对话（需要配置 ASR/TTS/LLM）
# 进入项目目录
cd /Users/xiniuyiliao/Desktop/在线多风格数字人/DH_live-main
# 激活虚拟环境
source venv/bin/activate
# 启动实时对话服务器
python web_demo/server_realtime.py
访问：http://localhost:8888/static/MiniLive_RealTime.html

方式 3：Gradio 图形界面（功能最全）--目前已经集成数字人生成名称选择以及相应的管理面板，可以实时启动大模型对话服务器
# 进入项目目录
cd /Users/xiniuyiliao/Desktop/在线多风格数字人/DH_live-main
# 激活虚拟环境
source venv/bin/activate
# 启动 Gradio 界面
python app.py
访问：会自动打开浏览器（或访问终端显示的地址，通常是 http://127.0.0.1:7860）


2026.3.4
数字人更新3.0
 1. 只变了一部分存储
  - 大文件资产仍在 video_data/（没变）
  - 配置和数字人元数据现在可落 admin.db（新增）
  2. 数据库初始化/数据来源
  - server_realtime.py 启动时会自动 create_all 建表
  - 但如果你要把历史 video_data 导入数据库，需要跑一次：
      - python -m admin_backend.db.migrate
  所以更准确地说：
  启动方式基本不变，数据存储从“纯文件”变成了“文件 + SQLite 并存”


数字人应用系统3.28
  1.接入大模型deepweek的api
  2.测试问答模式
  目前的所实现“数字人生成 + 数字人管理 + 实时语音对话”的完整样例系统
  web 实时对话
   FastAPI + WebSocket + 流式返回 组成在线交互服务
   ASR 语音识别
   LLM 流式回复
   TTS 合成音频
  3.优化文件系统和SQLite混合存储
   视频、模型、渲染资产不进数据库，只存文件
   实时服务和后台 API 以数据库为准。
  4.论文初稿近一步完善
