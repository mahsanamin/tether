"""Media helpers: classify uploads and (optionally) transcribe voice notes.

tether just stores and serves bytes. Transcription is a media transform (audio
to text), never interpretation, and is off by default in favour of client-side
Web Speech. Server-side Whisper is enabled with `voice = whisper` and requires
`uv add faster-whisper`.
"""

from __future__ import annotations

import os

_whisper_model = None


# MIME types safe to serve inline (the browser renders them as media, not code).
# Anything else (HTML, SVG, scripts, unknown) is served as a download instead, to
# avoid stored XSS on tether's own origin.
INLINE_MIMES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "audio/webm",
    "audio/ogg",
    "audio/mpeg",
    "audio/wav",
    "audio/mp4",
    "audio/x-m4a",
}


def safe_mime(mime: str) -> str:
    """Keep known-inline-safe types; downgrade everything else to a download.

    Strips any `;codecs=...` parameter, since MediaRecorder sends e.g.
    `audio/webm;codecs=opus`.
    """
    base = (mime or "").split(";")[0].strip().lower()
    return base if base in INLINE_MIMES else "application/octet-stream"


def guess_kind(mime: str) -> str:
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    return "file"


def transcribe_audio(path: str) -> str | None:
    """Return a transcript for an audio file, or None if disabled/unavailable.

    Synchronous and potentially slow; call it via asyncio.to_thread.
    """
    global _whisper_model
    if os.environ.get("TETHER_VOICE", "browser") != "whisper":
        return None
    try:
        from faster_whisper import WhisperModel
    except Exception:
        return None
    if _whisper_model is None:
        _whisper_model = WhisperModel(os.environ.get("TETHER_WHISPER_MODEL", "base"))
    segments, _ = _whisper_model.transcribe(path)
    text = " ".join(s.text for s in segments).strip()
    return text or None
