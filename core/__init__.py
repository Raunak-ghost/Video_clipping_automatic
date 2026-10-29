"""Core package for Video Production Studio."""
from .hardware import get_best_encoder, get_encoder_cascade, detect_system_gpus, test_ffmpeg_encoder
from .styles import resolve_style, build_ffmpeg_filters, CAPTION_PRESETS
