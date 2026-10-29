"""Style Engine and Render Filter Strategies.

Decouples FFmpeg filter generation and ASS caption formatting from pipeline.py.
Maps each style archetype back to its specification in `editing_styles/*.md`.
"""

from typing import Dict, Any, Tuple, Optional

# Per-style ASS caption presets (from editing_styles/*.md archetypes).
# Keys: font, size, primary colour (ASS &HBBGGRR), outline, alignment, marginV, words/event
CAPTION_PRESETS: Dict[str, Dict[str, Any]] = {
    "subtitles": dict(font="Arial", size=80, colour="&H00FFFFFF", outline=6, align=5, margin_v=60, words=3),
    # Hormozi: big uppercase kinetic words, center screen, yellow accent
    "hormozi": dict(font="Impact", size=96, colour="&H00FFFFFF", outline=7, align=5, margin_v=0, words=2),
    # Podcast: mid-divider captions, smaller, white
    "podcast": dict(font="Arial", size=56, colour="&H00FFFFFF", outline=4, align=5, margin_v=0, words=4),
    # Faceless: clean 2-line lower-third with soft box
    "faceless": dict(font="Arial", size=52, colour="&H00FFFFFF", outline=2, align=2, margin_v=140, words=8),
    # Gameplay: center captions over the 60/40 boundary
    "gameplay": dict(font="Arial", size=72, colour="&H00FFFFFF", outline=6, align=5, margin_v=0, words=3),
    # Corporate: minimal lower-third banner
    "corporate": dict(font="Arial", size=44, colour="&H00FFFFFF", outline=1, align=2, margin_v=120, words=10),
    # Kids: big rounded friendly captions, bright yellow, thick outline, bottom-screen
    "kids": dict(font="Arial Rounded MT Bold", size=92, colour="&H0000D7FF", outline=8, align=2, margin_v=140, words=4),
    # Anime recap: bold white bottom captions over full-screen footage
    "anime": dict(font="Arial", size=76, colour="&H00FFFFFF", outline=6, align=2, margin_v=150, words=4),
    # Movie recap: bold white center captions over full-screen footage
    "movie": dict(font="Arial", size=80, colour="&H00FFFFFF", outline=6, align=5, margin_v=0, words=4),
}

# Category -> render style, per editing_styles/index.md routing matrix.
CATEGORY_STYLE_MAP: Dict[str, str] = {
    "gaming": "hormozi",
    "high_views": "hormozi",
    "memes_funny": "hormozi",
    "podcasts": "podcast",
    "tech_news": "faceless",
    "war_geopolitical": "faceless",
    "sports": "gameplay",
    "ufc": "gameplay",
    "baby_rhymes": "kids",
    "anime": "anime",
    "anime_recap": "anime",
    "movie": "movie",
    "movies": "movie",
    "movie_recap": "movie",
    "film": "movie",
}


def resolve_style(category: Optional[str] = None, config: Optional[dict] = None) -> str:
    """Resolve the render style for a category.
    Priority: config edit_styles[category] > edit_styles['default'] > CATEGORY_STYLE_MAP > 'subtitles'.
    """
    edit_styles = (config or {}).get("edit_styles", {})
    if category and category in edit_styles:
        return edit_styles[category]
    if "default" in edit_styles:
        return edit_styles["default"]
    return CATEGORY_STYLE_MAP.get(category or "", "subtitles")


def build_ffmpeg_filters(
    style: str,
    ass_escaped: Optional[str] = None,
    aspect_ratio: str = "9:16",
) -> Tuple[Optional[str], Optional[str]]:
    """Build (vf, filter_complex) for the given style and subtitle sidecar."""
    vf = None
    filter_complex = None

    if style in ("subtitles", "hormozi", "kids", "anime", "movie"):
        vf = (
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920"
        )
        if ass_escaped:
            vf += f",subtitles='{ass_escaped}'"
    elif style == "podcast":
        sub_clause = f",subtitles='{ass_escaped}'" if ass_escaped else ""
        filter_complex = (
            "[0:v]split=2[top][bot];"
            "[top]crop=iw:ih/2:0:0,scale=1080:960[t];"
            "[bot]crop=iw:ih/2:0:ih/2,scale=1080:960[b];"
            f"[t][b]vstack=inputs=2[stacked];[stacked]{sub_clause.lstrip(',')}"
        )
    elif style == "faceless":
        sub_clause = f",subtitles='{ass_escaped}'" if ass_escaped else ""
        filter_complex = (
            "[0:v]split[main][bg];"
            "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=30[bg2];"
            "[main]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
            f"[bg2][fg]overlay=(W-w)/2:(H-h)/2{sub_clause}"
        )
    elif style == "gameplay":
        sub_clause = f",subtitles='{ass_escaped}'" if ass_escaped else ""
        filter_complex = (
            "[0:v]split[main][bg];"
            "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=40[bg2];"
            "[main]scale=1080:1152:force_original_aspect_ratio=decrease[fg];"
            f"[bg2][fg]overlay=(W-w)/2:0{sub_clause}"
        )
    elif style == "corporate":
        vf = (
            "scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920"
        )
        if ass_escaped:
            vf += f",subtitles='{ass_escaped}'"
    elif style == "blur":
        filter_complex = (
            "[0:v]split[main][bg];"
            "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=30[bg2];"
            "[main]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
            "[bg2][fg]overlay=(W-w)/2:(H-h)/2"
        )
    elif aspect_ratio == "9:16":
        vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    elif aspect_ratio == "16:9":
        vf = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black"

    return vf, filter_complex

