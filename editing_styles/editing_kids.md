# Editing Spec: Kids / Baby Rhymes (Bright & Playful)

## Iteration & Feedback Log
- **v1.0 (Initial):** Big rounded colorful bottom text synced to the music, slow pacing, full fit to the screen musical phrases.
- *Agent Directive:* Update this section whenever parameters are tuned during agent discussions.

## 1. Style Definition
Bright, friendly, high-contrast format for nursery rhymes, kids' songs, and toddler content. Designed to hold very young viewers' attention with large, colorful, easy-to-read bottom of the screen text synced to the music.

## 2. Visual & Audio Rules
- **Aspect Ratio:** 9:16 (1080x1920)
- **Pacing:** Slow and gentle. NO jump cuts. Let each musical phrase play out fully. Never cut mid-line or mid-word.
- **Captions:**
  - Max words per frame: 3-4 words, Bottom-screen.
  - Font: `Arial Rounded MT Bold` or `Comic Sans MS` (rounded, friendly).
  - Size: Very large (88-100pt) so toddlers can follow along.
  - Primary Color: `#FFFFFF` (White) with a thick, bright outline.
  - Outline / Accent: bright playful colors - sunny yellow `#FFD700`, hot pink `#FF69B4`, or sky blue `#00BFFF`.
  - Optional: cycle the caption color per line (rainbow karaoke effect).
- **Motion:** Optional gentle bounce/pulse on captions (scale 1.0 -> 1.05 on each new line). Keep background video bright and colorful.
- **Audio:** Keep original music/rhyme audio clean and front-and-center. No ducking, no SFX that could startle.

## 3. Targeted EDL JSON Output Schema
```json
{
  "style": "kids_bright",
  "pacing": {
    "jump_cuts": false,
    "caption_pulse": true
  },
  "typography": {
    "font_family": "Arial Rounded MT Bold",
    "font_size": 92,
    "primary_color_hex": "#FFFFFF",
    "outline_colors_hex": ["#FFD700", "#FF69B4", "#00BFFF"],
    "stroke_width": 8
  },
  "caption_rules": {
    "max_words_per_frame": 3,
    "never_cut_mid_line": true
  }
}
```
