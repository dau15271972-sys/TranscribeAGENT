#!/usr/bin/env python3
"""
Voice Input — macOS Menu Bar App
Глобальная горячая клавиша Ctrl+Option для голосового ввода через Whisper.

Режимы:
  - Удержание Ctrl+Option: запись пока нажаты → отпустил → транскрипция
  - Двойное нажатие Ctrl+Option: toggle запись → нажал снова → транскрипция

Запуск: python3 voice-app.py
"""

import os
import sys
import time
import wave
import subprocess
import threading
import tempfile
from enum import Enum, auto
from pathlib import Path

import rumps
import numpy as np
import sounddevice as sd
from pynput import keyboard
# Foundation import не используется напрямую (rumps использует внутри)

# --- Конфигурация ---
WHISPER_CLI = "/opt/homebrew/bin/whisper-cli"
WHISPER_MODEL_LARGE = str(Path.home() / ".local/share/whisper-models/ggml-large-v3.bin")
WHISPER_MODEL_SMALL = "/opt/homebrew/share/whisper-cpp/models/ggml-small.bin"
# Используем small для скорости (1-2 сек), large для качества (5-15 сек)
WHISPER_MODEL = WHISPER_MODEL_SMALL
WHISPER_LANG = "ru"
SAMPLE_RATE = 16000
CHANNELS = 1

# Тайминги (секунды)
HOLD_THRESHOLD = 0.4    # если удерживать дольше — hold mode
DOUBLE_TAP_WINDOW = 0.5 # окно для второго нажатия
MAX_RECORDING_SEC = 500  # авто-стоп записи (секунды)

# Иконки (текст в menu bar)
ICON_READY = "🎙"
ICON_RECORDING = "⏺"
ICON_TRANSCRIBING = "⏳"


class State(Enum):
    IDLE = auto()
    RECORDING_HOLD = auto()
    RECORDING_TOGGLE = auto()
    TRANSCRIBING = auto()


class VoiceInputApp(rumps.App):
    def __init__(self):
        super().__init__(ICON_READY, quit_button=None)
        self.state = State.IDLE
        self.audio_frames = []
        self.stream = None
        self.tmp_wav = os.path.join(tempfile.gettempdir(), "voice-input-app.wav")

        # Стейт-машина для горячих клавиш
        self._ctrl_pressed = False
        self._option_pressed = False
        self._combo_press_time = 0.0
        self._combo_release_time = 0.0
        self._waiting_for_double_tap = False
        self._hold_timer = None
        self._recording_start_time = 0.0
        self._recording_watchdog = None

        # Menu items
        self._stop_item = rumps.MenuItem("⏹ Остановить запись", callback=self._manual_stop)
        self._stop_item.set_callback(None)  # disabled by default
        self.menu = [
            rumps.MenuItem("Voice Input", callback=None),
            None,  # separator
            self._stop_item,
            None,
            rumps.MenuItem(f"Модель: {Path(WHISPER_MODEL).stem}", callback=None),
            rumps.MenuItem(f"Язык: {WHISPER_LANG}", callback=None),
            None,
            rumps.MenuItem("Выход", callback=self._quit),
        ]

        # Pending icon update (thread-safe)
        self._pending_icon = None

        # Запускаем слушатель клавиш в отдельном потоке
        self._start_key_listener()

        # Таймер для обновления иконки из main thread (каждые 0.1с)
        self._icon_timer = rumps.Timer(self._update_icon_tick, 0.1)
        self._icon_timer.start()

    def _start_key_listener(self):
        listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        listener.daemon = True
        listener.start()

    def _combo_active(self):
        return self._ctrl_pressed and self._option_pressed

    def _on_key_press(self, key):
        try:
            if key == keyboard.Key.ctrl_l or key == keyboard.Key.ctrl_r:
                self._ctrl_pressed = True
            elif key == keyboard.Key.alt_l or key == keyboard.Key.alt_r:
                self._option_pressed = True

            if self._combo_active():
                self._on_combo_press()
        except Exception as e:
            print(f"⚠️  Key press error: {e}", file=sys.stderr)

    def _on_key_release(self, key):
        try:
            was_combo = self._combo_active()

            if key == keyboard.Key.ctrl_l or key == keyboard.Key.ctrl_r:
                self._ctrl_pressed = False
            elif key == keyboard.Key.alt_l or key == keyboard.Key.alt_r:
                self._option_pressed = False

            if was_combo and not self._combo_active():
                self._on_combo_release()
        except Exception as e:
            print(f"⚠️  Key release error: {e}", file=sys.stderr)

    def _on_combo_press(self):
        now = time.time()

        if self.state == State.TRANSCRIBING:
            return

        if self.state == State.RECORDING_TOGGLE:
            # Нажали комбо во время toggle-записи → остановить
            self._stop_recording_and_transcribe()
            return

        if self.state == State.IDLE:
            if self._waiting_for_double_tap and (now - self._combo_release_time) < DOUBLE_TAP_WINDOW:
                # Второе нажатие — toggle mode
                self._waiting_for_double_tap = False
                if self._hold_timer:
                    self._hold_timer.cancel()
                    self._hold_timer = None
                self._start_recording(State.RECORDING_TOGGLE)
                return

            # Первое нажатие — запоминаем время, запускаем таймер для hold mode
            self._combo_press_time = now
            self._waiting_for_double_tap = False

            # Таймер: если через HOLD_THRESHOLD клавиши всё ещё нажаты → hold mode
            self._hold_timer = threading.Timer(HOLD_THRESHOLD, self._check_hold_mode)
            self._hold_timer.daemon = True
            self._hold_timer.start()

    def _check_hold_mode(self):
        """Вызывается через HOLD_THRESHOLD — если клавиши всё ещё нажаты, начинаем запись."""
        if self._combo_active() and self.state == State.IDLE:
            self._start_recording(State.RECORDING_HOLD)

    def _on_combo_release(self):
        now = time.time()
        held_duration = now - self._combo_press_time

        if self._hold_timer:
            self._hold_timer.cancel()
            self._hold_timer = None

        if self.state == State.RECORDING_HOLD:
            # Отпустили клавиши в hold mode → транскрибируем
            self._stop_recording_and_transcribe()
            return

        if self.state == State.IDLE and held_duration < HOLD_THRESHOLD:
            # Короткое нажатие — ждём второго для double-tap
            self._combo_release_time = now
            self._waiting_for_double_tap = True

            # Таймер сброса ожидания double-tap
            t = threading.Timer(DOUBLE_TAP_WINDOW, self._reset_double_tap)
            t.daemon = True
            t.start()

    def _reset_double_tap(self):
        self._waiting_for_double_tap = False

    def _manual_stop(self, _):
        """Ручная остановка записи через меню."""
        if self.state in (State.RECORDING_HOLD, State.RECORDING_TOGGLE):
            print("⏹ Ручная остановка записи")
            self._stop_recording_and_transcribe()

    def _recording_timeout(self):
        """Watchdog: авто-стоп если запись длится слишком долго."""
        if self.state in (State.RECORDING_HOLD, State.RECORDING_TOGGLE):
            elapsed = time.time() - self._recording_start_time
            print(f"⏹ Авто-стоп записи ({elapsed:.0f}s, макс {MAX_RECORDING_SEC}s)")
            self._stop_recording_and_transcribe()

    def _start_recording(self, mode):
        if self.state in (State.RECORDING_HOLD, State.RECORDING_TOGGLE, State.TRANSCRIBING):
            return

        self.state = mode
        self.audio_frames = []
        self._recording_start_time = time.time()
        self._set_icon(ICON_RECORDING)
        self._stop_item.set_callback(self._manual_stop)  # enable menu item
        print(f"🔴 Запись ({mode.name})...")

        # Watchdog таймер — авто-стоп через MAX_RECORDING_SEC
        if self._recording_watchdog:
            self._recording_watchdog.cancel()
        self._recording_watchdog = threading.Timer(MAX_RECORDING_SEC, self._recording_timeout)
        self._recording_watchdog.daemon = True
        self._recording_watchdog.start()

        def audio_callback(indata, frames, time_info, status):
            self.audio_frames.append(indata.copy())

        try:
            self.stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                callback=audio_callback,
            )
            self.stream.start()
        except Exception as e:
            print(f"Ошибка записи: {e}", file=sys.stderr)
            self.state = State.IDLE
            self._set_icon(ICON_READY)
            self._stop_item.set_callback(None)

    def _stop_recording_and_transcribe(self):
        # Отменяем watchdog
        if self._recording_watchdog:
            self._recording_watchdog.cancel()
            self._recording_watchdog = None

        # Disable menu stop button
        self._stop_item.set_callback(None)

        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception as e:
                print(f"⚠️  Ошибка остановки stream: {e}", file=sys.stderr)
            self.stream = None

        if not self.audio_frames:
            self.state = State.IDLE
            self._set_icon(ICON_READY)
            return

        self.state = State.TRANSCRIBING
        self._set_icon(ICON_TRANSCRIBING)

        # Сохраняем WAV и транскрибируем в фоне
        audio_data = np.concatenate(self.audio_frames)
        self.audio_frames = []

        thread = threading.Thread(target=self._transcribe, args=(audio_data,), daemon=True)
        thread.start()

    def _transcribe(self, audio_data):
        try:
            # Сохраняем WAV
            with wave.open(self.tmp_wav, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(2)  # int16
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(audio_data.tobytes())

            duration = len(audio_data) / SAMPLE_RATE
            print(f"🟡 Транскрибирую ({duration:.1f}s аудио)...")

            if duration < 0.5:
                print("⚠️  Слишком короткая запись, пропускаю")
                self.state = State.IDLE
                self._set_icon(ICON_READY)
                return

            # Проверка громкости — фильтр тишины и шума
            rms = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2))
            print(f"🔊 Громкость (RMS): {rms:.0f}")
            if rms < 200:
                print("⚠️  Тишина/шум, пропускаю (RMS < 200)")
                self.state = State.IDLE
                self._set_icon(ICON_READY)
                return

            # Запускаем whisper-cli
            t_start = time.time()
            result = subprocess.run(
                [
                    WHISPER_CLI,
                    "-m", WHISPER_MODEL,
                    "-l", WHISPER_LANG,
                    "-f", self.tmp_wav,
                    "--no-timestamps",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            # Парсим результат (убираем пустые строки и пробелы)
            text = "\n".join(
                line.strip()
                for line in result.stdout.splitlines()
                if line.strip()
                and not line.strip().startswith("main:")
                and not line.strip().startswith("whisper_")
                and not line.strip().startswith("ggml_")
                and not line.strip().startswith("metal_")
                and not line.strip().startswith("system_info")
            ).strip()

            t_elapsed = time.time() - t_start
            print(f"⏱  Whisper: {t_elapsed:.1f}s")

            if result.returncode != 0:
                print(f"❌ whisper-cli ошибка (code {result.returncode})")
                print(f"   stderr: {result.stderr[:200]}")
                return

            # Фильтр галлюцинаций Whisper (субтитры, музыка и т.д.)
            hallucination_markers = [
                "субтитр", "редактор", "корректор", "переводчик",
                "подписывайтесь", "ставьте лайк", "музыка",
                "♪", "♫", "[", "]", "(", ")",
                "subtitles", "subscribe", "thank you for watching",
            ]
            if text and any(m in text.lower() for m in hallucination_markers):
                print(f"⚠️  Галлюцинация Whisper отфильтрована: {text[:80]}")
                text = None

            if text:
                print(f"📝 Результат: {text[:100]}")
                self._paste_text(text)
            else:
                print("⚠️  Пустой результат от whisper")

        except subprocess.TimeoutExpired:
            print("❌ Whisper timeout (>60s)", file=sys.stderr)
        except Exception as e:
            print(f"❌ Ошибка транскрипции: {e}", file=sys.stderr)
        finally:
            self.state = State.IDLE
            self._set_icon(ICON_READY)
            # Сброс состояния клавиш (защита от залипания)
            self._ctrl_pressed = False
            self._option_pressed = False
            # Чистим tmp файл
            try:
                os.unlink(self.tmp_wav)
            except OSError:
                pass

    def _paste_text(self, text):
        """Копируем текст в буфер обмена и вставляем Cmd+V."""
        # pbcopy
        proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        proc.communicate(text.encode("utf-8"))
        print(f"📋 Скопировано в буфер")

        # Пауза чтобы буфер обновился
        time.sleep(0.15)

        # Cmd+V через CGEvent (более надёжно чем AppleScript)
        try:
            from Quartz import (
                CGEventCreateKeyboardEvent, CGEventSetFlags,
                CGEventPost, kCGHIDEventTap, kCGEventFlagMaskCommand,
            )
            # Key down
            event = CGEventCreateKeyboardEvent(None, 0x09, True)  # 0x09 = 'v'
            CGEventSetFlags(event, kCGEventFlagMaskCommand)
            CGEventPost(kCGHIDEventTap, event)
            # Key up
            event = CGEventCreateKeyboardEvent(None, 0x09, False)
            CGEventSetFlags(event, kCGEventFlagMaskCommand)
            CGEventPost(kCGHIDEventTap, event)
            print(f"✅ Cmd+V отправлен")
        except Exception as e:
            print(f"⚠️  CGEvent не сработал: {e}, пробую AppleScript...")
            subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to keystroke "v" using command down'],
                capture_output=True,
            )

    def _update_icon_tick(self, _):
        """Main-thread callback: обновляет иконку если есть pending."""
        if self._pending_icon is not None:
            self.title = self._pending_icon
            self._pending_icon = None

    def _set_icon(self, icon):
        """Thread-safe обновление иконки (через polling из main thread)."""
        self._pending_icon = icon

    def _quit(self, _):
        if self.stream:
            self.stream.stop()
            self.stream.close()
        rumps.quit_application()


if __name__ == "__main__":
    # Проверяем зависимости
    if not os.path.exists(WHISPER_CLI):
        print(f"Ошибка: whisper-cli не найден: {WHISPER_CLI}")
        print("Установи: brew install whisper-cpp")
        sys.exit(1)

    if not os.path.exists(WHISPER_MODEL):
        print(f"Ошибка: модель не найдена: {WHISPER_MODEL}")
        print("Скачай модель large-v3")
        sys.exit(1)

    print("✅ Voice Input запущен. Ctrl+Option — запись. Ctrl+C — выход.")
    app = VoiceInputApp()
    app.run()
