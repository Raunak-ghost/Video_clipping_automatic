# Video Production & Clipping Architecture Document

## System Overview

This system provides a unified video production platform combining:
1. **Automated Long-Form Video Clipping**: Automated highlight extraction, Whisper transcription, ASS subtitle styling, and hardware-accelerated rendering.
2. **AI Diffusion Video Generation**: Text-to-video workflow generation via ComfyUI (WAN 2.2 TI2V-5B model) optimized for AMD ROCm hardware.
3. **Multi-Style Creative Engine**: Preserved markdown creative specifications (`editing_styles/*.md`) paired with programmatic ComfyUI graph builders (`pipelines/styles/`).
4. **Hardware-Aware Acceleration**: Auto-detection prioritizing physical AMD Radeon RX 7900 XTX (`h264_amf`) with fallback to `h264_nvenc` and `libx264`.

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           UNIFIED RUNNER (run.py / run.bat)                    │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   ┌────────────────────────┐                   ┌────────────────────────────┐   │
│   │   pipelines/clipping   │                   │    pipelines/generative    │   │
│   ├────────────────────────┤                   ├────────────────────────────┤   │
│   │ - Downloader (yt-dlp)  │                   │ - ComfyClient (pooled HTTP)│   │
│   │ - Transcriber (Whisper)│                   │ - WorkflowBuilder (WAN 2.2)│   │
│   │ - Analyzer (LLM/Ollama)│                   │ - GenerativePipeline       │   │
│   │ - Renderer (AMF/ASS)   │                   │ - Prompt Expansion (Ollama)│   │
│   └───────────┬────────────┘                   └─────────────┬──────────────┘   │
│               │                                              │                  │
│               │         ┌───────────────────────────┐        │                  │
│               │         │     pipelines/styles      │        │                  │
│               │         ├───────────────────────────┤        │                  │
│               └────────▶│  Style Registry           │◀───────┘                  │
│                         │  - kids, anime, faceless  │                           │
│                         │  - movie, hormozi         │                           │
│                         │  Ref: editing_styles/*.md │                           │
│                         └─────────────┬─────────────┘                           │
│                                       │                                         │
│   ┌───────────────────────────────────┴─────────────────────────────────────┐   │
│   │                                core/                                    │   │
│   ├─────────────────────────────────────────────────────────────────────────┤   │
│   │  hardware.py (AMD AMF / NVENC / CPU) │ database.py (SQLite WAL)         │   │
│   │  styles.py (ASS presets, FFmpeg)     │ config.py (JSON settings)        │   │
│   └───────────────────────────────────┬─────────────────────────────────────┘   │
│                                       │                                         │
│   ┌───────────────────────────────────┴─────────────────────────────────────┐   │
│   │                              services/                                  │   │
│   ├─────────────────────────────────────────────────────────────────────────┤   │
│   │  api.py (FastAPI REST + Admin Studio)│ scheduler.py (APScheduler)       │   │
│   │  trigger_engine.py (Channel monitor) │ tasks.py (Task management)       │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Directory Organization

```
video_clipping/
├── core/                           # Shared foundation
│   ├── hardware.py                 # GPU detection (AMD AMF / NVENC / CPU)
│   ├── styles.py                   # ASS subtitle presets & FFmpeg filter generators
│   ├── config.py                   # Configuration loader & validator
│   └── database.py                 # SQLite database with WAL mode & retry handling
│
├── pipelines/                      # Production workflows
│   ├── clipping/                   # Long-form video clipping pipeline
│   │   ├── downloader.py           # yt-dlp downloader with cookie rotation
│   │   ├── transcriber.py          # Whisper transcription with cache
│   │   ├── analyzer.py             # Ollama highlight detection & fallbacks
│   │   ├── renderer.py             # ASS subtitle overlay & video encoding
│   │   └── pipeline.py             # ClipperPipeline orchestrator
│   │
│   ├── generative/                 # Text-to-video AI diffusion pipeline
│   │   ├── comfy_client.py         # Persistent connection-pooled ComfyUI client
│   │   ├── workflow_builder.py     # WAN 2.2 TI2V-5B graph generator
│   │   └── generator.py            # GenerativePipeline orchestrator
│   │
│   └── styles/                     # Programmatic style handlers
│       ├── registry.py             # Dynamic style discovery & dispatcher
│       ├── kids.py                 # 3D Pixar/nursery rhyme style
│       ├── anime.py                # High-saturation anime style
│       ├── faceless.py             # Ambient documentary style
│       ├── movie.py                # Cinematic trailer style
│       └── hormozi.py              # High-energy caption style
│
├── services/                       # Background processes & server endpoints
│   ├── api.py                      # FastAPI REST API & Admin Studio
│   ├── scheduler.py                # APScheduler job runner
│   ├── trigger_engine.py           # YouTube channel monitoring
│   └── tasks.py                    # Task queue & Celery management
│
├── editing_styles/                 # Preserved original creative specs (Markdown)
│   ├── editing_anime.md            # Original anime guidelines
│   ├── editing_faceless.md         # Original faceless documentary guidelines
│   ├── editing_hormozi.md          # Original Hormozi caption guidelines
│   ├── editing_kids.md             # Original kids nursery rhyme guidelines
│   └── editing_movie.md            # Original movie recap guidelines
│
├── instructions/                   # Creative copyright & production policies
│   ├── fair_use_guidelines.md      # Legal compliance & transformative analysis
│   └── ...                         # Production runbooks
│
├── run.py / run.bat                # Unified CLI entry point
├── generate_video.py / .bat        # Dedicated one-command generative video runner
├── main.py                         # FastAPI + Scheduler entry point
└── database.py, pipeline.py, ...   # Backward-compatibility shims
```

---

## Hardware Configuration

- **Host GPU:** AMD Radeon RX 7900 XTX (24 GB VRAM)
- **Active Driver:** 32.0.32015.7029
- **ROCm Environment:** `D:\ComfyUI\venv` (Python 3.12, PyTorch 2.9.1+rocm7.2.1)
- **Encoder Priority:**
  1. `h264_amf` (AMD GPU hardware encoder)
  2. `h264_nvenc` (NVIDIA hardware encoder, if available)
  3. `libx264` (Universal CPU software fallback)

---

## Commands & Usage

### 1. Unified Dispatcher
```bash
python run.py hardware                                       # Check GPU & FFmpeg encoders
python run.py generate "theme prompt" --style kids           # Generate video via ComfyUI
python run.py clip "https://youtube.com/watch?v=..."         # Clip a long-form video
python run.py movie "path/to/movie.mp4"                      # Process a local movie file
python run.py serve --port 8000                              # Launch FastAPI & Admin Studio
python run.py copyright "video_id_or_title"                  # Evaluate fair use compliance
```

### 2. Generative Video One-Click Runner
```bash
generate_video.bat "a cute baby panda playing in autumn leaves" --style kids
# Or directly:
python generate_video.py "prompt" --style anime --frames 17 --steps 6
```
