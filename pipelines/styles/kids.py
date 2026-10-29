"""Kids / Baby Rhymes Generative Style (ComfyUI).

Original Spec: editing_styles/editing_kids.md
Evolution: Translates toddler song & rhyme prompts into full 3D animated scenes
using WAN 2.2 diffusion in ComfyUI with bright candy colors, gentle camera motion,
and bouncy friendly characters.
"""

from typing import Dict, Any
from pipelines.generative.comfy_client import ComfyClient


class KidsComfyStyle:
    name = "kids"
    spec_file = "editing_styles/editing_kids.md"

    POSITIVE_SUFFIX = (
        "3D animated Pixar-style nursery rhyme video, ultra detailed, high quality animation, "
        "vibrant candy colors, warm golden lighting, smooth gentle camera motion, "
        "adorable chubby characters with big sparkling eyes, joyful playful atmosphere"
    )

    NEGATIVE_PROMPT = (
        "blurry, low quality, distorted, deformed, extra limbs, watermark, text, subtitles, "
        "flickering, static, dark, scary, horror, photorealistic, gloomy"
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
        cfg: float = 5.0,
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
        # Name the output appropriately
        workflow["10"]["inputs"]["filename_prefix"] = "video/kids_rhymes"
        return workflow

