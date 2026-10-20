# Plan: Higgsfield-Style AI B-Roll via muapi.ai

Port the "styling styles" from [Autom8AI/Open-Higgsfield-AI](https://github.com/Autom8AI/Open-Higgsfield-AI) into this pipeline. In that repo, "styles" are **not CSS/UI themes** — they are a **cinematic prompt taxonomy** (`src/lib/promptUtils.js`) plus a **muapi.ai generation client** (`src/lib/muapi.js`). The chosen integration (confirmed): give every edited clip the ability to generate **styled AI b-roll** (images now, video later) using those camera/lens/lighting presets, and composite them into the FFmpeg render.

---

## 1. What we're porting (source → target)

| Open-Higgsfield-AI source | Purpose | Target in this repo |
|---|---|---|
| `src/lib/promptUtils.js` | Camera/lens/focal/aperture maps, quality tags, `buildNanoBananaPrompt()` | new `broll_styles.py` |
| `src/lib/muapi.js` | muapi.ai client: submit → poll → result URL, upload, image/video/I2I/I2V/lip-sync | new `muapi_client.py` (subset: image, video, upload, download) |
| `src/lib/models.js` (260 KB catalog) | Model ids/endpoints/params | small curated dict in `muapi_client.py` (no full port) |

**Chosen model defaults** (from the repo's catalog):

| Phase | Default model | Endpoint | Key params | Alternatives |
|---|---|---|---|---|
| 1 — b-roll stills | `nano-banana` | `nano-banana` | `prompt`, `aspect_ratio` (supports `9:16`) | budget: `flux-schnell` (`flux-schnell-image`); premium: `nano-banana-pro`, `nano-banana-2`, `seedream-5.0` |
| 2 — b-roll video | `seedance-lite-t2v` | `seedance-lite-t2v` | `prompt`, `aspect_ratio` (`9:16`), `duration` (default 5 s), `resolution` (480p/720p/1080p) | premium: `kling-v2.1-master-t2v`, `seedance-v2.0-t2v`, `veo3*` |
| 2 — upscale stills | `ai-image-upscaler` | `ai-image-upscale` | image in/out | optional polish step |

> Note: models without an explicit `endpoint` field in the catalog use the model id as the endpoint — verify per model against the muapi.ai response at implementation time.

No new dependencies: `httpx`, `aiohttp`, `python-dotenv` are already in `requirements.txt`.

---

## 2. New files

### 2.1 `broll_styles.py` — taxonomy port (verbatim from `promptUtils.js`)

```python
CAMERA_MAP = {
    "Modular 8K Digital": "modular 8K digital cinema camera",
    "Full-Frame Cine Digital": "full-frame digital cinema camera",
    "Grand Format 70mm Film": "grand format 70mm film camera",
    "Studio Digital S35": "Super 35 studio digital camera",
    "Classic 16mm Film": "classic 16mm film camera",
    "Premium Large Format Digital": "premium large-format digital cinema camera",
}
LENS_MAP = {
    "Creative Tilt Lens": "creative tilt lens effect",
    "Compact Anamorphic": "compact anamorphic lens",
    "Extreme Macro": "extreme macro lens",
    "70s Cinema Prime": "1970s cinema prime lens",
    "Classic Anamorphic": "classic anamorphic lens",
    "Premium Modern Prime": "premium modern prime lens",
    "Warm Cinema Prime": "warm-toned cinema prime lens",
    "Swirl Bokeh Portrait": "swirl bokeh portrait lens",
    "Vintage Prime": "vintage prime lens",
    "Halation Diffusion": "halation diffusion filter",
    "Clinical Sharp Prime": "ultra-sharp clinical prime lens",
}
FOCAL_PERSPECTIVE = {8: "ultra-wide perspective", 14: "wide-angle perspective",
                     24: "wide-angle dynamic perspective", 35: "natural cinematic perspective",
                     50: "standard portrait perspective", 85: "classic portrait perspective"}
APERTURE_EFFECT = {"f/1.4": "shallow depth of field, creamy bokeh",
                   "f/4": "balanced depth of field",
                   "f/11": "deep focus clarity, sharp foreground to background"}
ENHANCE_TAGS = {
    "quality": ["professional photography", "ultra-detailed", "8K resolution",
                "high dynamic range", "award-winning"],
    "lighting": ["cinematic lighting", "golden hour", "dramatic studio lighting",
                 "soft diffused light", "neon glow", "volumetric rays"],
    "mood": ["moody atmosphere", "serene and peaceful", "epic and dramatic",
             "warm and cozy", "dark and mysterious"],
    "style": ["photorealistic", "oil painting style", "watercolor", "digital art",
              "concept art", "anime style", "cyberpunk aesthetic"],
}
```

Plus a Python port of `buildNanoBananaPrompt()`:

```python
def build_cinematic_prompt(base_prompt, camera, lens, focal, aperture):
    """Port of buildNanoBananaPrompt(): compiles base prompt + camera/lens/focal/aperture
    into one cinematic prompt string."""
```

Identical output to the JS version: `"{base}, shot on a {camera}, using a {lens} at {focal}mm ({perspective}), aperture {aperture}, {depth}, cinematic lighting, natural color science, high dynamic range, professional photography, ultra-detailed, 8K resolution"`.

Also add curated **look presets** (deterministic per-category defaults, so the 8B Ollama model doesn't have to choose gear):

```python
LOOK_PRESETS = {
    "default":  {"camera": "Full-Frame Cine Digital", "lens": "Premium Modern Prime", "focal": 35, "aperture": "f/4"},
    "war_geopolitical": {"camera": "Grand Format 70mm Film", "lens": "Vintage Prime", "focal": 24, "aperture": "f/4"},
    "tech_news": {"camera": "Studio Digital S35", "lens": "Clinical Sharp Prime", "focal": 50, "aperture": "f/1.4"},
    "movie":    {"camera": "Classic 16mm Film", "lens": "Halation Diffusion", "focal": 24, "aperture": "f/1.4"},
    "anime":    {"camera": "Premium Large Format Digital", "lens": "Compact Anamorphic", "focal": 35, "aperture": "f/4"},
    # ... one per category; cues rotate through 2-3 variants so clips don't look identical
}
```

### 2.2 `muapi_client.py` — Python port of `MuapiClient` (httpx, async)

Protocol (mirrors `muapi.js` exactly):

- Base URL `https://api.muapi.ai`; header `x-api-key: <key>` on every request.
- **Submit**: `POST /api/v1/{endpoint}` with model payload → `{request_id}` (fallback key `id`).
- **Poll**: `GET /api/v1/predictions/{request_id}/result` every 2 s until:
  - `status` in `{"completed", "succeeded", "success"}` → done
  - `status` in `{"failed", "error"}` → raise
  - HTTP 5xx → keep polling (transient); HTTP 4xx → raise immediately
- **Result URL**: `result.outputs[0] or result.url or result.output.url`.

Methods:

| Method | Payload | Poll budget |
|---|---|---|
| `generate_image(prompt, aspect_ratio="9:16", model="nano-banana", image_url=None, strength=0.6, seed=None)` | per-model inputs | 60 × 2 s (~2 min) |
| `generate_video(prompt, aspect_ratio="9:16", duration=5, resolution="720p", model="seedance-lite-t2v", image_url=None)` | per-model inputs | 900 × 2 s (30 min) |
| `upload_file(path)` | multipart field `file` → hosted URL (`data.url or data.file_url or data.data.url`) | — |
| `download(url, dest_path)` | stream to disk | — |

Per-model input mapping (from `muapi.js`): some models take `image_url`, others `images_list` — keep a small `MODEL_INPUTS` dict for the curated models only. Key comes from `os.getenv("MUAPI_API_KEY")` (loaded via `python-dotenv`); missing key ⇒ client constructor raises `MuapiNotConfigured`, which the caller treats as "b-roll disabled".

### 2.3 `broll.py` — orchestrator (the glue)

1. `plan_broll(edl, category, cfg)` — validate/normalize the EDL's `broll` array:
   - clamp cue count to the category's density cap (see §6),
   - clamp each cue to `2–4 s`, inside clip bounds, non-overlapping,
   - fill missing `camera/lens/focal/aperture` from `LOOK_PRESETS[category]` (rotating variants),
   - compile final generation prompt via `build_cinematic_prompt()`.
2. `generate_broll_assets(cues, cfg)` — `asyncio.gather` over cues:
   - cache key = `sha256(model | prompt | aspect_ratio | params)` → `cache/broll/<hash>.png`; skip API if present (mirrors the existing whisper-transcript cache pattern),
   - generate → download into cache → return `[{path, start, end, duration, motion}]`,
   - per-cue try/except: a failed cue is dropped with a warning, never fatal.
3. `build_broll_ffmpeg_inputs(assets)` / `build_broll_filter_fragment(assets, base_label)` — produce the `-loop 1 ...` input args and the `zoompan`/`overlay` filter graph described in §5.

---

## 3. EDL schema extension (LLM instructions)

Extend the current schema in `editing_instructions.md` (and the per-category `instructions/*.md`) with an **optional** `broll` array. The LLM only supplies **content + timing**; Python applies the cinematic look deterministically (keeps the 8B model's job simple).

```json
{
  "clip_start": 12.4,
  "clip_end": 55.2,
  "title": "Why this changes everything",
  "aspect_ratio": "9:16",
  "platforms": ["youtube"],
  "reason": "...",
  "broll": [
    {
      "start": 2.0,
      "end": 5.0,
      "prompt": "a lone surveillance drone gliding over a neon-lit city at night, rain reflections",
      "motion": "zoom-in"
    }
  ]
}
```

Rules to add to the instructions:

- `broll` is optional; emit `[]` or omit when the footage doesn't need it; max 3 cues.
- `start`/`end` are **seconds relative to clip start** (0 = first frame of the clip); each cue 2–4 s; no overlaps.
- `prompt`: pure visual description, < 200 chars, no on-screen text/logos/watermarks, no real people's faces, no brand names.
- `motion`: one of `zoom-in` (default), `zoom-out`, `pan-left`, `pan-right`.
- Only emit b-roll when it visually **explains or dramatizes** what is being said at that moment.

`pipeline.py` EDL parsing: `edl.get("broll") or []` — fully backward compatible; old LLM output without `broll` keeps working.

---

## 4. Config changes (`config.json`)

```json
"muapi": {
  "enabled": false,
  "api_key_env": "MUAPI_API_KEY",
  "base_url": "https://api.muapi.ai",
  "image_model": "nano-banana",
  "video_model": "seedance-lite-t2v",
  "video_enabled": false,
  "dry_run": false,
  "broll_density": {
    "default": 1, "tech_news": 2, "war_geopolitical": 3, "faceless": 3,
    "movie": 1, "movie_recap": 1, "anime": 0, "anime_recap": 0,
    "kids": 0, "baby_rhymes": 0, "gameplay": 0, "sports": 0, "ufc": 0,
    "podcasts": 0, "memes_funny": 0, "high_views": 1, "gaming": 0, "corporate": 1
  }
}
```

- `enabled: false` ships first; flip to `true` once `MUAPI_API_KEY` is set in `.env`.
- `dry_run: true` logs the compiled prompts without calling the API (for testing prompt quality).
- Density = max cues per clip (0 = off). Rationale: faceless/war/tech benefit most (talking-head/news footage); gameplay/sports/kids/anime have constant native action or a clashing art style.
- **Security**: the key lives in `.env` (add `.env` to `.gitignore`, add `.env.example` with `MUAPI_API_KEY=`), *not* in config.json — which already contains plaintext social credentials (migrating those is recommended but out of scope here).

---

## 5. Render integration (`pipeline.py` → `edit_video_clip()`)

**Zero-regression rule**: when b-roll is disabled, absent, or all cues fail, the existing filter graphs and command build are used untouched.

When assets exist:

1. **Inputs** — for each still asset (Phase 1): `-loop 1 -framerate 30 -t {duration} -i {path}`; for video assets (Phase 2): `-t {duration} -i {path}`. All b-roll inputs get `-an` semantics (video-only) since `overlay` uses video pads only.
2. **Filter graph** — b-roll overlays are inserted **before** the `subtitles` filter in every style graph, so captions always render on top of b-roll (retention-critical):
   - Still + Ken Burns (zoompan over a single-frame input):
     ```
     [k:v]scale=2160:3840:force_original_aspect_ratio=increase,crop=2160:3840,
       zoompan=z='min(zoom+0.0015,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':
               d={duration*30}:s=1080x1920:fps=30,setsar=1[b0]
     ```
     (`zoom-out`/`pan-*` variants swap the `z`/`x` expressions; finalize expressions during implementation.)
   - Video asset: `[k:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,setsar=1[b0]`
   - Overlay chain: `[base][b0]overlay=enable='between(t,{start},{end})':eval=frame[t0]; [t0][b1]overlay=...[t1]; ... [tN]subtitles='<ass>'[v]`
3. **Graph plumbing** — the six `vf`-chain styles (subtitles/hormozi/kids/anime/movie/corporate) get promoted to `filter_complex` when b-roll is present: existing chain runs on `[0:v]` up to `crop`, then overlays, then `subtitles`. The four `filter_complex` styles (podcast/faceless/gameplay/blur) insert the overlay chain on their existing final label before their subtitles stage. One shared helper (`broll.build_broll_filter_fragment`) serves all ten styles.
4. **Timing** — cue `start/end` are relative to the clip, and the FFmpeg command already uses `-ss clip_start -t duration`, so `enable='between(t,...)'` lines up with the clip-local timeline as-is.

---

## 6. Pipeline flow change (`editing_styles/index.md`)

Current: trigger → transcript → category/style match → style spec → LLM EDL → FFmpeg render.
New step between EDL and render:

```
LLM EDL (now with optional broll[]) 
  → broll.plan_broll()        (density caps, look presets, prompt compilation)
  → broll.generate_broll_assets()  (parallel, cached, failure-tolerant)
  → edit_video_clip()         (composites assets into the filter graph)
```

---

## 7. Failure & cost policy

- Missing key / `enabled: false` → b-roll silently off (one log line).
- API error, timeout, or failed generation → drop that cue, warn, render the rest. **The pipeline must never fail because of b-roll.**
- Phase 1 latency: cues generate in parallel; worst case ~2 min added per clip (image poll budget 60 × 2 s). Typical: 20–60 s.
- Phase 2 latency: video polls can run to 30 min ⇒ video b-roll must be **prefetched immediately after the EDL is produced** (before render starts) and/or moved to a pre-generation queue; `video_enabled` stays `false` until that's in place.
- Cache hit ⇒ zero added latency on re-runs of the same clip/prompt.

---

## 8. Phased rollout

| Phase | Scope | Deliverables |
|---|---|---|
| **1** (this plan's core) | Stills-only b-roll | `broll_styles.py`, `muapi_client.py` (image path), `broll.py`, EDL schema + instructions update, render compositing, config, caching, `.env` hygiene |
| **2** | Video b-roll | `generate_video()` + `seedance-lite-t2v`, prefetch/queue, optional `ai-image-upscaler` polish for stills, premium model options (kling/veo) |
| **3** (optional, out of scope) | i2i restyle of real frames (`upload_file` + `image_url` + `strength`), lip-sync | documented hooks only |

---

## 9. Implementation checklist (ordered)

1. `broll_styles.py` — taxonomy + `build_cinematic_prompt()` + `LOOK_PRESETS` (unit-testable pure functions).
2. `muapi_client.py` — async client: submit/poll/result-URL/upload/download; `MuapiNotConfigured` on missing key.
3. `broll.py` — plan/generate/filter-fragment helpers with caching (`cache/broll/`) and per-cue fault tolerance.
4. `config.json` — add `muapi` section (disabled by default); `.env.example` + `.gitignore` entry.
5. `editing_instructions.md` + `instructions/*.md` — add the `broll` array spec + rules (§3).
6. `pipeline.py` — parse `broll` from EDL; call `plan_broll`/`generate_broll_assets` before render; extend `edit_video_clip()` with the overlay graph behind an "assets exist" guard.
7. `editing_styles/index.md` — insert the b-roll step into the 6-step flow.
8. Test: `dry_run` prompt review → one real generation per high-density category (faceless, war_geopolitical, tech_news) → verify captions render above b-roll → verify a clip with b-roll disabled is byte-identical to today's output.

---

## 10. Verification criteria

- A clip with `broll: []` or b-roll disabled renders exactly as before (no graph changes on that path).
- A clip with 2 cues shows b-roll at the right times, 1080×1920, with captions visible on top.
- Same prompt twice ⇒ second run uses the cache (no API call).
- With `MUAPI_API_KEY` unset, the full pipeline run succeeds end-to-end.
