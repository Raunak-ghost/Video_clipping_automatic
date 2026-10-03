# Editing Spec: Hormozi Kinetic Typography

## Iteration & Feedback Log
- **v1.0 (Initial):** Basic 1-3 word captions, yellow/green highlights, 2s jump cuts.
- **v1.1 (Target):** Add sound effect cues (whoosh, pop) on keyword highlights.
- *Agent Directive:* Update this section whenever parameters are tuned during agent discussions.

## 1. Style Definition
High-energy, fast-paced educational format designed for maximum retention on single-speaker advice.

## 2. Visual & Audio Rules
- **Aspect Ratio:** 9:16 (1080x1920)
- **Cut / Zoom Frequency:** Hard jump-cut or scale shift (1.0x to 1.15x) every 1.5 to 2.2 seconds to eliminate silence.
- **Captions:**
  - Max words per frame: 1-3 words centered in the lower-third.
  - Font: `Montserrat Black` or `Impact` (Uppercase, 48pt-56pt).
  - Primary Color: `#FFFFFF` (White) with 100% black outline (4px stroke).
  - Highlight Accent: `#FFFF00` (Yellow) or `#00FF00` (Lime Green) on high-value numbers or verbs.
- **Overlays:** Insert emojis or vector pop-ups on key accent words.
- **Audio:** SFX (`whoosh.wav`, `pop.wav`) synced to highlighted words.

## 3. Targeted EDL JSON Output Schema
```json
{
  "style": "hormozi_kinetic",
  "pacing": {
    "zoom_interval_seconds": 1.8,
    "cut_silence_threshold_ms": 150
  },
  "typography": {
    "font_family": "Montserrat Black",
    "font_size": 52,
    "highlight_color_hex": "#FFFF00",
    "stroke_color_hex": "#000000"
  },
  "sfx_cues": [
    {"timestamp": "00:00:03.200", "sound": "pop.wav"},
    {"timestamp": "00:00:08.500", "sound": "whoosh.wav"}
  ]
}
```
