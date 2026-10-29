"""Hardware detection and video encoder abstraction.

Detects available GPU hardware (AMD Radeon / ROCm vs NVIDIA GeForce / CUDA)
and tests which FFmpeg hardware encoders are operational (e.g. h264_amf, h264_nvenc, libx264).
"""

import logging
import subprocess
import functools
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def detect_system_gpus() -> List[Dict[str, Any]]:
    """Query Windows WMI / PnP to identify physical graphics adapters."""
    gpus = []
    try:
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object Name, VideoProcessor, DriverVersion | ConvertTo-Json -Compress",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0 and res.stdout.strip():
            import json
            data = json.loads(res.stdout)
            if isinstance(data, dict):
                data = [data]
            for item in data:
                name = item.get("Name", "")
                if name:
                    gpus.append({
                        "name": name,
                        "processor": item.get("VideoProcessor", ""),
                        "driver": item.get("DriverVersion", ""),
                    })
    except Exception as e:
        logger.debug(f"GPU detection via WMI failed: {e}")

    return gpus


def test_ffmpeg_encoder(encoder_name: str, ffmpeg_path: str = "ffmpeg") -> bool:
    """Test whether a specific FFmpeg video encoder functions on this system."""
    cmd = [
        ffmpeg_path,
        "-y",
        "-v", "error",
        "-f", "lavfi",
        "-i", "testsrc=duration=0.5:size=320x240:rate=10",
        "-c:v", encoder_name,
        "-f", "null",
        "-",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return res.returncode == 0
    except Exception:
        return False


@functools.lru_cache(maxsize=1)
def get_encoder_cascade(ffmpeg_path: str = "ffmpeg", preferred_encoder: Optional[str] = None) -> List[str]:
    """Return an ordered list of verified, working FFmpeg encoders.
    
    Priority order tested:
      1. Explicit preference from config (if it passes hardware test)
      2. h264_amf (AMD Video Core Next)
      3. h264_nvenc (NVIDIA NVENC)
      4. h264_qsv (Intel Quick Sync)
      5. h264_videotoolbox (macOS)
      6. libx264 (Universal CPU fallback)
    """
    candidates = []
    if preferred_encoder:
        candidates.append(preferred_encoder)

    candidates.extend(["h264_amf", "h264_nvenc", "h264_qsv", "h264_videotoolbox", "libx264"])

    verified = []
    for enc in candidates:
        if enc in verified:
            continue
        if enc == "libx264":
            verified.append(enc)
            continue
        if test_ffmpeg_encoder(enc, ffmpeg_path=ffmpeg_path):
            logger.info(f"Hardware encoder verified operational: {enc}")
            verified.append(enc)
        else:
            logger.debug(f"Hardware encoder unavailable/failed test: {enc}")

    if "libx264" not in verified:
        verified.append("libx264")

    return verified


def get_best_encoder(ffmpeg_path: str = "ffmpeg", preferred_encoder: Optional[str] = None) -> str:
    """Return the primary working video encoder."""
    cascade = get_encoder_cascade(ffmpeg_path=ffmpeg_path, preferred_encoder=preferred_encoder)
    return cascade[0] if cascade else "libx264"


def print_hardware_summary():
    """Print diagnosed hardware and verified encoder support."""
    print("=" * 65)
    print(" HARDWARE & VIDEO ENCODER DIAGNOSTICS")
    print("=" * 65)
    gpus = detect_system_gpus()
    print("Detected Display Adapters:")
    for i, g in enumerate(gpus, 1):
        print(f"  [{i}] {g['name']} (Driver: {g.get('driver', 'unknown')})")
    print("\nFFmpeg Encoder Testing:")
    for enc in ["h264_amf", "h264_nvenc", "h264_qsv", "libx264"]:
        ok = test_ffmpeg_encoder(enc)
        status = "PASSED (Active GPU Hardware)" if ok else "FAILED / NOT SUPPORTED"
        print(f"  • {enc:<15} : {status}")
    cascade = get_encoder_cascade()
    print(f"\nActive Encoder Priority: {' -> '.join(cascade)}")
    print("=" * 65)


if __name__ == "__main__":
    print_hardware_summary()

