"""List recent uploads for each configured channel and pick one clip candidate.

Chooses the most recent video longer than 3 minutes from the 5 most recent
uploads.
"""
import json
from typing import Any, Dict

from yt_dlp import YoutubeDL

CHANNELS = {
    "mkbhd": "UCBJycsmduvYEL83R_U4JriQ",
    "huberman": "UC2D2CMWXMOVWx7giW1n3LIg",
    "diary_of_a_ceo": "UCGq-a57w-aPwyi3pW7XLiHw",
}


def list_videos(channel_id: str, limit: int = 5):
    url = f"https://www.youtube.com/channel/{channel_id}/videos"
    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "playlistend": limit,
        "skip_download": True,
    }
    with YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
        info = ydl.extract_info(url, download=False)
    entries = [e for e in (info.get("entries") or []) if e and e.get("id")]
    entries = [e for e in entries if e.get("live_status") not in ("is_upcoming", "is_live")]
    entries = entries[:limit]

    # Flat entries usually carry duration; fall back to per-video metadata if not.
    if entries and all(e.get("duration") is None for e in entries):
        filled = []
        meta_opts: Dict[str, Any] = {"quiet": True, "no_warnings": True, "skip_download": True}
        with YoutubeDL(meta_opts) as ydl:  # type: ignore[arg-type]
            for e in entries:
                try:
                    vi = ydl.extract_info(
                        f"https://www.youtube.com/watch?v={e['id']}", download=False
                    )
                    filled.append(
                        {"id": vi.get("id"), "title": vi.get("title"), "duration": vi.get("duration")}
                    )
                    continue
                except Exception as ex:  # noqa: BLE001
                    print(f"  ! metadata fetch failed for {e['id']}: {ex}")
                filled.append({"id": e.get("id"), "title": e.get("title"), "duration": e.get("duration")})
        entries = filled
    return entries


def pick(entries):
    # entries are newest-first; pick the most recent video longer than 3 minutes
    qualifying = [e for e in entries if e.get("duration") and e["duration"] > 180]
    if not qualifying:
        return None
    return qualifying[0]


def main():
    report = {}
    for name, channel_id in CHANNELS.items():
        print(f"\n=== {name} ({channel_id}) ===")
        try:
            entries = list_videos(channel_id)
        except Exception as ex:  # noqa: BLE001
            print(f"  ! failed to list channel: {ex}")
            report[name] = {"error": str(ex)}
            continue
        for e in entries:
            dur = e.get("duration")
            print(f"  {e.get('id')}  {f'{dur}s' if dur else '?':>9}  {e.get('title')}")
        chosen = pick(entries)
        if chosen:
            chosen_id = chosen.get("id")
            chosen_title = chosen.get("title")
            chosen_duration = chosen.get("duration")
            print(f"  -> chosen: {chosen_id} ({chosen_duration}s) {chosen_title}")
            report[name] = {
                "video_id": chosen_id,
                "title": chosen_title,
                "duration": chosen_duration,
                "url": f"https://www.youtube.com/watch?v={chosen_id}",
            }
        else:
            print("  -> no video longer than 3min in top 5")
            report[name] = {"error": "no qualifying video"}
    print("\n=== RESULT JSON ===")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
