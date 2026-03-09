# Voice Input App — Установка на Windows

Голосовой ввод через локальный Whisper. Нажимаешь Ctrl+Alt — говоришь — текст вставляется в активное окно.
Работает полностью локально, без интернета.

---

## Что это

Системный tray-приложение на Python. Глобальная горячая клавиша **Ctrl+Alt**.

- **Удержание:** держишь Ctrl+Alt → говоришь → отпускаешь → текст вставляется
- **Двойное нажатие:** быстро Ctrl+Alt дважды → говоришь → нажимаешь ещё раз → текст вставляется
- **Индикатор:** иконка в системном трее меняет цвет (зелёный/красный/жёлтый)
- **Модель:** whisper.cpp small (~0.5 сек) или large-v3 (лучше качество, ~3-5 сек)
- **Язык:** русский

---

## Шаг 1: Установить Python 3.11+

Если нет Python:
```powershell
winget install Python.Python.3.12
```
Или скачай с https://www.python.org/downloads/
**ВАЖНО:** при установке отметь "Add Python to PATH".

Проверка:
```powershell
python --version
pip --version
```

---

## Шаг 2: Установить whisper.cpp для Windows

### Вариант A: Скачать готовый бинарник (рекомендуется)

1. Перейди на https://github.com/ggerganov/whisper.cpp/releases
2. Скачай последний `whisper-*-bin-x64.zip` (или `whisper-*-cublas-*-x64.zip` если есть NVIDIA GPU)
3. Распакуй в `C:\whisper-cpp\`
4. Проверь что есть `C:\whisper-cpp\whisper-cli.exe`

### Вариант B: Через winget/scoop

```powershell
scoop install whisper-cpp
```

### Проверка:
```powershell
C:\whisper-cpp\whisper-cli.exe --help
```

---

## Шаг 3: Скачать модель Whisper

```powershell
# Создать папку для моделей
mkdir C:\whisper-cpp\models

# Small модель (466MB, быстрая, ~0.5 сек)
curl -L "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin" -o C:\whisper-cpp\models\ggml-small.bin
```

Опционально — large-v3 для лучшего качества (3GB):
```powershell
curl -L "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin" -o C:\whisper-cpp\models\ggml-large-v3.bin
```

---

## Шаг 4: Установить Python зависимости

```powershell
pip install pystray Pillow pynput sounddevice numpy pyperclip
```

| Пакет | Назначение |
|-------|------------|
| pystray | Иконка в системном трее Windows |
| Pillow | Генерация цветных иконок |
| pynput | Глобальные горячие клавиши |
| sounddevice | Запись аудио с микрофона |
| numpy | Буфер аудио |
| pyperclip | Работа с буфером обмена |

---

## Шаг 5: Создать файл voice-app.py

Создай папку и файл:
```powershell
mkdir C:\VoiceInput
```

Создай файл `C:\VoiceInput\voice-app.py` с содержимым ниже.

---

## Полный код voice-app.py (Windows)

```python
#!/usr/bin/env python3
"""
Voice Input — Windows System Tray App
Глобальная горячая клавиша Ctrl+Alt для голосового ввода через Whisper.

Режимы:
  - Удержание Ctrl+Alt: запись пока нажаты → отпустил → транскрипция
  - Двойное нажатие Ctrl+Alt: toggle запись → нажал снова → транскрипция

Запуск: python voice-app.py
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

import numpy as np
import sounddevice as sd
import pyperclip
from pynput import keyboard
from pynput.keyboard import Key, Controller as KeyController
from PIL import Image, ImageDraw
import pystray

# --- Конфигурация ---
# Пути к whisper-cli и модели
# ВАЖНО: измени эти пути если whisper установлен в другом месте
WHISPER_CLI = r"C:\whisper-cpp\whisper-cli.exe"
WHISPER_MODEL_SMALL = r"C:\whisper-cpp\models\ggml-small.bin"
WHISPER_MODEL_LARGE = r"C:\whisper-cpp\models\ggml-large-v3.bin"
# Используем small для скорости (0.5-2 сек), large для качества (3-15 сек)
WHISPER_MODEL = WHISPER_MODEL_SMALL
WHISPER_LANG = "ru"
SAMPLE_RATE = 16000
CHANNELS = 1

# Тайминги (секунды)
HOLD_THRESHOLD = 0.4    # если удерживать дольше — hold mode
DOUBLE_TAP_WINDOW = 0.5 # окно для второго нажатия

# Цвета иконок (RGB)
COLOR_READY = (0, 180, 0)       # зелёный — готов
COLOR_RECORDING = (220, 30, 30) # красный — запись
COLOR_TRANSCRIBING = (220, 180, 0) # жёлтый — транскрипция


def create_icon_image(color, size=64):
    """Создаёт круглую иконку заданного цвета для системного трея."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = 4
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill=color + (255,),
    )
    return image


class State(Enum):
    IDLE = auto()
    RECORDING_HOLD = auto()
    RECORDING_TOGGLE = auto()
    TRANSCRIBING = auto()


class VoiceInputApp:
    def __init__(self):
        self.state = State.IDLE
        self.audio_frames = []
        self.stream = None
        self.tmp_wav = os.path.join(tempfile.gettempdir(), "voice-input-app.wav")
        self.kb_controller = KeyController()

        # Стейт-машина для горячих клавиш
        self._ctrl_pressed = False
        self._alt_pressed = False
        self._combo_press_time = 0.0
        self._combo_release_time = 0.0
        self._waiting_for_double_tap = False
        self._hold_timer = None

        # Создаём иконки
        self._icons = {
            "ready": create_icon_image(COLOR_READY),
            "recording": create_icon_image(COLOR_RECORDING),
            "transcribing": create_icon_image(COLOR_TRANSCRIBING),
        }

        # Системный трей
        menu = pystray.Menu(
            pystray.MenuItem("Voice Input", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"Модель: {Path(WHISPER_MODEL).stem}", None, enabled=False),
            pystray.MenuItem(f"Язык: {WHISPER_LANG}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Выход", self._quit),
        )

        self.tray = pystray.Icon(
            "VoiceInput",
            self._icons["ready"],
            "Voice Input — Готов",
            menu,
        )

    def run(self):
        """Запускает приложение."""
        # Запускаем слушатель клавиш
        listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        listener.daemon = True
        listener.start()

        print("Voice Input запущен")
        print("Горячая клавиша: Ctrl+Alt")
        print("  Удержать — запись пока нажаты")
        print("  Двойное нажатие — toggle запись")
        print("")

        # Запускаем трей (блокирующий вызов)
        self.tray.run()

    def _combo_active(self):
        return self._ctrl_pressed and self._alt_pressed

    def _on_key_press(self, key):
        if key == Key.ctrl_l or key == Key.ctrl_r:
            self._ctrl_pressed = True
        elif key == Key.alt_l or key == Key.alt_r:
            self._alt_pressed = True

        if self._combo_active():
            self._on_combo_press()

    def _on_key_release(self, key):
        was_combo = self._combo_active()

        if key == Key.ctrl_l or key == Key.ctrl_r:
            self._ctrl_pressed = False
        elif key == Key.alt_l or key == Key.alt_r:
            self._alt_pressed = False

        if was_combo and not self._combo_active():
            self._on_combo_release()

    def _on_combo_press(self):
        now = time.time()

        if self.state == State.TRANSCRIBING:
            return

        if self.state == State.RECORDING_TOGGLE:
            self._stop_recording_and_transcribe()
            return

        if self.state == State.IDLE:
            if self._waiting_for_double_tap and (now - self._combo_release_time) < DOUBLE_TAP_WINDOW:
                self._waiting_for_double_tap = False
                if self._hold_timer:
                    self._hold_timer.cancel()
                    self._hold_timer = None
                self._start_recording(State.RECORDING_TOGGLE)
                return

            self._combo_press_time = now
            self._waiting_for_double_tap = False

            self._hold_timer = threading.Timer(HOLD_THRESHOLD, self._check_hold_mode)
            self._hold_timer.daemon = True
            self._hold_timer.start()

    def _check_hold_mode(self):
        if self._combo_active() and self.state == State.IDLE:
            self._start_recording(State.RECORDING_HOLD)

    def _on_combo_release(self):
        now = time.time()
        held_duration = now - self._combo_press_time

        if self._hold_timer:
            self._hold_timer.cancel()
            self._hold_timer = None

        if self.state == State.RECORDING_HOLD:
            self._stop_recording_and_transcribe()
            return

        if self.state == State.IDLE and held_duration < HOLD_THRESHOLD:
            self._combo_release_time = now
            self._waiting_for_double_tap = True

            t = threading.Timer(DOUBLE_TAP_WINDOW, self._reset_double_tap)
            t.daemon = True
            t.start()

    def _reset_double_tap(self):
        self._waiting_for_double_tap = False

    def _start_recording(self, mode):
        if self.state in (State.RECORDING_HOLD, State.RECORDING_TOGGLE, State.TRANSCRIBING):
            return

        self.state = mode
        self.audio_frames = []
        self._set_icon("recording")
        print(f"🔴 Запись ({mode.name})...")

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
            self._set_icon("ready")

    def _stop_recording_and_transcribe(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        if not self.audio_frames:
            self.state = State.IDLE
            self._set_icon("ready")
            return

        self.state = State.TRANSCRIBING
        self._set_icon("transcribing")

        audio_data = np.concatenate(self.audio_frames)
        self.audio_frames = []

        thread = threading.Thread(target=self._transcribe, args=(audio_data,), daemon=True)
        thread.start()

    def _transcribe(self, audio_data):
        try:
            with wave.open(self.tmp_wav, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(2)  # int16
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(audio_data.tobytes())

            duration = len(audio_data) / SAMPLE_RATE
            print(f"🟡 Транскрибирую ({duration:.1f}s аудио)...")

            if duration < 0.5:
                print("⚠️  Слишком короткая запись")
                self.state = State.IDLE
                self._set_icon("ready")
                return

            t_start = time.time()

            # Запускаем whisper-cli
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
                creationflags=subprocess.CREATE_NO_WINDOW,  # не показывать окно CMD
            )

            # Парсим результат
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
            self._set_icon("ready")
            try:
                os.unlink(self.tmp_wav)
            except OSError:
                pass

    def _paste_text(self, text):
        """Копируем текст в буфер обмена и вставляем Ctrl+V."""
        pyperclip.copy(text)
        print("📋 Скопировано в буфер")

        time.sleep(0.15)

        # Ctrl+V через pynput
        try:
            self.kb_controller.press(Key.ctrl_l)
            self.kb_controller.press('v')
            self.kb_controller.release('v')
            self.kb_controller.release(Key.ctrl_l)
            print("✅ Ctrl+V отправлен")
        except Exception as e:
            print(f"⚠️  Ошибка вставки: {e}")

    def _set_icon(self, icon_name):
        """Обновляем иконку в системном трее."""
        tooltips = {
            "ready": "Voice Input — Готов",
            "recording": "Voice Input — 🔴 ЗАПИСЬ",
            "transcribing": "Voice Input — 🟡 Транскрипция...",
        }
        try:
            self.tray.icon = self._icons[icon_name]
            self.tray.title = tooltips.get(icon_name, "Voice Input")
        except Exception:
            pass

    def _quit(self, icon, item):
        """Выход из приложения."""
        if self.stream:
            self.stream.stop()
            self.stream.close()
        self.tray.stop()


if __name__ == "__main__":
    # Проверяем зависимости
    if not os.path.exists(WHISPER_CLI):
        print(f"Ошибка: whisper-cli не найден: {WHISPER_CLI}")
        print("Скачай с https://github.com/ggerganov/whisper.cpp/releases")
        print("Распакуй в C:\\whisper-cpp\\")
        sys.exit(1)

    if not os.path.exists(WHISPER_MODEL):
        print(f"Ошибка: модель не найдена: {WHISPER_MODEL}")
        print("Скачай: curl -L https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin -o C:\\whisper-cpp\\models\\ggml-small.bin")
        sys.exit(1)

    app = VoiceInputApp()
    app.run()
```

---

## Шаг 6: Запуск

```powershell
cd C:\VoiceInput
python voice-app.py
```

В системном трее (рядом с часами) появится зелёный кружок.

---

## Шаг 7: Проверка

1. Открой любой текстовый редактор или браузер
2. Удержи **Ctrl+Alt** → говори → отпусти
3. Текст должен вставиться в активное окно
4. В терминале видны логи:

```
🔴 Запись (RECORDING_HOLD)...
🟡 Транскрибирую (2.7s аудио)...
⏱  Whisper: 0.5s
📝 Результат: текст из речи
📋 Скопировано в буфер
✅ Ctrl+V отправлен
```

---

## Автозапуск при старте Windows (опционально)

### Вариант A: Ярлык в автозагрузке

```powershell
# Создать VBS-скрипт для запуска без окна консоли
@"
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "pythonw C:\VoiceInput\voice-app.py", 0, False
"@ | Out-File -FilePath "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\VoiceInput.vbs" -Encoding ASCII
```

### Вариант B: Через Task Scheduler

```powershell
schtasks /create /tn "VoiceInput" /tr "pythonw C:\VoiceInput\voice-app.py" /sc onlogon /rl highest
```

---

## Отличия от macOS версии

| Аспект | macOS | Windows |
|--------|-------|---------|
| Системный трей | rumps (menu bar) | pystray (system tray) |
| Горячая клавиша | Ctrl+Option | Ctrl+Alt |
| Буфер обмена | pbcopy | pyperclip |
| Вставка текста | CGEvent (Cmd+V) | pynput (Ctrl+V) |
| Иконки | Emoji в тексте | Цветные круги PIL |
| Accessibility | Нужно добавлять в настройках | Не требуется |
| whisper-cli путь | /opt/homebrew/bin/whisper-cli | C:\whisper-cpp\whisper-cli.exe |

---

## Быстрая установка одной командой

Для Claude Code — выполни всё сразу:

```powershell
# 1. Python зависимости
pip install pystray Pillow pynput sounddevice numpy pyperclip

# 2. Папка whisper
mkdir C:\whisper-cpp\models -Force

# 3. Скачать whisper-cli (проверь актуальную версию на GitHub releases!)
# https://github.com/ggerganov/whisper.cpp/releases
# Скачай whisper-*-bin-x64.zip, распакуй в C:\whisper-cpp\

# 4. Скачать модель (466MB)
curl -L "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin" -o C:\whisper-cpp\models\ggml-small.bin

# 5. Создать папку приложения
mkdir C:\VoiceInput -Force

# 6. Создать voice-app.py (код выше)
# Claude Code: используй Write tool для создания C:\VoiceInput\voice-app.py

# 7. Запуск
cd C:\VoiceInput
python voice-app.py
```

---

## Troubleshooting

| Проблема | Решение |
|----------|---------|
| whisper-cli не найден | Проверь путь `C:\whisper-cpp\whisper-cli.exe`. Скачай с GitHub releases |
| Модель не найдена | Скачай: `curl -L "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin" -o C:\whisper-cpp\models\ggml-small.bin` |
| pip install ошибка | Убедись что Python добавлен в PATH: `python --version` |
| Нет звука / пустой результат | Проверь микрофон: `python -c "import sounddevice; print(sounddevice.query_devices(kind='input'))"` |
| Жёлтый висит долго | Используй small модель вместо large-v3 |
| sounddevice ошибка | Установи Visual C++ Redistributable: https://aka.ms/vs/17/release/vc_redist.x64.exe |
| Иконка не появляется в трее | Нажми стрелку ↑ рядом с часами — иконка может быть скрыта |
| Ctrl+Alt конфликтует | Измени горячую клавишу в коде: замени `Key.alt_l`/`Key.alt_r` на другую клавишу |
| NVIDIA GPU ускорение | Скачай версию whisper-cpp с cuBLAS вместо обычной |

---

## Структура файлов

```
C:\whisper-cpp\
  ├── whisper-cli.exe       # Бинарник whisper
  ├── ggml.dll              # Библиотека (из архива)
  └── models\
      └── ggml-small.bin    # Модель (466MB)

C:\VoiceInput\
  └── voice-app.py          # Приложение
```
