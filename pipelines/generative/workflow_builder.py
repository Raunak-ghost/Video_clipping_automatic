"""WAN 2.2 TI2V-5B Workflow Graph Generator for ComfyUI."""

from typing import Dict, Any


def build_wan22_workflow(
    positive: str,
    negative: str,
    seed: int = 42,
    steps: int = 20,
    cfg: float = 5.0,
    width: int = 1280,
    height: int = 704,
    frames: int = 121,
    fps: int = 24,
    filename_prefix: str = "video/generated_clip",
) -> Dict[str, Any]:
    """Construct WAN 2.2 graph using the local safetensors models."""
    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "wan2.2_ti2v_5B_fp16.safetensors",
                "weight_dtype": "default",
            },
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
                "type": "wan",
                "device": "default",
            },
        },
        "3": {
            "class_type": "VAELoader",
            "inputs": {"vae_name": "wan2.2_vae.safetensors"},
        },
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": positive},
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"clip": ["2", 0], "text": negative},
        },
        "6": {
            "class_type": "EmptyHunyuanLatentVideo",
            "inputs": {
                "width": width,
                "height": height,
                "length": frames,
                "batch_size": 1,
            },
        },
        "7": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "uni_pc",
                "scheduler": "simple",
                "denoise": 1.0,
                "model": ["1", 0],
                "positive": ["4", 0],
                "negative": ["5", 0],
                "latent_image": ["6", 0],
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["7", 0], "vae": ["3", 0]},
        },
        "9": {
            "class_type": "CreateVideo",
            "inputs": {"images": ["8", 0], "fps": fps, "codec": "auto"},
        },
        "10": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["9", 0],
                "filename_prefix": filename_prefix,
                "format": "auto",
            },
        },
    }
