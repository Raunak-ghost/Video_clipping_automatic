"""Audio Transcription module using Whisper."""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class VideoTranscriber:
    """Manages audio transcription with Whisper and per-session caching."""

    def __init__(self, model_name: str = "base"):
        self.model_name = model_name
        self._model = None
        self._cache: Dict[str, Any] = {}

    def transcribe(self, video_path: str) -> dict:
        """Transcribe video audio to timestamped segments."""
        if video_path in self._cache:
            return self._cache[video_path]

        import whisper
        if self._model is None:
            logger.info(f"Loading Whisper model: {self.model_name}")
            self._model = whisper.load_model(self.model_name)

        result = self._model.transcribe(video_path, word_timestamps=True)
        if not isinstance(result, dict):
            result = {}
        self._cache[video_path] = result
        return result
