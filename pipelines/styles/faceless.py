"""Faceless Explainer & AI B-Roll Generative Style (ComfyUI).

Original Spec: editing_styles/editing_faceless.md (and plan_muapi_broll.md)
Evolution: Automatically synthesizes high-density, photorealistic 9:16 documentary
B-roll (replacing stock video subscriptions) via ComfyUI with cinematic camera/lens
specifications (Full-frame cine, 35mm prime, soft diffused lighting).
"""

from typing import Dict, Any
from pipelines.generative.comfy_client import ComfyClient


class FacelessComfyStyle:
    name = "faceless"
    spec_file = "editing_styles/editing_faceless.md"

    # Higgsfield-style cinematic taxonomy port
    CINEMATIC_TAGS = (
        "shot on full-frame digital cinema camera, 35mm prime lens at f/2.8, natural depth of field, "
        "documentary b-roll footage, cinematic lighting, ultra-detailed, photorealistic, 8k resolution, award-winning"
    )

    NEGATIVE_PROMPT = (
        "cartoon, anime, 3d render, CGI, drawing, low quality, artifacting, flickering, watermark, "
        "amateur footage, ugly, distorted, oversaturated"
    )

    def __init__(self, client: ComfyClient):
        self.client = client

    def build_prompt(self, base_prompt: str) -> str:
        return f"{base_prompt.strip('. ')}, {self.CINEMATIC_TAGS}"

    def generate(
        self,
        prompt: str,
        seed: int = 42,
        steps: int = 20,
        cfg: float = 5.5,
        width: int = 704,
        height: int = 1280,  # Native vertical 9:16 for B-roll shorts
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
        workflow["10"]["inputs"]["filename_prefix"] = "video/faceless_broll"
        return workflow

