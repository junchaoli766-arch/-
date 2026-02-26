from typing import *
import os
import time
import sherpa_onnx
import logging
import numpy as np
import asyncio
import time
import soundfile
from scipy.signal import resample
import io
import re
import threading
import base64
logger = logging.getLogger(__file__)

splitter = re.compile(r'[,，。.!?！？;；、\n]')
_tts_engines = {}

tts_configs = {
    'sherpa-onnx-vits-zh-ll': {
        'model': 'model.onnx',
        'lexicon': 'lexicon.txt',
        'dict_dir': 'dict',
        'tokens': 'tokens.txt',
        'sample_rate': 16000,
        # 'rule_fsts': ['phone.fst', 'date.fst', 'number.fst'],
    },
    'vits-zh-hf-theresa': {
        'model': 'theresa.onnx',
        'lexicon': 'lexicon.txt',
        'dict_dir': 'dict',
        'tokens': 'tokens.txt',
        'sample_rate': 22050,
        # 'rule_fsts': ['phone.fst', 'date.fst', 'number.fst'],
    },
    'vits-melo-tts-zh_en': {
        'model': 'model.onnx',
        'lexicon': 'lexicon.txt',
        'dict_dir': 'dict',
        'tokens': 'tokens.txt',
        'sample_rate': 44100,
        'rule_fsts': ['phone.fst', 'date.fst', 'number.fst'],
    },
}


def load_tts_model(name: str, model_root: str, provider: str, num_threads: int = 1, max_num_sentences: int = 20) -> sherpa_onnx.OfflineTtsConfig:
    cfg = tts_configs[name]
    fsts = []
    model_dir = os.path.join(model_root, name)
    for f in cfg.get('rule_fsts', ''):
        fsts.append(os.path.join(model_dir, f))
    tts_rule_fsts = ','.join(fsts) if fsts else ''

    model_config = sherpa_onnx.OfflineTtsModelConfig(
        vits=sherpa_onnx.OfflineTtsVitsModelConfig(
            model=os.path.join(model_dir, cfg['model']),
            lexicon=os.path.join(model_dir, cfg['lexicon']),
            dict_dir=os.path.join(model_dir, cfg['dict_dir']),
            tokens=os.path.join(model_dir, cfg['tokens']),
        ),
        provider=provider,
        debug=0,
        num_threads=num_threads,
    )
    tts_config = sherpa_onnx.OfflineTtsConfig(
        model=model_config,
        rule_fsts=tts_rule_fsts,
        max_num_sentences=max_num_sentences)

    if not tts_config.validate():
        raise ValueError("tts: invalid config")

    return tts_config


def get_tts_engine(args) -> Tuple[sherpa_onnx.OfflineTts, int]:
    sample_rate = tts_configs[args.tts_model]['sample_rate']
    cache_engine = _tts_engines.get(args.tts_model)
    if cache_engine:
        return cache_engine, sample_rate
    st = time.time()
    tts_config = load_tts_model(
        args.tts_model, args.models_root, args.tts_provider)

    cache_engine = sherpa_onnx.OfflineTts(tts_config)
    elapsed = time.time() - st
    logger.info(f"tts: loaded {args.tts_model} in {elapsed:.2f}s")
    _tts_engines[args.tts_model] = cache_engine

    return cache_engine, sample_rate

# 1. 全局模型管理类
class TTSEngineManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if not cls._instance:
                cls._instance = super().__new__(cls)
                cls._instance.engine = None
            return cls._instance

    @classmethod
    def initialize(cls, args):
        instance = cls()
        if instance.engine is None:  # 安全访问属性
            instance.engine, instance.original_sample_rate = get_tts_engine(args)

    @classmethod
    def get_engine(cls):
        instance = cls()  # 确保实例存在
        return instance.engine,instance.original_sample_rate  # 安全访问属性


async def get_audio(text, voice_speed=1.0, voice_id=0, target_sample_rate = 16000):
    print("run_tts", text, voice_speed, voice_id)
    # 获取全局共享的ASR引擎
    tts_engine,original_sample_rate = TTSEngineManager.get_engine()

    # 将同步方法放入线程池执行
    loop = asyncio.get_event_loop()
    audio = await loop.run_in_executor(
        None,
        lambda: tts_engine.generate(text, voice_id, voice_speed)
    )
    # audio = tts_engine.generate(text, voice_id, voice_speed)
    samples = audio.samples
    
    # 确保 samples 是正确的格式
    if samples is None or len(samples) == 0:
        raise ValueError("TTS生成的音频数据为空")
    
    # 确保是 numpy 数组
    if not isinstance(samples, np.ndarray):
        samples = np.array(samples)
    
    # 确保是1D数组（单声道）
    if samples.ndim > 1:
        samples = samples.flatten()
    
    # 确保数据类型是 float32
    if samples.dtype != np.float32:
        samples = samples.astype(np.float32)
    
    # 确保值在 [-1.0, 1.0] 范围内
    if samples.max() > 1.0 or samples.min() < -1.0:
        samples = np.clip(samples, -1.0, 1.0)
    
    # 重采样处理
    current_sample_rate = getattr(audio, 'sample_rate', original_sample_rate)
    if target_sample_rate != current_sample_rate:
        num_samples = int(
            len(samples) * target_sample_rate / current_sample_rate)
        resampled_chunk = resample(samples, num_samples)
        samples = resampled_chunk.astype(np.float32)
        current_sample_rate = target_sample_rate
    
    # 确保采样率有效
    if current_sample_rate <= 0:
        current_sample_rate = target_sample_rate

    output = io.BytesIO()
    # 使用 soundfile 写入 WAV 格式数据（自动生成头部）
    try:
        soundfile.write(
            output,
            samples,  # 音频数据（numpy 数组）
            samplerate=int(current_sample_rate),  # 采样率（如 16000）
            subtype="PCM_16",  # 16-bit PCM 编码
            format="WAV"  # WAV 容器格式
        )
    except Exception as e:
        print(f"soundfile.write 错误: {e}")
        print(f"samples shape: {samples.shape}, dtype: {samples.dtype}")
        print(f"sample_rate: {current_sample_rate}")
        raise

    # 获取字节数据并 Base64 编码
    wav_data = output.getvalue()
    return base64.b64encode(wav_data).decode("utf-8")

    # import wave
    # import uuid
    # with wave.open('{}.wav'.format(uuid.uuid4()), 'w') as f:
    #     f.setnchannels(1)
    #     f.setsampwidth(2)
    #     f.setframerate(16000)
    #     f.writeframes(samples)
    # return base64.b64encode(samples).decode('utf-8')

