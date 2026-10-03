# Master Editing Router & Style Selection Matrix

## System Role
This file is the primary router for the video editing pipeline. When processing a video, evaluate its category and load the designated style spec.

## Category-to-Style Mapping Rules
- IF category == "Business", "Finance", "Productivity", "Single Speaker Advice", "gaming", "high_views", "memes_funny":
  -> Load `editing_styles/editing_hormozi.md`
- IF category == "Podcast", "Interview", "Debate", "Multi-Speaker", "podcasts":
  -> Load `editing_styles/editing_podcast.md`
- IF category == "Science", "Tech Explainer", "Case Study", "Docu-Style", "tech_news", "war_geopolitical":
  -> Load `editing_styles/editing_faceless.md`
- IF category == "Streamer Highlight", "Gaming", "Long Monologue without Visuals":
  -> Load `editing_styles/editing_gameplay.md`
- IF category == "B2B", "Webinar", "Corporate", "SaaS Showcase", "baby_rhymes":
  -> Load `editing_styles/editing_corporate.md`

## Pipeline Execution Flow
1. `trigger_engine.py` identifies source video URL.
2. Whisper generates transcript with word-level timestamps.
3. Match content niche to a category in this matrix.
4. Load the designated `editing_<style>.md` spec file.
5. Pass transcript + style spec to the LLM to output the final Edit Decision List (EDL) JSON.
6. Python/FFmpeg renders the clip deterministically from the EDL.
