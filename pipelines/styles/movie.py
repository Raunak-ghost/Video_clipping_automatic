"""Movie Recap & Film Noir Generative Style (ComfyUI).

Original Spec: editing_styles/editing_movie.md
Evolution: Synthesizes Hollywood 70mm anamorphic film sequences using WAN 2.2 diffusion
with warm cinema color grading, anamorphic halation, shallow depth of field, and gritty texture.
"""

from typing import Dict, Any
from pipelines.generative.comfy_client import ComfyClient


class MovieComfyStyle:
    name = "movie"
    spec_file = "editing_styles/editing_movie.md"

    FILM_TAGS = (
        "grand format 70mm film camera, classic anamorphic lens, halation diffusion, "
        "shallow depth of field f/1.8, creamy bokeh, warm cinematic color grade, 35mm film grain, "
        "dramatic shadow contrast, cinematic lighting, movie still, masterpiece"
    )

    NEGATIVE_PROMPT = (
        "digital, video camera, cartoon, anime, flat lighting, amateur, blurry, oversaturated, "
        "low resolution, watermark, text"
    )

    def __init__(self, client: ComfyClient):
        self.client = client

    def build_prompt(self, base_prompt: str) -> str:
        return f"{base_prompt.strip('. ')}, {self.FILM_TAGS}"

    def generate(
        self,
        prompt: str,
        seed: int = 42,
        steps: int = 20,
        cfg: float = 5.5,
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
        workflow["10"]["inputs"]["filename_prefix"] = "video/movie_cinematic"
        return workflow

