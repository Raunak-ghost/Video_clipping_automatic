"""Pipelines package for Video Production Studio."""
from .clipping import ClipperPipeline
from .generative import GenerativePipeline, ComfyClient
from .styles import get_style, list_styles, STYLE_REGISTRY
