# Editing Spec: Movie Recap

## Iteration & Feedback Log
- **v1.0 (Initial):** Full-screen movie footage + bold white center captions, fast recap narration.
- *Agent Directive:* Update this section whenever parameters are tuned during agent discussions.

## 1. Style Definition
Fast-paced movie/film recap format (e.g., Movie Recap channels). Full-screen movie footage plays while a narrator summarizes the plot ("Armed robbers picked the wrong woman..."). Bold white captions sit center-screen, synced to the narration. Designed for high retention through continuous story momentum and cliffhanger pacing.

## 2. Visual & Audio Rules
- **Aspect Ratio:** 9:16 (1080x1920)
- **Layout:** Full-screen movie footage fills the entire canvas (no split, no blur bars). Crop to fill 9:16.
- **Pacing:** Very fast. Continuous plot momentum. Cut any slow/establishing shots. End on a cliffhanger for multi-part recaps.
- **Captions:**
  - Position: CENTER of screen (mid-frame), where the eye naturally rests during fast cuts.
  - Max words per frame: 3-4 words.
  - Font: Bold sans-serif (`Arial Bold` / `Montserrat Bold`).
  - Primary Color: `#FFFFFF` (White) with a strong black outline for readability over any scene.
  - Size: Large (78-84pt).
- **Audio:** Clear, fast AI narration/voiceover summarizing the plot. Original movie audio is replaced or ducked low under the narration.

## 3. Targeted EDL JSON Output Schema
```json
{
  "style": "movie_recap",
  "layout": "fullscreen_fill",
  "typography": {
    "font_family": "Arial Bold",
    "font_size": 80,
    "primary_color_hex": "#FFFFFF",
    "outline_color_hex": "#000000",
    "stroke_width": 6,
    "position": "center"
  },
  "caption_rules": {
    "max_words_per_frame": 4
  },
  "audio": {
    "narration": "ai_voiceover_recap",
    "original_audio_duck_db": -18
  },
  "pacing": {
    "end_on_cliffhanger": true
  }
}
```
