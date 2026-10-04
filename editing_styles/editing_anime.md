# Editing Spec: Anime Recap

## Iteration & Feedback Log
- **v1.0 (Initial):** Full-screen anime footage + bold white bottom captions, fast recap narration.
- *Agent Directive:* Update this section whenever parameters are tuned during agent discussions.

## 1. Style Definition
Fast-paced anime/episode recap format (e.g., Alucard Recap). Full-screen anime footage plays while a narrator summarizes the story. Bold white captions sit at the BOTTOM of the screen, synced to the narration. Designed for high retention through continuous story momentum.

## 2. Visual & Audio Rules
- **Aspect Ratio:** 9:16 (1080x1920)
- **Layout:** Full-screen anime/footage fills the entire canvas (no split, no blur bars). Crop to fill 9:16.
- **Pacing:** Fast. Continuous forward story momentum. Cut any slow establishing shots.
- **Captions:**
  - Position: BOTTOM-third of screen (bottom-center).
  - Max words per frame: 3-5 words.
  - Font: Bold sans-serif (`Arial Bold` / `Montserrat Bold`).
  - Primary Color: `#FFFFFF` (White) with a strong black outline for readability over bright anime scenes.
  - Size: Large (70-80pt).
- **Audio:** Clear, fast AI narration/voiceover summarizing the plot. Original anime audio is replaced or ducked low under the narration.

## 3. Targeted EDL JSON Output Schema
```json
{
  "style": "anime_recap",
  "layout": "fullscreen_fill",
  "typography": {
    "font_family": "Arial Bold",
    "font_size": 76,
    "primary_color_hex": "#FFFFFF",
    "outline_color_hex": "#000000",
    "stroke_width": 6,
    "position": "bottom_center"
  },
  "caption_rules": {
    "max_words_per_frame": 4
  },
  "audio": {
    "narration": "ai_voiceover_recap",
    "original_audio_duck_db": -18
  }
}
```
