"""Hormozi / Viral High-Energy Generative Style (ComfyUI).

Original Spec: editing_styles/editing_hormozi.md
Evolution: Synthesizes high-impact 3D visual metaphors, kinetic assets, and punchy
concept scenes using WAN 2.2 diffusion in ComfyUI with vivid studio contrast,
dramatic lighting, and high-retention energy.
"""

from typing import Dict, Any
from pipelines.generative.comfy_client import ComfyClient


class HormoziComfyStyle:
    name = "hormozi"
    spec_file = "editing_styles/editing_hormozi.md"

    HORMOZI_TAGS = (
        "hyper-realistic 3D visual metaphor, high energy, bold studio rim lighting, "
        "intense contrast, vibrant yellow and gold highlights, high retention visual hook, "
        "ultra-detailed, 8k resolution, cinematic commercial look"
    )

    NEGATIVE_PROMPT = (
        "dull, pale colors, boring, blurry, static, deformed, low quality, dark shadows, flat"
    )

    def __init__(self, client: ComfyClient):
        self.client = client

    def build_prompt(self, base_prompt: str) -> str:
        return f"{base_prompt.strip('. ')}, {self.HORMOZI_TAGS}"

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
        workflow["10"]["inputs"]["filename_prefix"] = "video/hormozi_hook"
        return workflow

