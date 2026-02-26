#!/bin/bash

# 复制已下载的模型文件到项目目录
# 使用方法: bash copy_models.sh

set -e

# 项目根目录
PROJECT_DIR="/Users/xiniuyiliao/Desktop/在线多风格数字人/DH_live-main"
MODELS_DIR="$PROJECT_DIR/models"

# 源目录（根据实际路径调整）
SOURCE_DIR="/Users/xiniuyiliao/Desktop/在线多风格数字人/ ASR（语音识别）和 TTS（语音合成）模型文件"

cd "$PROJECT_DIR"

# 创建 models 目录
mkdir -p "$MODELS_DIR"

echo "正在查找模型文件..."

# 查找 ASR 模型
ASR_SOURCE=$(find "/Users/xiniuyiliao/Desktop/在线多风格数字人" -type d -name "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20" 2>/dev/null | grep -v "DH_live-main" | head -1)
TTS_SOURCE=$(find "/Users/xiniuyiliao/Desktop/在线多风格数字人" -type d -name "sherpa-onnx-vits-zh-ll" 2>/dev/null | grep -v "DH_live-main" | head -1)

if [ -z "$ASR_SOURCE" ]; then
    echo "错误: 未找到 ASR 模型文件夹"
    echo "请确保模型已解压到: $SOURCE_DIR"
    exit 1
fi

if [ -z "$TTS_SOURCE" ]; then
    echo "错误: 未找到 TTS 模型文件夹"
    echo "请确保模型已解压到: $SOURCE_DIR"
    exit 1
fi

echo "找到 ASR 模型: $ASR_SOURCE"
echo "找到 TTS 模型: $TTS_SOURCE"

# 复制 ASR 模型
echo ""
echo "正在复制 ASR 模型..."
if [ -d "$MODELS_DIR/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20" ]; then
    echo "ASR 模型已存在，跳过复制"
else
    cp -R "$ASR_SOURCE" "$MODELS_DIR/"
    echo "ASR 模型复制完成！"
fi

# 复制 TTS 模型
echo ""
echo "正在复制 TTS 模型..."
if [ -d "$MODELS_DIR/sherpa-onnx-vits-zh-ll" ]; then
    echo "TTS 模型已存在，跳过复制"
else
    cp -R "$TTS_SOURCE" "$MODELS_DIR/"
    echo "TTS 模型复制完成！"
fi

echo ""
echo "所有模型复制完成！"
echo "模型目录结构："
ls -la "$MODELS_DIR"

# 验证模型文件
echo ""
echo "验证 ASR 模型文件..."
ASR_DIR="$MODELS_DIR/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20"
if [ -f "$ASR_DIR/encoder-epoch-99-avg-1.onnx" ] && \
   [ -f "$ASR_DIR/decoder-epoch-99-avg-1.onnx" ] && \
   [ -f "$ASR_DIR/joiner-epoch-99-avg-1.onnx" ] && \
   [ -f "$ASR_DIR/tokens.txt" ]; then
    echo "✓ ASR 模型文件完整"
else
    echo "✗ ASR 模型文件不完整，请检查"
fi

echo ""
echo "验证 TTS 模型文件..."
TTS_DIR="$MODELS_DIR/sherpa-onnx-vits-zh-ll"
if [ -d "$TTS_DIR" ]; then
    echo "✓ TTS 模型目录存在"
    ls "$TTS_DIR" | head -5
else
    echo "✗ TTS 模型目录不存在"
fi
