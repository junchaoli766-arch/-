#!/bin/bash

# 下载 ASR 和 TTS 模型的脚本
# 使用方法: bash download_models.sh

set -e

MODELS_DIR="./models"
cd "$(dirname "$0")"

# 创建 models 目录
mkdir -p "$MODELS_DIR"
cd "$MODELS_DIR"

echo "开始下载 ASR 模型..."
# 下载 ASR 模型
ASR_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2"
ASR_FILE="sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2"

if [ ! -d "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20" ]; then
    echo "正在下载 ASR 模型..."
    curl -L -o "$ASR_FILE" "$ASR_URL"
    echo "正在解压 ASR 模型..."
    tar -xjf "$ASR_FILE"
    rm "$ASR_FILE"
    echo "ASR 模型下载完成！"
else
    echo "ASR 模型已存在，跳过下载"
fi

echo ""
echo "开始下载 TTS 模型..."
# 下载 TTS 模型
TTS_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/sherpa-onnx-vits-zh-ll.tar.bz2"
TTS_FILE="sherpa-onnx-vits-zh-ll.tar.bz2"

if [ ! -d "sherpa-onnx-vits-zh-ll" ]; then
    echo "正在下载 TTS 模型..."
    curl -L -o "$TTS_FILE" "$TTS_URL"
    echo "正在解压 TTS 模型..."
    tar -xjf "$TTS_FILE"
    rm "$TTS_FILE"
    echo "TTS 模型下载完成！"
else
    echo "TTS 模型已存在，跳过下载"
fi

echo ""
echo "所有模型下载完成！"
echo "模型目录结构："
ls -la
