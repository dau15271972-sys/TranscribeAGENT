# -*- coding: utf-8 -*-
from pyannote.audio import Pipeline
import torch
import os

# Читаем токен
token_file = os.path.join(os.path.dirname(__file__), '.hf_token')
with open(token_file, 'r') as f:
    hf_token = f.read().strip()

print("Загружаем пайплайн диаризации...")
print(f"Токен: {hf_token[:10]}...")

# Загружаем пайплайн (исправлено: token вместо use_auth_token)
pipeline = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-3.1",
    token=hf_token
)

print("✅ Пайплайн успешно загружен!")
print("Всё готово к работе с аудиофайлами!")