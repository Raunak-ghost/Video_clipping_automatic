"""Copyright / near-duplicate checker for generated clips.

Two layers:
1. Pre-upload (local): perceptual video hash (videohash) compared against a
   reference library of known-copyrighted videos you want to avoid re-uploading
   (e.g. full episodes, movie scenes, music videos). Catches near-duplicates
   even after cropping, scaling, watermarking, or re-encoding.
2. Post-upload (YouTube): after a clip is uploaded as private, poll the
   YouTube Data API for the video's processing/claim status before publishing.

Note: YouTube's Content ID pre-check ("Checks" in Studio) is NOT available via
any public API. The only programmatic signal is post-upload status. The local
hash layer is your first line of defense.

CLI:
    python copyright_check.py fingerprint <video.mp4>          # print 64-bit hash
    python copyright_check.py add <video.mp4>                  # add to reference library
    python copyright_check.py check <clip.mp4>                 # check clip vs library
    python copyright_check.py check-all                        # check all clips/ vs library
"""
import json
import logging
import sys
from pathlib import Path
from typing import Optional

# videohash 3.0.1 uses PIL.Image.ANTIALIAS, removed in Pillow 10.
# Shim it to LANCZOS before videohash is imported.
try:
    from PIL import Image
    if not hasattr(Image, "ANTIALIAS"):
        Image.ANTIALIAS = Image.LANCZOS
except Exception:
    pass

logger = logging.getLogger("copyright_check")

REFERENCE_DB = Path("copyright_reference.json")
# Hamming distance threshold on the 64-bit hash: <= this = "too similar".
# Measured on this pipeline: identical file = 0, different videos = 21-34,
# 9:16-cropped+captioned re-render of same content = 36. A threshold of 10
# flags only true near-duplicates (same edit, minor re-encode) without
# false-positiving on transformative clips. Raise to ~15 to be more aggressive.
SIMILARITY_THRESHOLD = 10


# ------------------- local perceptual-hash layer -------------------

def fingerprint(video_path: str) -> str:
    """Return the 64-bit perceptual hash (hex) of a video."""
    from videohash import VideoHash
    return VideoHash(path=video_path).hash_hex


def _load_db() -> dict:
    if REFERENCE_DB.exists():
        return json.loads(REFERENCE_DB.read_text(encoding="utf-8"))
    return {}


def _save_db(db: dict) -> None:
    REFERENCE_DB.write_text(json.dumps(db, indent=2), encoding="utf-8")


def add_reference(video_path: str, label: Optional[str] = None) -> str:
    """Fingerprint a known-copyrighted video into the reference library."""
    h = fingerprint(video_path)
    db = _load_db()
    db[h] = {"label": label or Path(video_path).stem, "source": str(video_path)}
    _save_db(db)
    logger.info(f"Added reference: {db[h]['label']} ({h})")
    return h


def check_clip(clip_path: str, threshold: int = SIMILARITY_THRESHOLD) -> dict:
    """Check a clip against the reference library.

    Returns {"status": "clear"|"flagged", "matches": [...], "hash": ...}.
    """
    from videohash import VideoHash

    clip_hash = VideoHash(path=clip_path)
    db = _load_db()
    matches = []
    for ref_hex, meta in db.items():
        dist = clip_hash - ref_hex  # hamming distance via __sub__
        if dist <= threshold:
            matches.append({"label": meta["label"], "distance": dist, "ref_hash": ref_hex})
    return {
        "status": "flagged" if matches else "clear",
        "clip": clip_path,
        "hash": clip_hash.hash_hex,
        "matches": sorted(matches, key=lambda m: m["distance"]),
    }


# ------------------- post-upload YouTube status layer -------------------

def check_uploaded_video(video_id: str, config: dict) -> dict:
    """Poll YouTube Data API for an uploaded video's processing/claim status.

    Uses the pipeline's OAuth (youtube_token.json). Returns the video's
    status dict: uploadStatus, rejectionReason, privacyStatus, etc.
    A 'rejected' uploadStatus or a non-empty rejectionReason means a
    copyright/policy block.
    """
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token_path = Path("youtube_token.json")
    if not token_path.exists():
        return {"error": "youtube_token.json not found - complete OAuth first"}

    scopes = ["https://www.googleapis.com/auth/youtube.upload",
              "https://www.googleapis.com/auth/youtube.readonly"]
    creds = Credentials.from_authorized_user_file(str(token_path), scopes)
    youtube = build("youtube", "v3", credentials=creds)

    resp = youtube.videos().list(part="status,processingDetails", id=video_id).execute()
    items = resp.get("items") or []
    if not items:
        return {"error": f"video {video_id} not found on the authenticated channel"}

    status = items[0].get("status", {})
    processing = items[0].get("processingDetails", {})
    upload_status = status.get("uploadStatus")
    rejection = status.get("rejectionReason")
    return {
        "video_id": video_id,
        "upload_status": upload_status,          # uploaded | processed | rejected | failed | deleted
        "rejection_reason": rejection,           # e.g. 'copyright' if blocked
        "processing_status": processing.get("processingStatus"),
        "blocked": upload_status in ("rejected", "failed") or bool(rejection),
        "copyright_blocked": rejection == "copyright",
    }


# ------------------- CLI -------------------

def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]

    if cmd == "fingerprint" and len(sys.argv) == 3:
        print(fingerprint(sys.argv[2]))
        return 0

    if cmd == "add" and len(sys.argv) >= 3:
        add_reference(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
        return 0

    if cmd == "check" and len(sys.argv) == 3:
        result = check_clip(sys.argv[2])
        print(json.dumps(result, indent=2))
        return 1 if result["status"] == "flagged" else 0

    if cmd == "check-all":
        clips = sorted(Path("clips").rglob("*.mp4"))
        if not clips:
            print("no clips found")
            return 0
        flagged = 0
        for c in clips:
            r = check_clip(str(c))
            mark = "FLAGGED" if r["status"] == "flagged" else "clear"
            if r["status"] == "flagged":
                flagged += 1
            print(f"  [{mark}] {c}")
        print(f"\n{flagged}/{len(clips)} clips flagged")
        return 1 if flagged else 0

    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
