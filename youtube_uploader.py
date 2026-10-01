"""YouTube Data API v3 Video Uploader.

Handles:
- OAuth 2.0 authorization using client_id and client_secret from config.json
- Persisting authorization token in youtube_token.json (refresh token flow)
- Resumable video file upload to your YouTube channel as Shorts or standard video
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional, Dict, Any

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_FILE = "youtube_token.json"
CONFIG_FILE = "config.json"


def _load_youtube_config() -> dict:
    """Load YouTube credentials from config.json."""
    if Path(CONFIG_FILE).exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("upload_connectors", {}).get("youtube", {})
        except Exception as e:
            logger.error(f"Error loading YouTube credentials: {e}")
    return {}


def get_authenticated_service():
    """Authenticate and return the YouTube Data API v3 service."""
    creds = None
    token_path = Path(TOKEN_FILE)

    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception as e:
            logger.warning(f"Existing token invalid: {e}")

    # If no valid credentials available, refresh or run OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                logger.warning(f"Could not refresh token: {e}")
                creds = None

        if not creds:
            yt_cfg = _load_youtube_config()
            client_id = yt_cfg.get("client_id")
            client_secret = yt_cfg.get("client_secret")

            if not client_id or not client_secret:
                raise ValueError("YouTube client_id or client_secret missing in config.json")

            client_config = {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            }

            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            creds = flow.run_local_server(port=0, prompt="consent")

        # Save credentials for future runs
        token_path.write_text(creds.to_json(), encoding="utf-8")
        logger.info(f"Saved YouTube authorization token to {TOKEN_FILE}")

    return build("youtube", "v3", credentials=creds)


def upload_video(
    file_path: str,
    title: str = "Video Highlight #Shorts",
    description: str = "Created with Video Clipping Pipeline #Shorts",
    tags: Optional[list] = None,
    privacy_status: str = "private",  # 'private', 'unlisted', or 'public'
) -> Dict[str, Any]:
    """Upload a video to YouTube.

    Args:
        file_path: Absolute or relative path to MP4 video file.
        title: Title of the video.
        description: Description of the video.
        tags: Optional list of tag keywords.
        privacy_status: 'public', 'unlisted', or 'private' (default: 'private' for safety).

    Returns:
        Dict with video_id, url, and upload metadata.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Video file not found: {file_path}")

    youtube = get_authenticated_service()

    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags or ["Shorts", "Highlights"],
            "categoryId": "28",  # Science & Technology (or 24 Entertainment)
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(path),
        chunksize=1024 * 1024 * 4,  # 4MB chunks
        resumable=True,
        mimetype="video/mp4",
    )

    logger.info(f"Starting upload for {path.name} to YouTube...")
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info(f"Uploaded {int(status.progress() * 100)}%")

    video_id = response.get("id")
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    logger.info(f"Successfully uploaded video to YouTube! URL: {video_url}")

    return {
        "status": "success",
        "video_id": video_id,
        "video_url": video_url,
        "privacy_status": privacy_status,
        "title": title,
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--auth":
        print("Starting YouTube OAuth authorization...")
        svc = get_authenticated_service()
        print("✓ YouTube authorization successful! Token saved to youtube_token.json")
    elif len(sys.argv) > 1:
        video_file = sys.argv[1]
        print(f"Uploading {video_file}...")
        res = upload_video(video_file, privacy_status="private")
        print("Upload Result:", res)
    else:
        print("Usage:")
        print("  python youtube_uploader.py --auth          # Run one-time browser login to authorize YouTube upload")
        print("  python youtube_uploader.py <clip.mp4>      # Upload clip to YouTube")
