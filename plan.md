# Video Clipping Pipeline - Architecture, LM Studio, AMD AMF & Monitoring Plan

## 1. Architecture Overview

This project implements a modular, pure-Python distributed system for automated video clipping, transcription, LM Studio analysis, FFmpeg editing (with AMD AMF / NVIDIA NVENC hardware acceleration), and multi-platform publishing.

```
video_clipping/
├── __init__.py          # Package exports
├── main.py              # System entry point
├── scheduler.py         # APScheduler triggers (cron/interval & YouTube monitoring)
├── api.py               # FastAPI webhook & YouTube monitor endpoints
├── database.py          # SQLite task/log state storage
├── pipeline.py          # Core processing (yt-dlp → Whisper → LM Studio → FFmpeg AMF/NVENC → Social APIs)
├── tasks.py             # Celery distributed tasks (Redis broker/backend)
├── test_db.py           # Consolidated SQLite database integration tests
├── .env.example         # Sample environment config template
├── video_clipping.db    # SQLite DB file
├── requirements.txt     # Dependencies
└── README.md            # Documentation
```

---

## 2. YouTube Video Monitoring & Ingestion Flow

You can start the workflow in two ways:

### Option A: Automatic Scheduled Channel Monitoring (`scheduler.py`)
- APScheduler periodically checks a list of YouTube channel URLs or RSS feeds (`https://www.youtube.com/feeds/videos.xml?channel_id=...`).
- When a new video is uploaded, it automatically extracts the video URL and queues a clipping task with a default or channel-specific starting prompt.

### Option B: On-Demand API Endpoint (`api.py`)
Send a `POST /monitor/youtube` HTTP request with video/channel details and your custom starting prompt:

```json
POST /monitor/youtube
{
  "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "starting_prompt": "Find the top 3 high-energy, educational clip highlights suitable for YouTube Shorts under 45 seconds.",
  "target_platforms": ["twitter", "youtube", "tiktok"]
}
```

---

## 3. Dynamic Title + Transcription Prompting Architecture

When a video is processed by the pipeline:

```
+-------------------------------------------------------------------------------+
| 1. Download & Metadata Extraction (yt-dlp)                                    |
| Extracts video MP4 file + Title: "How to Build AI Agents" + Description        |
+-------------------------------------------------------------------------------+
                                       |
                                       v
+-------------------------------------------------------------------------------+
| 2. Audio Transcription (Whisper + AMD DirectML / CUDA)                         |
| Generates full timestamped text transcription                                 |
+-------------------------------------------------------------------------------+
                                       |
                                       v
+-------------------------------------------------------------------------------+
| 3. Dynamic LM Studio Prompt Engine                                            |
| Constructs tailored prompt:                                                   |
| - Title: "How to Build AI Agents"                                             |
| - User's Starting Prompt: "Find top 3 high-energy clips under 45s"            |
| - Transcription text with timestamps                                          |
+-------------------------------------------------------------------------------+
                                       |
                                       v
+-------------------------------------------------------------------------------+
| 4. LM Studio API (/v1/chat/completions)                                       |
| Returns structured JSON: clip_start, clip_end, clip_title, platforms          |
+-------------------------------------------------------------------------------+
                                       |
                                       v
+-------------------------------------------------------------------------------+
| 5. FFmpeg AMF Editing & Social Publishing                                     |
| Cuts clip using AMD VCN GPU engine and posts to social APIs                    |
+-------------------------------------------------------------------------------+
```

### Prompt Construction Example in `pipeline.py`:

```python
def generate_lm_studio_prompt(video_title: str, starting_prompt: str, transcription: str) -> str:
    return f"""
    You are an expert video editor. Analyze this video and select highlight clips.

    VIDEO TITLE:
    "{video_title}"

    CUSTOM CLIP SELECTION INSTRUCTIONS:
    {starting_prompt or 'Find the top engaging, high-impact 30-60 second clips.'}

    FULL TRANSCRIPT WITH TIMESTAMPS:
    {transcription}

    RESPONSE FORMAT (JSON ONLY):
    {{
      "clips": [
        {{
          "clip_start": 45.0,
          "clip_end": 95.0,
          "title": "Agent Memory Explanation",
          "platforms": ["twitter", "youtube", "tiktok"]
        }}
      ]
    }}
    """
```

---

## 4. AMD Native Tools & Hardware Acceleration

- **FFmpeg AMF (Advanced Media Framework)**: Uses AMD **VCN (Video Core Next)** hardware video blocks (`h264_amf`, `hevc_amf`, `av1_amf`).
- **DirectML (`torch-directml`)**: Runs Whisper transcription on AMD Radeon GPUs via DirectX 12.
- **LM Studio AMD Backend**: Uses Vulkan/ROCm for local LLM inference on AMD hardware.

---

## 5. Distributed Multi-System & Multi-GPU Setup over Wi-Fi

```
Central Redis Broker (192.168.1.100:6379)
  │
  ├── System #1 (AMD GPU): Celery Worker [-Q amd_render_queue,transcribe_queue]
  │   └── Runs FFmpeg AMF Video Edit & DirectML Whisper
  │
  ├── System #2 (NVIDIA GPU): Celery Worker [-Q nvidia_render_queue]
  │   └── Runs FFmpeg NVENC Video Edit
  │
  └── Host System: LM Studio API Server (Port 1234)
```

---

## 6. Where to Put Social API Keys

Store in `.env`:
```env
TWITTER_API_KEY=your_twitter_api_key
TWITTER_API_SECRET=your_twitter_api_secret
TWITTER_ACCESS_TOKEN=your_twitter_access_token
TWITTER_ACCESS_TOKEN_SECRET=your_twitter_access_token_secret

YOUTUBE_API_KEY=your_youtube_api_key
YOUTUBE_CLIENT_SECRET_FILE=client_secret.json

TIKTOK_API_KEY=your_tiktok_api_key
TIKTOK_ACCESS_TOKEN=your_tiktok_access_token
```

---

## 7. Actionable Implementation Roadmap

1. **API & Monitoring**: Implement `POST /monitor/youtube` endpoint and scheduled channel polling in `scheduler.py`.
2. **Title + Prompt Engineering**: Update `pipeline.py` to extract `title` via `yt-dlp` and combine it with `starting_prompt` and `transcription` for LM Studio.
3. **AMD Hardware Acceleration**: Auto-detect AMD GPUs and apply `h264_amf` encoding.
4. **Distributed Celery Tasks**: Decouple pipeline into modular tasks and queue support across Wi-Fi systems.
