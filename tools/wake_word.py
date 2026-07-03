#!/usr/bin/env python3
"""Wake Word Detection — Always-listening mode for "Simplicio".

Uses Porcupine (Picovoice) for local, offline wake word detection.
No cloud, no API key needed. ~2MB model, runs in background.

Install:
    pip install pvporcupine

Usage:
    from tools.wake_word import WakeWordDetector

    detector = WakeWordDetector(callback=lambda: print("Simplicio ativado!"))
    detector.start()  # blocks until wake word detected
"""

import logging
import os
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

WAKE_WORD = "Simplicio"
WAKE_SENSITIVITY = 0.7  # 0.0–1.0, lower = more sensitive


def _pvporcupine_available() -> bool:
    """Check if pvporcupine can be imported."""
    try:
        import pvporcupine  # noqa: F401
        return True
    except ImportError:
        return False


def _audio_available() -> bool:
    """Check if sounddevice can be imported."""
    try:
        import sounddevice as sd  # noqa: F401
        return True
    except (ImportError, OSError):
        return False


class WakeWordDetector:
    """Always-listening wake word detector for "Simplicio".

    Runs Porcupine in a background thread, calling `callback` on detection.

    Example:
        def on_wake():
            print("Simplicio ouvindo...")
            # Start recording, transcribe, reply

        detector = WakeWordDetector(callback=on_wake)
        detector.start()          # blocks until Ctrl+C
        # or
        detector.start_async()    # non-blocking
    """

    def __init__(
        self,
        callback: Callable[[], None],
        sensitivity: float = WAKE_SENSITIVITY,
        keyword: str = WAKE_WORD,
    ):
        self.callback = callback
        self.sensitivity = sensitivity
        self.keyword = keyword
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def is_available(self) -> bool:
        """Check all dependencies before starting."""
        if not _pvporcupine_available():
            logger.error("pvporcupine not installed. Run: pip install pvporcupine")
            return False
        if not _audio_available():
            logger.error("sounddevice not installed. Run: pip install sounddevice numpy")
            return False
        return True

    def install_hint(self) -> str:
        """Return install command for missing dependencies."""
        missing = []
        if not _pvporcupine_available():
            missing.append("pvporcupine")
        if not _audio_available():
            missing.append("sounddevice numpy")
        if missing:
            return f"pip install {' '.join(missing)}"
        return "all dependencies installed"

    def start(self) -> None:
        """Start wake word detection (blocking). Ctrl+C to stop."""
        if not self.is_available():
            hint = self.install_hint()
            print(f"❌ Wake word não disponível. Instale: {hint}")
            return

        import pvporcupine
        import sounddevice as sd
        import numpy as np

        try:
            porcupine = pvporcupine.create(
                keywords=[self.keyword.lower()],
                sensitivities=[self.sensitivity],
            )
        except pvporcupine.PorcupineError as e:
            # If built-in keyword not found, try custom model path
            logger.warning(f"Built-in keyword '{self.keyword}' not found: {e}")
            model_path = os.environ.get(
                "SIMPLICIO_WAKE_MODEL",
                os.path.expanduser("~/.simplicio/models/wake-word.ppn"),
            )
            if os.path.exists(model_path):
                porcupine = pvporcupine.create(
                    keyword_paths=[model_path],
                    sensitivities=[self.sensitivity],
                )
            else:
                print(f"❌ Wake word model não encontrado: {model_path}")
                print(f"   Crie seu modelo customizado em: https://console.picovoice.ai/")
                return

        self._running = True
        sample_rate = porcupine.sample_rate
        frame_length = porcupine.frame_length

        print(f"🎤 Aguardando '{self.keyword}'... (Ctrl+C para parar)")

        def audio_callback(indata, frames, time_info, status):
            if not self._running:
                raise sd.CallbackStop
            if status:
                logger.warning(f"Audio status: {status}")
            pcm = np.frombuffer(indata, dtype=np.int16)
            keyword_index = porcupine.process(pcm.flatten().tolist())
            if keyword_index >= 0:
                logger.info(f"Wake word '{self.keyword}' detected!")
                # Run callback in a new thread to not block audio
                threading.Thread(target=self.callback, daemon=True).start()

        try:
            with sd.InputStream(
                samplerate=sample_rate,
                blocksize=frame_length,
                dtype="int16",
                channels=1,
                callback=audio_callback,
            ):
                while self._running:
                    sd.sleep(100)
        except KeyboardInterrupt:
            print(f"\n🛑 Wake word desativado.")
        finally:
            self._running = False
            porcupine.delete()

    def start_async(self) -> None:
        """Start wake word detection in a background thread (non-blocking)."""
        self._thread = threading.Thread(target=self.start, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop wake word detection."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)


# ── Convenience function for CLI integration ────────────────────────────────

def create_wake_detector(on_wake: Callable[[], None]) -> WakeWordDetector:
    """Create a pre-configured wake word detector for 'Simplicio'."""
    return WakeWordDetector(
        callback=on_wake,
        sensitivity=WAKE_SENSITIVITY,
        keyword=WAKE_WORD,
    )
