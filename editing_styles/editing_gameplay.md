# Editing Spec: Split Reaction / High Retention Overlay

## Iteration & Feedback Log
- **v1.0 (Initial):** Top 60% clip / Bottom 40% gameplay footage.
- **v1.1 (Target):** Auto-select background type based on mood (GTA V parkour for fast audio; kinetic sand for deep monologue).

## 1. Style Definition
Designed for streamer clips, audio monologues, or viral discussions that lack high visual movement.

## 2. Visual & Audio Rules
- **Aspect Ratio:** 9:16 (1080x1920)
- **Canvas Layout:**
  - **Top 60% (1080x1152):** Primary clip / reaction camera centered on speaker.
  - **Bottom 40% (1080x768):** High-retention stock video (GTA V parkour, Subway Surfers, satisfying craft loops).
- **Audio Rules:**
  - Mute audio on bottom footage completely.
  - Primary voiceover normalized to -1dB peak.
- **Captions:** Center-aligned kinetic captions placed over the boundary line between top and bottom clips.

## 3. Targeted EDL JSON Output Schema
```json
{
  "style": "gameplay_split_overlay",
  "layout_split_ratio": "60_40",
  "background_media_type": "gta5_parkour",
  "top_frame_crop": [0, 0, 1080, 1152],
  "bottom_frame_crop": [0, 1152, 1080, 1920]
}
```
