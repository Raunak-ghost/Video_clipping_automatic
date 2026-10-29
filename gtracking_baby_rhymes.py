#!/usr/bin/env python
"""gtracking_baby_rhymes.py

Standard gtracking workflow for processing multiple baby‑rhymes videos.

The script accepts a list of video URLs or local file paths, processes each
video through the existing :class:`Pipeline` from ``pipeline.py`` and writes a
markdown report that includes:

* Input video title, duration and format.
* Processing status (completed / failed).
* Any errors encountered.
* A progress bar that shows the current status of the workflow.

The report is written to ``gtracking_report.md`` in the repository root.

Usage::

    python gtracking_baby_rhymes.py --videos url1 url2 ...

or provide a text file with one URL per line::

    python gtracking_baby_rhymes.py --list videos.txt

The script is intentionally lightweight and does not modify any existing
pipeline logic.  It simply orchestrates the pipeline and aggregates the
results.
"""

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from datetime import datetime

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

from pipeline import Pipeline
from database import Database

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def load_video_list(args) -> list[str]:
    """Return a list of video URLs or file paths.

    The function supports two modes:

    * ``--videos`` – a space separated list of URLs/paths.
    * ``--list`` – a file containing one URL/path per line.
    """
    if args.videos:
        return list(args.videos)
    if args.list:
        with open(args.list, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    return []


def format_report_entry(entry: dict) -> str:
    """Return a markdown table row for a single video entry."""
    status = entry.get("status", "unknown")
    title = entry.get("title", "<unknown>")
    duration = entry.get("duration", "<unknown>")
    fmt = entry.get("format", "<unknown>")
    error = entry.get("error", "")
    return f"| {entry['index']} | {title} | {duration} | {fmt} | {status} | {error} |"

# ---------------------------------------------------------------------------
# Main workflow
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="gtracking baby‑rhymes workflow")
    parser.add_argument("--videos", nargs="*", help="Video URLs or local paths")
    parser.add_argument("--list", help="File containing one video URL/path per line")
    parser.add_argument("--report", default="gtracking_report.md", help="Output report file")
    args = parser.parse_args()

    video_list = load_video_list(args)
    if not video_list:
        print("No videos specified.")
        sys.exit(1)

    # Initialise database (used by Pipeline for status updates)
    db = Database()
    pipeline = Pipeline(db)

    results = []
    progress = tqdm(video_list, desc="Processing videos", disable=not tqdm)
    for idx, video in enumerate(progress, start=1):
        task_id = str(uuid.uuid4())
        # The Pipeline expects a URL; if a local path is provided, we can
        # convert it to a file:// URL so that the download step is skipped.
        if os.path.isfile(video):
            video_url = Path(video).absolute().as_uri()
        else:
            video_url = video
        res = pipeline.process_video(video_url, task_id)
        # Extract useful info for the report
        entry = {
            "index": idx,
            "status": res.get("status", "unknown"),
            "title": res.get("title", "<unknown>"),
            "duration": res.get("duration", "<unknown>"),
            "format": res.get("format", "<unknown>"),
            "error": res.get("error", ""),
        }
        results.append(entry)

    # Write markdown report
    report_path = Path(args.report)
    with report_path.open("w", encoding="utf-8") as f:
        f.write("# Baby Rhymes gtracking Report\n\n")
        f.write("| # | Title | Duration | Format | Status | Error |\n")
        f.write("|---|-------|---------|--------|--------|------|\n")
        for entry in results:
            f.write(format_report_entry(entry) + "\n")

    print(f"Report written to {report_path}")


if __name__ == "__main__":
    main()

"""
# End of file
"""
