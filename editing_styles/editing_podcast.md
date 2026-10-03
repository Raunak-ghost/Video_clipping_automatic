# Editing Spec: Podcast & Split-Screen Framing

## Iteration & Feedback Log
- **v1.0 (Initial):** Dual-stacked 9:16 frame with active speaker detection.
- **v1.1 (Target):** Auto-switch to full-screen 9:16 when a speaker monologues for >8 seconds.

## 1. Style Definition
Dual-speaker framing optimized for interviews, conversational podcasts, and debates (Diary of a CEO, Huberman Lab).

## 2. Visual & Audio Rules
- **Aspect Ratio:** 9:16 (1080x1920)
- **Layout Architecture:**
  - **Top Box (0 to 50% height):** Face-tracked crop of Speaker A.
  - **Bottom Box (50% to 100% height):** Face-tracked crop of Speaker B.
- **Active Speaker Rule:**
  - If Speaker A talks continuously for >8 seconds, smoothly zoom Top Box to fill 100% canvas until Speaker B interjects.
- **Captions:**
  - Position: Mid-screen divider line.
  - Font: `Inter Bold` or `Futura`.
  - Color Coding: Speaker A = `#FFFF00` (Yellow text), Speaker B = `#FFFFFF` (White text).

## 3. Targeted EDL JSON Output Schema
```json
{
  "style": "podcast_split_screen",
  "layout": {
    "type": "dual_stack_vertical",
    "speaker_a_crop_box": [0, 0, 1080, 960],
    "speaker_b_crop_box": [0, 960, 1080, 1920]
  },
  "speaker_colors": {
    "speaker_a_hex": "#FFFF00",
    "speaker_b_hex": "#FFFFFF"
  }
}
```
