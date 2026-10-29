"""Backward-compatibility shim for pipelines.clipping.ClipperPipeline."""
from pipelines.clipping.pipeline import ClipperPipeline as Pipeline
from pipelines.clipping import *

__all__ = ["Pipeline", "ClipperPipeline"]
