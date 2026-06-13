"""FFmpeg / ffprobe adapter (Layer 0).

Exposes just the operations the atomic audio/video compressors need:

* :meth:`FFmpegAdapter.probe` — structured media metadata via ffprobe.
* :meth:`FFmpegAdapter.transcode_audio` — re-encode audio to a target bitrate,
  keeping the *same* codec/container (DESIGN.md §4.2).
* :meth:`FFmpegAdapter.transcode_video` — re-encode video by CRF or target
  bitrate, keeping the *same* container (DESIGN.md §4.3).

All command-line nuance (encoder selection per codec, pixel formats, ``-y``)
lives here and nowhere else.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ...logging_config import get_logger
from ..exceptions import ToolExecutionError
from .process import CommandResult, run, which

log = get_logger(__name__)

# Map an input audio codec name (as reported by ffprobe) to the FFmpeg encoder
# that reproduces the *same* format. This is what keeps mp3->mp3, aac->aac, etc.
AUDIO_ENCODER_FOR_CODEC: dict[str, str] = {
    "mp3": "libmp3lame",
    "aac": "aac",
    "vorbis": "libvorbis",
    "opus": "libopus",
    "flac": "flac",
    "ac3": "ac3",
    "wmav2": "wmav2",
    "pcm_s16le": "pcm_s16le",
}

VIDEO_ENCODER_FOR_CODEC: dict[str, str] = {
    "h264": "libx264",
    "hevc": "libx265",
    "mpeg4": "mpeg4",
    "vp8": "libvpx",
    "vp9": "libvpx-vp9",
    "av1": "libaom-av1",
    "mpeg2video": "mpeg2video",
}


@dataclass(slots=True)
class StreamInfo:
    index: int
    codec_type: str  # "video" | "audio" | ...
    codec_name: str
    bit_rate: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None


@dataclass(slots=True)
class MediaInfo:
    format_name: str
    duration: float
    size_bytes: int
    overall_bit_rate: Optional[int]
    streams: list[StreamInfo] = field(default_factory=list)

    @property
    def video_streams(self) -> list[StreamInfo]:
        return [s for s in self.streams if s.codec_type == "video"]

    @property
    def audio_streams(self) -> list[StreamInfo]:
        return [s for s in self.streams if s.codec_type == "audio"]

    @property
    def primary_video(self) -> Optional[StreamInfo]:
        return self.video_streams[0] if self.video_streams else None

    @property
    def primary_audio(self) -> Optional[StreamInfo]:
        return self.audio_streams[0] if self.audio_streams else None


class FFmpegAdapter:
    """Thin wrapper around the ``ffmpeg`` and ``ffprobe`` executables."""

    def __init__(
        self,
        ffmpeg_path: Optional[str] = None,
        ffprobe_path: Optional[str] = None,
    ) -> None:
        self.ffmpeg_path = ffmpeg_path or which("ffmpeg") or "ffmpeg"
        self.ffprobe_path = ffprobe_path or which("ffprobe") or "ffprobe"

    # --- availability ------------------------------------------------------------

    def is_available(self) -> bool:
        return which(self.ffmpeg_path) is not None or Path(self.ffmpeg_path).exists()

    # --- probing -----------------------------------------------------------------

    def probe(self, input_path: Path, *, timeout: float = 60) -> MediaInfo:
        """Return structured metadata for ``input_path`` using ffprobe."""
        result = run(
            [
                self.ffprobe_path,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(input_path),
            ],
            tool="ffprobe",
            timeout=timeout,
        )
        return self._parse_probe(result, input_path)

    def _parse_probe(self, result: CommandResult, input_path: Path) -> MediaInfo:
        try:
            data = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise ToolExecutionError(
                "ffprobe", stderr=f"Unparseable JSON: {exc}", command=result.command
            ) from exc

        fmt = data.get("format", {})
        streams: list[StreamInfo] = []
        for s in data.get("streams", []):
            streams.append(
                StreamInfo(
                    index=int(s.get("index", 0)),
                    codec_type=s.get("codec_type", "unknown"),
                    codec_name=s.get("codec_name", "unknown"),
                    bit_rate=_to_int(s.get("bit_rate")),
                    width=_to_int(s.get("width")),
                    height=_to_int(s.get("height")),
                    sample_rate=_to_int(s.get("sample_rate")),
                    channels=_to_int(s.get("channels")),
                )
            )
        return MediaInfo(
            format_name=fmt.get("format_name", ""),
            duration=float(fmt.get("duration", 0.0) or 0.0),
            size_bytes=_to_int(fmt.get("size")) or input_path.stat().st_size,
            overall_bit_rate=_to_int(fmt.get("bit_rate")),
            streams=streams,
        )

    # --- audio transcode ---------------------------------------------------------

    def transcode_audio(
        self,
        input_path: Path,
        output_path: Path,
        *,
        codec: str,
        bitrate_kbps: int,
        sample_rate: Optional[int] = None,
        channels: Optional[int] = None,
        timeout: float = 600,
    ) -> None:
        """Re-encode an audio file to ``bitrate_kbps`` using the codec-matched encoder."""
        encoder = AUDIO_ENCODER_FOR_CODEC.get(codec, codec)
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-i",
            str(input_path),
            "-vn",
            "-c:a",
            encoder,
            "-b:a",
            f"{bitrate_kbps}k",
        ]
        if sample_rate:
            cmd += ["-ar", str(sample_rate)]
        if channels:
            cmd += ["-ac", str(channels)]
        cmd.append(str(output_path))
        run(cmd, tool="ffmpeg", timeout=timeout)

    # --- video transcode ---------------------------------------------------------

    def transcode_video(
        self,
        input_path: Path,
        output_path: Path,
        *,
        video_codec: str,
        crf: Optional[int] = None,
        video_bitrate_kbps: Optional[int] = None,
        scale_width: Optional[int] = None,
        audio_codec: Optional[str] = None,
        audio_bitrate_kbps: int = 128,
        fps: Optional[float] = None,
        timeout: float = 1800,
    ) -> None:
        """Re-encode video keeping the container; drive quality by CRF or bitrate.

        Exactly one of ``crf`` / ``video_bitrate_kbps`` should be supplied.
        """
        encoder = VIDEO_ENCODER_FOR_CODEC.get(video_codec, "libx264")
        cmd = [self.ffmpeg_path, "-y", "-i", str(input_path), "-c:v", encoder]

        if crf is not None:
            cmd += ["-crf", str(crf)]
            # x265 takes crf via -crf too; libvpx needs -b:v 0 to honor crf.
            if encoder in {"libvpx", "libvpx-vp9"}:
                cmd += ["-b:v", "0"]
            else:
                cmd += ["-preset", "medium"]
        elif video_bitrate_kbps is not None:
            cmd += ["-b:v", f"{video_bitrate_kbps}k"]
        else:  # pragma: no cover - guarded by callers
            raise ToolExecutionError(
                "ffmpeg", stderr="transcode_video needs crf or video_bitrate_kbps"
            )

        filters = []
        if scale_width:
            # Even width/height required by most encoders.
            filters.append(f"scale={scale_width}:-2")
        if fps:
            cmd += ["-r", f"{fps:g}"]
        if filters:
            cmd += ["-vf", ",".join(filters)]

        if audio_codec:
            enc = AUDIO_ENCODER_FOR_CODEC.get(audio_codec, "aac")
            cmd += ["-c:a", enc, "-b:a", f"{audio_bitrate_kbps}k"]
        else:
            cmd += ["-an"]

        cmd.append(str(output_path))
        run(cmd, tool="ffmpeg", timeout=timeout)


def _to_int(value: object) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
