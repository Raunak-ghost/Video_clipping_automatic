"""ComfyUI Generative Style Registry.

Maps editing style names to their executable ComfyUI workflow generators,
while keeping the original markdown files in `editing_styles/` intact as the
ground-truth creative specification.
"""

from typing import Dict, Type
from pipelines.generative.comfy_client import ComfyClient
from .kids import KidsComfyStyle
from .anime import AnimeComfyStyle
from .faceless import FacelessComfyStyle
from .movie import MovieComfyStyle
from .hormozi import HormoziComfyStyle

STYLE_REGISTRY: Dict[str, Type] = {
    "kids": KidsComfyStyle,
    "baby_rhymes": KidsComfyStyle,
    "anime": AnimeComfyStyle,
    "anime_recap": AnimeComfyStyle,
    "faceless": FacelessComfyStyle,
    "broll": FacelessComfyStyle,
    "tech_news": FacelessComfyStyle,
    "war_geopolitical": FacelessComfyStyle,
    "movie": MovieComfyStyle,
    "film": MovieComfyStyle,
    "hormozi": HormoziComfyStyle,
    "gaming": HormoziComfyStyle,
    "high_views": HormoziComfyStyle,
}


def get_style(name: str, client: ComfyClient = None):
    """Resolve a style generator by name, falling back to 'kids'."""
    client = client or ComfyClient()
    cls = STYLE_REGISTRY.get(name.lower().strip(), KidsComfyStyle)
    return cls(client)


def list_styles() -> Dict[str, str]:
    """List available evolved styles and their source markdown specs."""
    return {
        "kids / baby_rhymes": "editing_styles/editing_kids.md",
        "anime / anime_recap": "editing_styles/editing_anime.md",
        "faceless / broll": "editing_styles/editing_faceless.md",
        "movie / film": "editing_styles/editing_movie.md",
        "hormozi / gaming": "editing_styles/editing_hormozi.md",
    }

