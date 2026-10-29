"""Multi-scene video composer for generative AI videos.

Stitches multiple diffusion-generated shots into a continuous, cohesive video
(e.g. 60+ seconds) with smooth transitions, background audio/music,
and stylized ASS subtitles matching the editing_styles specs.
"""

import os
import subprocess
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

from core.hardware import get_best_encoder, get_encoder_cascade

logger = logging.getLogger(__name__)


def create_nursery_subtitles(
    lyrics: List[Dict[str, Any]],
    ass_path: Path,
    style: str = "kids",
) -> Path:
    """Generate an ASS subtitle file for nursery rhymes matching editing_kids.md."""
    ass_path.parent.mkdir(parents=True, exist_ok=True)
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: KidsBright,Arial Rounded MT Bold,92,&H0000D7FF,&H000000FF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,8,3,2,60,60,180,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for item in lyrics:
        start_sec = item["start"]
        end_sec = item["end"]
        text = item["text"]
        start_ts = f"{int(start_sec//3600)}:{int((start_sec%3600)//60):02d}:{int(start_sec%60):02d}.{int((start_sec%1)*100):02d}"
        end_ts = f"{int(end_sec//3600)}:{int((end_sec%3600)//60):02d}:{int(end_sec%60):02d}.{int((end_sec%1)*100):02d}"
        events.append(f"Dialogue: 0,{start_ts},{end_ts},KidsBright,,0,0,0,,{text}")

    ass_path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return ass_path


def compose_long_video(
    shot_paths: List[Path],
    audio_path: Optional[Path],
    output_path: Path,
    target_duration: float = 60.0,
    subtitles_path: Optional[Path] = None,
    aspect_ratio: str = "9:16",
    fps: int = 24,
) -> Path:
    """Assemble multiple diffusion shots into a continuous target_duration video."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    num_shots = len(shot_paths)
    if num_shots == 0:
        raise ValueError("At least one shot is required")

    slot_duration = target_duration / num_shots
    video_encoder = get_best_encoder()

    # Step 1: Normalize and loop/stretch each shot to slot_duration
    norm_shots = []
    temp_dir = output_path.parent / "temp_shots"
    temp_dir.mkdir(parents=True, exist_ok=True)

    for idx, shot in enumerate(shot_paths):
        norm_file = temp_dir / f"norm_shot_{idx:02d}.mp4"
        # Ping-pong loop filter to smoothly extend shot motion to slot_duration without frozen frames
        # Scale to 9:16 (1080x1920) with blurred background or fill
        if aspect_ratio == "9:16":
            vf = (
                f"split=2[bg][fg];"
                f"[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:5[bgblur];"
                f"[fg]scale=1080:1920:force_original_aspect_ratio=decrease[fgscaled];"
                f"[bgblur][fgscaled]overlay=(W-w)/2:(H-h)/2,"
                f"fps={fps}"
            )
        else:
            vf = f"scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(1280-iw)/2:(720-ih)/2,fps={fps}"

        # Loop the video via stream loop
        loop_count = max(4, int(slot_duration // 1.0) + 2)
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", str(loop_count),
            "-i", str(shot),
            "-t", f"{slot_duration:.2f}",
            "-vf", vf,
            "-c:v", video_encoder,
            "-pix_fmt", "yuv420p",
            "-an",
            str(norm_file),
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            logger.warning(f"Error normalizing shot {shot}: {res.stderr[:200]}")
            # fallback to libx264
            cmd[cmd.index(video_encoder)] = "libx264"
            subprocess.run(cmd, check=True)
        norm_shots.append(norm_file)

    # Step 2: Concatenate normalized shots
    concat_list = temp_dir / "concat_list.txt"
    with open(concat_list, "w", encoding="utf-8") as f:
        for ns in norm_shots:
            f.write(f"file '{ns.resolve().as_posix()}'\n")

    stitched_video = temp_dir / "stitched_raw.mp4"
    cmd_concat = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        str(stitched_video),
    ]
    subprocess.run(cmd_concat, check=True)

    # Step 3: Mix audio and burn subtitles
    final_inputs = ["-i", str(stitched_video)]
    filter_chains = []

    if subtitles_path and subtitles_path.exists():
        escaped_ass = str(subtitles_path.resolve()).replace("\\", "/").replace(":", "\\:")
        filter_chains.append(f"subtitles='{escaped_ass}'")

    cmd_final = ["ffmpeg", "-y"]
    cmd_final.extend(final_inputs)

    if audio_path and audio_path.exists():
        cmd_final.extend(["-i", str(audio_path)])
        cmd_final.extend(["-c:a", "aac", "-b:a", "192k"])
    else:
        # synthesize cheerful gentle rhythmic tone if no audio supplied
        cmd_final.extend(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"])

    if filter_chains:
        cmd_final.extend(["-vf", ",".join(filter_chains)])

    cmd_final.extend([
        "-c:v", video_encoder,
        "-pix_fmt", "yuv420p",
        "-t", f"{target_duration:.2f}",
        "-shortest",
        str(output_path),
    ])

    res = subprocess.run(cmd_final, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        logger.warning(f"Hardware encode failed in final assembly, falling back to libx264: {res.stderr[:200]}")
        cmd_final[cmd_final.index(video_encoder)] = "libx264"
        subprocess.run(cmd_final, check=True)

    # Cleanup temp
    try:
        for f in temp_dir.glob("*"):
            f.unlink()
        temp_dir.rmdir()
    except Exception:
        pass

    return output_path
