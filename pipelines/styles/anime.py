"""Anime Recap & Cinematic Anime Generative Style (ComfyUI).

Original Spec: editing_styles/editing_anime.md
Evolution: Produces high-retention cinematic anime footage using WAN 2.2 diffusion
in ComfyUI with vibrant cel-shading, Ufotable/Makoto Shinkai aesthetic, dynamic camera
angles, and bold composition.
"""

from typing import Dict, Any
from pipelines.generative.comfy_client import ComfyClient


class AnimeComfyStyle:
    name = "anime"
    spec_file = "editing_styles/editing_anime.md"

    POSITIVE_SUFFIX = (
        "masterpiece anime scene, studio ufotable and makoto shinkai style, "
        "vibrant cel shading, cinematic anime lighting, dramatic composition, dynamic motion, "
        "intricate lineart, expressive eyes, volumetric light rays, 8k resolution anime aesthetic"
    )

    NEGATIVE_PROMPT = (
        "photorealistic, live action, western 3D cartoon, claymation, blurry, low resolution, "
        "deformed face, missing fingers, extra limbs, ugly, watermark, text"
    )

    def __init__(self, client: ComfyClient):
        self.client = client

    def build_prompt(self, base_prompt: str) -> str:
        return f"{base_prompt.strip('. ')}. {self.POSITIVE_SUFFIX}"

    def generate(
        self,
        prompt: str,
        seed: int = 42,
        steps: int = 20,
        cfg: float = 6.0,
        width: int = 1280,
        height: int = 704,
        frames: int = 121,
        fps: int = 24,
    ) -> Dict[str, Any]:
        positive = self.build_prompt(prompt)
        workflow = self.client.build_wan22_workflow(
            positive=positive,
            negative=self.NEGATIVE_PROMPT,
            seed=seed,
            steps=steps,
            cfg=cfg,
            width=width,
            height=height,
            frames=frames,
            fps=fps,
        )
        workflow["10"]["inputs"]["filename_prefix"] = "video/anime_recap"
        return workflow

