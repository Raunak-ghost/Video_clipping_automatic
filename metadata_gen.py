"""Generate paste-ready YouTube upload metadata (title + description + hashtags)
for each clip, saved as a .txt in upload_metadata/<category>/<channel>/<date>/.

The .txt is formatted so you can copy each field straight into YouTube Studio:
- Title box  -> the TITLE line (hashtags here show as part of the title)
- Description box -> the DESCRIPTION block (hashtags here become clickable links)

Hashtag format rules (per YouTube): start with #, no spaces or special chars.
"""
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("metadata_gen")

METADATA_ROOT = Path("upload_metadata")

# Base hashtags every Shorts clip gets
BASE_TAGS = ["#shorts", "#viral", "#clip"]

# Per-category hashtag sets (no spaces, no special chars after #)
CATEGORY_TAGS = {
    "gaming": ["#gaming", "#mrbeast", "#challenge", "#gamingclips"],
    "high_views": ["#viral", "#trending", "#mustwatch"],
    "memes_funny": ["#memes", "#funny", "#comedy", "#lol"],
    "podcasts": ["#podcast", "#podcastclips", "#interview", "#motivation"],
    "tech_news": ["#tech", "#technews", "#review", "#gadgets"],
    "war_geopolitical": ["#news", "#geopolitics", "#worldnews"],
    "sports": ["#sports", "#espn", "#highlights"],
    "ufc": ["#ufc", "#mma", "#fight", "#knockout"],
    "baby_rhymes": ["#nurseryrhymes", "#kidssongs", "#cocomelon", "#kids", "#toddler"],
}

# Per-channel extra tag (channel name -> hashtag, no spaces)
def _channel_tag(channel: Optional[str]) -> Optional[str]:
    if not channel:
        return None
    tag = re.sub(r"[^A-Za-z0-9]", "", channel)
    return f"#{tag.lower()}" if tag else None


def build_hashtags(category: Optional[str], channel: Optional[str]) -> str:
    """Return a space-separated hashtag string for the category + channel."""
    tags = list(BASE_TAGS)
    tags += CATEGORY_TAGS.get(category or "", [])
    ctag = _channel_tag(channel)
    if ctag:
        tags.append(ctag)
    # de-dup, preserve order
    seen = set()
    out = []
    for t in tags:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return " ".join(out)


def generate_metadata(
    title: str,
    category: Optional[str] = None,
    channel: Optional[str] = None,
    source_url: Optional[str] = None,
) -> dict:
    """Build the title/description/hashtags for a clip."""
    hashtags = build_hashtags(category, channel)

    # Title: clip title + a couple of hashtags (these show as part of the title)
    title_tags = " ".join(hashtags.split()[:3])  # first few tags in title
    full_title = f"{title} {title_tags}".strip()
    if len(full_title) > 100:
        full_title = title[:100]  # YouTube title limit

    # Description: short line + source credit + full hashtag block (clickable links)
    desc_lines = [
        f"{title}",
        "",
    ]
    if channel:
        desc_lines.append(f"From: {channel}")
    if source_url:
        desc_lines.append(f"Source: {source_url}")
    desc_lines += [
        "",
        hashtags,
        "",
        "#shorts #feed",
    ]
    description = "\n".join(desc_lines)

    return {"title": full_title, "description": description, "hashtags": hashtags}


def write_metadata_txt(
    title: str,
    category: Optional[str],
    channel: Optional[str],
    source_url: Optional[str],
    clip_filename: str,
) -> Path:
    """Write the paste-ready .txt next to the clip's category/channel/date tree
    under upload_metadata/. Returns the txt path."""
    meta = generate_metadata(title, category, channel, source_url)

    date_str = datetime.now().strftime("%Y-%m-%d")
    safe_cat = re.sub(r"[^A-Za-z0-9 _.-]", "", category or "uncategorized").strip()
    safe_chan = re.sub(r"[^A-Za-z0-9 _.-]", "", channel or "unknown_channel").strip()
    out_dir = METADATA_ROOT / safe_cat / safe_chan / date_str
    out_dir.mkdir(parents=True, exist_ok=True)

    txt_path = out_dir / (Path(clip_filename).stem + ".txt")
    body = f"""============================================================
YOUTUBE UPLOAD METADATA - copy each field into YouTube Studio
============================================================

TITLE (paste into the Title box):
{meta['title']}

------------------------------------------------------------
DESCRIPTION (paste into the Description box):
{meta['description']}

------------------------------------------------------------
HASHTAGS ONLY (if you want to add them separately):
{meta['hashtags']}

============================================================
Notes:
- Hashtags in the TITLE appear as part of the title.
- Hashtags in the DESCRIPTION become clickable blue links.
- Format: # + word, no spaces or special characters.
============================================================
"""
    txt_path.write_text(body, encoding="utf-8")
    logger.info(f"Metadata written -> {txt_path}")
    return txt_path
