# Editing Spec: Faceless B-Roll & Visual Explainer

## Iteration & Feedback Log
- **v1.0 (Initial):** Stock B-roll overlay every 2-3 seconds over transcript voiceover.
- **v1.1 (Target):** Add animated line charts and text stat callouts on financial/scientific figures.

## 1. Style Definition
Documentary and explainer style used for science, health, business case studies, and true crime breakdowns.

## 2. Visual & Audio Rules
- **Aspect Ratio:** 9:16 (1080x1920)
- **Visual Layering:**
  - Source video is suppressed or used sparingly (20% of duration).
  - High-density B-roll overlay (Pexels, stock video, AI images) changing every 2.0 to 3.0 seconds.
  - Motion: Continuous 1.05x subtle zoom (Ken Burns effect) on static images.
- **Captions & Graphics:**
  - Subtitles: Clean 2-line lower-third with soft dark backdrop box (50% opacity).
  - Stat Callouts: Animated center cards when numbers or stats are mentioned (e.g., "$10,000/mo" or "78% Increase").
- **Audio:** Low background track ducked at -20dB underneath voiceover.

## 3. Targeted EDL JSON Output Schema
```json
{
  "style": "faceless_explainer",
  "b_roll_frequency_seconds": 2.5,
  "background_audio_duck_db": -20,
  "graphics_triggers": [
    {
      "timestamp": "00:00:12.100",
      "type": "stat_card",
      "main_text": "+140% Growth",
      "sub_text": "Q3 Revenue Surge"
    }
  ]
}
```
