"""VideoCompressor (Layer 1) — DESIGN.md §4.3.

Lossy only; the output **container equals the input** (mp4->mp4, mkv->mkv, …)
and the video stream is re-encoded with a container-compatible codec. The
primary convergence knob is **CRF** (constant-quality factor); the downscale
ladder reduces resolution width when CRF alone cannot reach the ceiling.

Because re-encoding video is expensive, the controller's per-knob result cache
(and a deliberately small CRF search space mapped onto an integer "quality"
knob) keep the number of ffmpeg invocations low.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ...logging_config import get_logger
from ..adapters.ffmpeg import VIDEO_ENCODER_FOR_CODEC
from ..media_type import FileFormat, MediaClass, format_from_extension
from ..models import CompressionResult, CompressionTarget
from .base import AtomicCompressor, ProgressFn, lerp

log = get_logger(__name__)


class VideoCompressor(AtomicCompressor):
    media_class = MediaClass.VIDEO

    def compress(
        self,
        input_path: Path,
        target: CompressionTarget,
        *,
        output_path: Optional[Path] = None,
        work: Optional[Path] = None,
        out_format: Optional[FileFormat] = None,
        on_progress: Optional[ProgressFn] = None,
    ) -> CompressionResult:
        self.registry.require("ffmpeg")
        work = self._ensure_work(work)
        original_bytes = input_path.stat().st_size
        fmt = out_format or format_from_extension(input_path.suffix)
        ext = input_path.suffix.lstrip(".") or fmt.value
        if output_path is None:
            output_path = work / f"out.{ext}"

        info = self.registry.ffmpeg.probe(input_path)
        vstream = info.primary_video
        if vstream is None:
            raise _no_video(input_path)
        vcodec = vstream.codec_name if vstream.codec_name in VIDEO_ENCODER_FOR_CODEC else "h264"
        astream = info.primary_audio
        acodec = astream.codec_name if astream else None

        resolved = target.resolve(original_bytes)
        opts = self.options

        # Map an integer "quality" knob onto the CRF axis: higher knob -> lower
        # CRF -> bigger file (so the controller's monotonic assumption holds).
        crf_lo, crf_hi = opts.video_min_crf, opts.video_max_crf
        knob_min, knob_max = 0, crf_hi - crf_lo

        base_w = vstream.width or 1920
        state = {"width": None}  # None => keep source width

        def knob_to_crf(knob: int) -> int:
            return crf_hi - knob

        def encode(knob: int) -> Path:
            crf = knob_to_crf(knob)
            w = state["width"]
            cand = work / f"cand_{crf}_{w or 'src'}.{ext}"
            self.registry.ffmpeg.transcode_video(
                input_path,
                cand,
                video_codec=vcodec,
                crf=crf,
                scale_width=w,
                audio_codec=acodec,
            )
            return cand

        def downscale() -> bool:
            cur = state["width"] or base_w
            nxt = int(cur * opts.downscale_factor)
            nxt -= nxt % 2  # keep even for the encoder
            if nxt < 160:
                return False
            state["width"] = nxt
            return True

        conv = self.controller.converge(
            target=resolved,
            encode=encode,
            knob_min=knob_min,
            knob_max=knob_max,
            fmt=fmt,
            downscale=downscale,
            on_progress=on_progress,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        conv.path.replace(output_path)

        note_bits = []
        if state["width"]:
            note_bits.append(f"downscaled to {state['width']}px wide")
        if conv.note:
            note_bits.append(conv.note)

        return CompressionResult(
            output_path=str(output_path),
            original_bytes=original_bytes,
            final_bytes=output_path.stat().st_size,
            landed_in_band=conv.landed_in_band,
            media_class=MediaClass.VIDEO,
            file_format=fmt,
            operations=conv.operations,
            note="; ".join(note_bits) or None,
        )

    def encode_quality(
        self,
        input_path: Path,
        quality: int,
        *,
        output_path: Path,
        work: Path,
        out_format: Optional[FileFormat] = None,
    ) -> Path:
        self.registry.require("ffmpeg")
        quality = max(1, min(100, quality))
        info = self.registry.ffmpeg.probe(input_path)
        vstream = info.primary_video
        if vstream is None:
            raise _no_video(input_path)
        vcodec = vstream.codec_name if vstream.codec_name in VIDEO_ENCODER_FOR_CODEC else "h264"
        astream = info.primary_audio
        acodec = astream.codec_name if astream else None
        opts = self.options
        t = quality / 100.0
        crf = int(round(lerp(opts.video_max_crf, opts.video_min_crf, t)))
        base_w = vstream.width or 1920
        width = int(round(lerp(0.4, 1.0, t) * base_w))
        width -= width % 2
        width = max(160, width)
        scale_width = None if width >= base_w else width
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry.ffmpeg.transcode_video(
            input_path,
            output_path,
            video_codec=vcodec,
            crf=crf,
            scale_width=scale_width,
            audio_codec=acodec,
        )
        return output_path


def _no_video(path: Path):
    from ..exceptions import MediaProcessingError

    return MediaProcessingError(f"No video stream found in {path.name}.")
