#!/usr/bin/env python3
"""
Voice Input — Windows System Tray App (faster-whisper)

Голосовой ввод через локальный Whisper. Без whisper-cli.exe,
без интернета, без токенов — всё работает через faster-whisper Python API.

Горячая клавиша: Ctrl+Alt
  - Удержание: держишь Ctrl+Alt → говоришь → отпускаешь → текст вставляется
  - Двойное нажатие: быстро Ctrl+Alt дважды → говоришь → снова Ctrl+Alt → вставляется

Иконка в трее:
  Зелёный  — готов
  Красный  — идёт запись
  Жёлтый   — транскрипция

Запуск:
  .venv\\Scripts\\python voice-input-windows.py
"""

import os
import sys
import time
import wave
import threading
import tempfile
from enum import Enum, auto

import numpy as np
import sounddevice as sd
import pyperclip
from pynput import keyboard
from pynput.keyboard import Key, Controller as KeyController
from PIL import Image, ImageDraw
import pystray
from faster_whisper import WhisperModel

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------
MODEL_SIZE = "small"
# tiny     ~40 MB,  мгновенно (<0.3s),  хуже качество
# base     ~75 MB,  ~0.3s,              приемлемо
# small    ~240 MB, ~0.5-1s,            хорошее качество  <-- рекомендуется
# medium   ~770 MB, ~1-3s,              очень хорошее
# large-v3 ~3 GB,   ~3-8s,              лучшее качество

LANGUAGE = "ru"          # ru / en / None (авто-определение)
SAMPLE_RATE = 16000
CHANNELS = 1

# Устройство записи: None = системный дефолт, или номер из списка ниже
# При старте выводится список всех микрофонов с их номерами
DEVICE = None            # например: DEVICE = 1  для C922 Webcam

# Тайминги (секунды)
HOLD_THRESHOLD = 0.4       # удержание дольше → hold-режим
DOUBLE_TAP_WINDOW = 0.5    # окно для второго нажатия (toggle-режим)
MAX_RECORDING_SEC = 120    # авто-стоп записи

# Фильтр тишины
MIN_RMS = 150              # ниже — не отправлять в whisper

# Галлюцинации whisper — эти фразы игнорируем
HALLUCINATIONS = [
    "субтитр", "редактор", "корректор", "переводчик",
    "подписывайтесь", "ставьте лайк", "музыка",
    "♪", "♫", "subtitles", "subscribe", "thank you for watching",
]

# Цвета иконок
COLOR_READY        = (0,   180,   0)
COLOR_RECORDING    = (220,  30,  30)
COLOR_TRANSCRIBING = (220, 180,   0)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def make_icon(color, size=64):
    """Круглая иконка для системного трея."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = 4
    d.ellipse([m, m, size - m, size - m], fill=color + (255,))
    return img


def detect_device():
    """Авто-выбор устройства: CUDA если есть, иначе CPU."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda", "float16"
    except ImportError:
        pass
    return "cpu", "int8"


# ---------------------------------------------------------------------------
# Стейт-машина
# ---------------------------------------------------------------------------

class State(Enum):
    IDLE              = auto()
    RECORDING_HOLD    = auto()
    RECORDING_TOGGLE  = auto()
    TRANSCRIBING      = auto()


# ---------------------------------------------------------------------------
# Приложение
# ---------------------------------------------------------------------------

class VoiceInputApp:

    def __init__(self):
        self.state = State.IDLE
        self.audio_frames = []
        self.stream = None
        self._tmp_dir = tempfile.gettempdir()
        self.kb = KeyController()

        # Стейт горячих клавиш
        self._ctrl = False
        self._alt = False
        self._press_time = 0.0
        self._release_time = 0.0
        self._double_tap_waiting = False
        self._hold_timer = None
        self._watchdog = None

        # Иконки
        self._icons = {
            "ready":        make_icon(COLOR_READY),
            "recording":    make_icon(COLOR_RECORDING),
            "transcribing": make_icon(COLOR_TRANSCRIBING),
        }

        # Загрузка модели (один раз при старте)
        device, compute_type = detect_device()
        print(f"[VoiceInput] Загружаю faster-whisper '{MODEL_SIZE}' на {device.upper()}...")
        print(f"             (первый запуск — модель скачается автоматически ~240 MB)")
        self.model = WhisperModel(MODEL_SIZE, device=device, compute_type=compute_type)
        print(f"[VoiceInput] Модель готова. Устройство: {device.upper()}")

        # Системный трей
        menu = pystray.Menu(
            pystray.MenuItem("Voice Input", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"Модель: {MODEL_SIZE}", None, enabled=False),
            pystray.MenuItem(f"Язык: {LANGUAGE or 'авто'}", None, enabled=False),
            pystray.MenuItem(f"Устройство: {device.upper()}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", self._quit),
        )
        self.tray = pystray.Icon(
            "VoiceInput",
            self._icons["ready"],
            "Voice Input — Готов",
            menu,
        )

    # ------------------------------------------------------------------
    # Запуск
    # ------------------------------------------------------------------

    def run(self):
        listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        listener.daemon = True
        listener.start()

        # Список микрофонов
        print("[VoiceInput] Доступные микрофоны:")
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                marker = " <-- используется" if (DEVICE is None and i == sd.default.device[0]) or i == DEVICE else ""
                print(f"  [{i}] {d['name']}{marker}")
        if DEVICE is not None:
            print(f"[VoiceInput] Выбран микрофон: [{DEVICE}]")
        else:
            print(f"[VoiceInput] Микрофон: системный дефолт [{sd.default.device[0]}]")
            print(f"             Чтобы сменить — задай DEVICE=<номер> в коде")
        print("[VoiceInput] Запущен. Иконка в системном трее (рядом с часами).")
        print("[VoiceInput] Ctrl+Alt — начать запись (удержание или двойное нажатие).")
        print("")
        self.tray.run()

    # ------------------------------------------------------------------
    # Обработка горячих клавиш
    # ------------------------------------------------------------------

    def _combo(self):
        return self._ctrl and self._alt

    def _on_press(self, key):
        try:
            if key in (Key.ctrl_l, Key.ctrl_r):
                self._ctrl = True
            elif key in (Key.alt_l, Key.alt_r):
                self._alt = True
            if self._combo():
                self._on_combo_press()
        except Exception as e:
            print(f"[VoiceInput] key press error: {e}", file=sys.stderr)

    def _on_release(self, key):
        try:
            was = self._combo()
            if key in (Key.ctrl_l, Key.ctrl_r):
                self._ctrl = False
            elif key in (Key.alt_l, Key.alt_r):
                self._alt = False
            if was and not self._combo():
                self._on_combo_release()
        except Exception as e:
            print(f"[VoiceInput] key release error: {e}", file=sys.stderr)

    def _on_combo_press(self):
        now = time.time()

        if self.state == State.TRANSCRIBING:
            return

        if self.state == State.RECORDING_TOGGLE:
            self._stop_and_transcribe()
            return

        if self.state == State.IDLE:
            if self._double_tap_waiting and (now - self._release_time) < DOUBLE_TAP_WINDOW:
                self._double_tap_waiting = False
                if self._hold_timer:
                    self._hold_timer.cancel()
                    self._hold_timer = None
                self._start_recording(State.RECORDING_TOGGLE)
                return

            self._press_time = now
            self._double_tap_waiting = False
            self._hold_timer = threading.Timer(HOLD_THRESHOLD, self._maybe_hold)
            self._hold_timer.daemon = True
            self._hold_timer.start()

    def _maybe_hold(self):
        if self._combo() and self.state == State.IDLE:
            self._start_recording(State.RECORDING_HOLD)

    def _on_combo_release(self):
        now = time.time()
        held = now - self._press_time

        if self._hold_timer:
            self._hold_timer.cancel()
            self._hold_timer = None

        if self.state == State.RECORDING_HOLD:
            self._stop_and_transcribe()
            return

        if self.state == State.IDLE and held < HOLD_THRESHOLD:
            self._release_time = now
            self._double_tap_waiting = True
            t = threading.Timer(DOUBLE_TAP_WINDOW, self._cancel_double_tap)
            t.daemon = True
            t.start()

    def _cancel_double_tap(self):
        self._double_tap_waiting = False

    # ------------------------------------------------------------------
    # Запись аудио
    # ------------------------------------------------------------------

    def _start_recording(self, mode):
        if self.state not in (State.IDLE,):
            return

        self.state = mode
        self.audio_frames = []
        self._set_icon("recording")
        print(f"[VoiceInput] Запись ({mode.name})...")

        # Watchdog авто-стоп
        if self._watchdog:
            self._watchdog.cancel()
        self._watchdog = threading.Timer(MAX_RECORDING_SEC, self._watchdog_stop)
        self._watchdog.daemon = True
        self._watchdog.start()

        def callback(indata, frames, time_info, status):
            self.audio_frames.append(indata.copy())

        try:
            self.stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                device=DEVICE,
                callback=callback,
            )
            self.stream.start()
        except Exception as e:
            print(f"[VoiceInput] Ошибка микрофона: {e}", file=sys.stderr)
            self.state = State.IDLE
            self._set_icon("ready")

    def _watchdog_stop(self):
        if self.state in (State.RECORDING_HOLD, State.RECORDING_TOGGLE):
            print(f"[VoiceInput] Авто-стоп ({MAX_RECORDING_SEC}s)")
            self._stop_and_transcribe()

    def _stop_and_transcribe(self):
        if self._watchdog:
            self._watchdog.cancel()
            self._watchdog = None

        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

        if not self.audio_frames:
            self.state = State.IDLE
            self._set_icon("ready")
            return

        self.state = State.TRANSCRIBING
        self._set_icon("transcribing")

        audio_data = np.concatenate(self.audio_frames)
        self.audio_frames = []

        # Сброс состояния клавиш (защита от залипания)
        self._ctrl = False
        self._alt = False

        threading.Thread(target=self._transcribe, args=(audio_data,), daemon=True).start()

    # ------------------------------------------------------------------
    # Транскрипция через faster-whisper
    # ------------------------------------------------------------------

    def _transcribe(self, audio_data):
        # Уникальный файл для каждой транскрипции — избегаем гонки состояний
        tmp_wav = os.path.join(self._tmp_dir, f"voice-input-{time.monotonic_ns()}.wav")
        try:
            duration = len(audio_data) / SAMPLE_RATE
            print(f"[VoiceInput] Транскрибирую ({duration:.1f}s аудио)...")

            if duration < 0.5:
                print("[VoiceInput] Слишком коротко, пропускаю.")
                return

            # Фильтр тишины по RMS
            rms = float(np.sqrt(np.mean(audio_data.astype(np.float32) ** 2)))
            if rms < MIN_RMS:
                print(f"[VoiceInput] Тишина (RMS={rms:.0f} < {MIN_RMS}), пропускаю.")
                return

            # Пишем WAV
            with wave.open(tmp_wav, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(audio_data.tobytes())

            t0 = time.time()

            segments, info = self.model.transcribe(
                tmp_wav,
                language=LANGUAGE,
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=300),
            )
            text = " ".join(s.text.strip() for s in segments).strip()

            elapsed = time.time() - t0
            print(f"[VoiceInput] {elapsed:.1f}s | lang={info.language} ({info.language_probability:.0%})")

            # Фильтр галлюцинаций
            if text and any(m in text.lower() for m in HALLUCINATIONS):
                print(f"[VoiceInput] Галлюцинация отфильтрована: {text[:80]}")
                return

            if text:
                print(f"[VoiceInput] Результат: {text[:120]}")
                self._paste(text)
            else:
                print("[VoiceInput] Пустой результат.")

        except Exception as e:
            print(f"[VoiceInput] Ошибка: {e}", file=sys.stderr)
        finally:
            self.state = State.IDLE
            self._set_icon("ready")
            try:
                os.unlink(tmp_wav)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Вставка текста
    # ------------------------------------------------------------------

    def _paste(self, text):
        """Копирует в буфер → Ctrl+V в активном окне."""
        pyperclip.copy(text)
        time.sleep(0.15)
        try:
            self.kb.press(Key.ctrl_l)
            self.kb.press("v")
            self.kb.release("v")
            self.kb.release(Key.ctrl_l)
            print("[VoiceInput] Вставлено.")
        except Exception as e:
            print(f"[VoiceInput] Ошибка вставки: {e}")

    # ------------------------------------------------------------------
    # Иконка
    # ------------------------------------------------------------------

    def _set_icon(self, name):
        labels = {
            "ready":        "Voice Input — Готов",
            "recording":    "Voice Input — ЗАПИСЬ",
            "transcribing": "Voice Input — Транскрипция...",
        }
        try:
            self.tray.icon = self._icons[name]
            self.tray.title = labels.get(name, "Voice Input")
        except Exception:
            pass

    def _quit(self, icon, item):
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
        self.tray.stop()


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app = VoiceInputApp()
    app.run()
