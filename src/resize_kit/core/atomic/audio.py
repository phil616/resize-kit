"""AudioCompressor (Layer 1) — DESIGN.md §4.2.

Lossy only; the output encoding format always equals the input (mp3->mp3,
aac->aac, …). The primary convergence knob is **bitrate**; when bitrate alone
cannot reach the ceiling, the downscale ladder drops to mono and then lower
sample rates.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ...logging_config import get_logger
from ..adapters.ffmpeg import AUDIO_ENCODER_FOR_CODEC
from ..media_type import FileFormat, MediaClass, format_from_extension
from ..models import CompressionResult, CompressionTarget
from .base import AtomicCompressor, ProgressFn, lerp

log = get_logger(__name__)


class AudioCompressor(AtomicCompressor):
    media_class = MediaClass.AUDIO

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
        stream = info.primary_audio
        if stream is None:
            raise _no_audio(input_path)
        codec = stream.codec_name
        if codec not in AUDIO_ENCODER_FOR_CODEC:
            codec = _codec_for_format(fmt) or codec

        orig_kbps = _estimate_kbps(stream.bit_rate, info.overall_bit_rate, original_bytes, info.duration)
        resolved = target.resolve(original_bytes)

        opts = self.options
        knob_max = max(orig_kbps, opts.audio_min_bitrate_kbps + 1)
        knob_min = min(opts.audio_min_bitrate_kbps, knob_max)

        state = {
            "sample_rate": stream.sample_rate,
            "channels": stream.channels or 2,
        }

        def encode(bitrate: int) -> Path:
            cand = work / f"cand_{bitrate}_{state['sample_rate']}_{state['channels']}.{ext}"
            self.registry.ffmpeg.transcode_audio(
                input_path,
                cand,
                codec=codec,
                bitrate_kbps=bitrate,
                sample_rate=state["sample_rate"],
                channels=state["channels"],
            )
            return cand

        def downscale() -> bool:
            if state["channels"] and state["channels"] > 1:
                state["channels"] = 1
                return True
            sr = state["sample_rate"] or 44100
            for nxt in (32000, 22050, 16000, 11025, 8000):
                if sr > nxt:
                    state["sample_rate"] = nxt
                    return True
            return False

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
        if state["channels"] == 1 and (stream.channels or 2) > 1:
            note_bits.append("downmixed to mono")
        if state["sample_rate"] and stream.sample_rate and state["sample_rate"] < stream.sample_rate:
            note_bits.append(f"resampled to {state['sample_rate']} Hz")
        if conv.note:
            note_bits.append(conv.note)

        return CompressionResult(
            output_path=str(output_path),
            original_bytes=original_bytes,
            final_bytes=output_path.stat().st_size,
            landed_in_band=conv.landed_in_band,
            media_class=MediaClass.AUDIO,
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
        fmt = out_format or format_from_extension(input_path.suffix)
        info = self.registry.ffmpeg.probe(input_path)
        stream = info.primary_audio
        if stream is None:
            raise _no_audio(input_path)
        codec = stream.codec_name
        if codec not in AUDIO_ENCODER_FOR_CODEC:
            codec = _codec_for_format(fmt) or codec
        orig_kbps = _estimate_kbps(
            stream.bit_rate, info.overall_bit_rate, input_path.stat().st_size, info.duration
        )
        t = quality / 100.0
        bitrate = int(round(lerp(self.options.audio_min_bitrate_kbps, orig_kbps, t)))
        bitrate = max(self.options.audio_min_bitrate_kbps, bitrate)
        channels = 1 if quality < 25 and (stream.channels or 2) > 1 else stream.channels
        sr = stream.sample_rate
        if sr and quality < 20:
            sr = min(sr, 16000)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry.ffmpeg.transcode_audio(
            input_path,
            output_path,
            codec=codec,
            bitrate_kbps=bitrate,
            sample_rate=sr,
            channels=channels,
        )
        return output_path


def _estimate_kbps(
    stream_br: Optional[int],
    overall_br: Optional[int],
    size_bytes: int,
    duration: float,
) -> int:
    if stream_br:
        return max(8, stream_br // 1000)
    if overall_br:
        return max(8, overall_br // 1000)
    if duration > 0:
        return max(8, int((size_bytes * 8) / duration / 1000))
    return 192


def _codec_for_format(fmt: FileFormat) -> Optional[str]:
    return {
        FileFormat.MP3: "mp3",
        FileFormat.AAC: "aac",
        FileFormat.M4A: "aac",
        FileFormat.OGG: "vorbis",
        FileFormat.OPUS: "opus",
        FileFormat.FLAC: "flac",
        FileFormat.WAV: "pcm_s16le",
    }.get(fmt)


def _no_audio(path: Path):
    from ..exceptions import MediaProcessingError

    return MediaProcessingError(f"No audio stream found in {path.name}.")
