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


方式 3：Gradio 图形界面（功能最全）
# 进入项目目录
cd /Users/xiniuyiliao/Desktop/在线多风格数字人/DH_live-main

# 激活虚拟环境
source venv/bin/activate

# 启动 Gradio 界面
python app.py
访问：会自动打开浏览器（或访问终端显示的地址，通常是 http://127.0.0.1:7860）