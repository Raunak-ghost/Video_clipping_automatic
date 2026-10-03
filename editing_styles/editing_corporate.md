# Editing Spec: Minimalist Corporate Clean

## Iteration & Feedback Log
- **v1.0 (Initial):** Clean lower-thirds, subtle transitions, crisp 1080p output.
- **v1.1 (Target):** Add custom brand color hex variable to JSON output.

## 1. Style Definition
Refined format tailored for B2B executives, SaaS software demos, tech webinars, and corporate announcements.

## 2. Visual & Audio Rules
- **Aspect Ratio:** 9:16 (1080x1920) or 1:1 (1080x1080) for LinkedIn/X.
- **Pacing:** Standard natural cadence. Zero aggressive jump cuts.
- **Captions:**
  - Style: Elegant, minimal lower-third banner.
  - Font: `Inter` or `Roboto Medium`.
  - Color: Dark gray/navy text backdrop (`#1A1D20`) with white text.
- **Graphics:** Subtle side-slide corporate transitions and polished lower-third name tags.

## 3. Targeted EDL JSON Output Schema
```json
{
  "style": "corporate_clean",
  "typography": {
    "font_family": "Inter",
    "font_size": 36,
    "background_box_color": "#1A1D20",
    "text_color": "#FFFFFF"
  },
  "transitions": "fade_cross_dissolve_200ms"
}
```
