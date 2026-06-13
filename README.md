# resize-kit

**Enterprise multi-format lossy compressor with precise size targeting.**

resize-kit compresses images, audio, video, Office documents (DOC/DOCX/PPT/PPTX)
and PDFs to a target you control — a ratio, an exact size, or a `min ≤ size ≤ max`
band — and can even *grow* a file to a target size losslessly. It is the reference
implementation of the design in [`DESIGN.md`](./DESIGN.md).

It ships with a **CLI** (`resize-kit`) and a **PyQt5 desktop GUI** (`resize-kit-gui`).

---

## Highlights

- **Four target modes** — shrink to a *ratio*, land in a *size band*, hit an *exact*
  size (±tolerance), or *inflate* to a size with zero quality change.
- **Precise to the byte.** A binary search drives the encoder under the ceiling;
  format-legal padding lifts the result to the floor. `EXACT` lands within a
  tolerance you choose (default ±1 KiB).
- **Never emits a corrupt file.** An unreachable target is reported as a first-class
  error carrying the achievable bounds — not a broken output.
- **Container fidelity.** Embedded media is rewritten under its *original name and
  format*, so DOCX/PPTX relationships and `[Content_Types].xml` need no edits.
- **Transparency-safe images.** Alpha is always preserved (palette quantization by
  default, channel-separation method available).
- **Lossless inflate.** Growing a file injects decoder-ignored bytes; pixels and
  samples stay bit-for-bit identical.

---

## Architecture

Four layers, dependencies pointing strictly downward (see `DESIGN.md` §2):

```
 L3  Dispatcher          detect format · isolate workspace · route · clean up
       │
 L2  Container handlers  OOXML (docx/pptx) · legacy office (doc/ppt) · PDF
       │
 L1  Atomic compressors  Image · Audio · Video      <- reused by every L2 handler
       │
 L0  Tool adapters       ffmpeg · LibreOffice · Ghostscript · pngquant
       └──────────────── SizeBandController + padding  (cross-cutting) ──────────┘
```

The `SizeBandController` (binary-search-for-the-ceiling + pad-for-the-floor) and the
format-legal padding carriers are shared by every atomic compressor *and* by the
container handlers, which converge the whole document by searching a single per-asset
quality knob.

Source layout:

```
src/resize_kit/
  core/
    adapters/   L0 — ffmpeg, libreoffice, ghostscript, pngquant, tool registry
    atomic/     L1 — image, audio, video compressors
    handlers/   L2 — ooxml, legacy_office, pdf
    sizing/     controller + padding (cross-cutting)
    dispatcher.py, detect.py, workspace.py, models.py, …
  cli.py        command-line interface
  gui/          PyQt5 desktop app
```

---

## Installation

resize-kit uses [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev          # create .venv and install everything (incl. dev tools)
uv run resize-kit doctor     # check external tools
```

### External tools

| Tool          | Required | Used for                                            |
|---------------|:--------:|-----------------------------------------------------|
| **ffmpeg**    | yes      | audio & video (re)compression and probing           |
| **LibreOffice** (`soffice`) | optional | legacy DOC/PPT ↔ DOCX/PPTX conversion |
| **Ghostscript** (`gs`) | optional | alternative PDF image-downsampling backend |
| **pngquant**  | optional | superior PNG palette quantization                   |

`resize-kit doctor` reports what is available. Image/PDF work runs without the
optional tools (native fallbacks); audio/video need ffmpeg; legacy DOC/PPT need
LibreOffice.

---

## CLI usage

```bash
# Shrink a photo into a 150–200 KiB band
resize-kit compress photo.jpg --min 150KB --max 200KB -o photo.small.jpg

# Compress to half the original size
resize-kit compress slides.pptx --ratio 0.5

# Hit an exact size (±50 KiB tolerance) for an upload limit
resize-kit compress clip.mp4 --exact 8MB --tolerance 50KB

# Flatten a scanned PDF to images for maximum compression
resize-kit compress scan.pdf --max 1MB --pdf-mode rasterize

# Grow an image to exactly 900 KiB without touching a pixel
resize-kit inflate icon.png --to 900KB

# Inspect what resize-kit sees
resize-kit probe movie.mkv
resize-kit doctor
```

Sizes accept `B`, `KB`/`KiB`, `MB`/`MiB`, `GB`/`GiB` (KB == KiB == 1024).

**Exit codes:** `0` landed in band · `2` target unreachable · `3` finished but
outside band · `1` error.

### Key options

| Option            | Meaning                                                        |
|-------------------|----------------------------------------------------------------|
| `--ratio R`       | shrink to fraction `R` of the original (0–1)                    |
| `--max / --min`   | size-band bounds (either may be omitted)                        |
| `--exact S`       | exact target size, with `--tolerance`                          |
| `--inflate S`     | grow to size `S` via lossless padding                          |
| `--pdf-mode`      | `multimedia` (keep text/vectors) or `rasterize` (image-only)   |
| `--png-alpha`     | `quantize` (default) or `channel_split` for transparent PNGs   |
| `--keep-ooxml`    | for DOC/PPT, output DOCX/PPTX (safer, precise sizing)          |
| `--no-downscale`  | forbid resolution / sample-rate reduction                      |
| `--no-pad`        | forbid padding to reach the lower bound                        |

---

## GUI

```bash
uv run resize-kit-gui
```

Pick a file (drag-and-drop or browse), choose a target mode, tweak options, and
press **Compress**. The job runs on a background thread with live progress; results
show before/after sizes, the per-asset breakdown for containers, and a log.

---

## How precise sizing works (DESIGN.md §6)

```
target: min ≤ size ≤ max
  1. binary-search the quality knob for the highest quality with size ≤ max   (ceiling)
  2. if that result ≥ min  → done
     else                  → add format-legal padding up to the floor          (floor)
  3. if even max compression > max and downscaling is allowed → downscale, retry
     else → report the unreachable band with achievable bounds
```

**Padding carriers** (bytes a decoder ignores) — exact to the byte:

| Format        | Carrier                                  |
|---------------|------------------------------------------|
| JPEG          | `COM` comment segments (chained)         |
| PNG           | private ancillary `rkPd` chunk           |
| MP4/MOV/M4A   | top-level `free` box                     |
| MP3           | ID3v2 tag padding                        |
| WAV           | private RIFF sub-chunk                   |
| PDF           | trailing comment after `%%EOF`           |
| DOCX/PPTX/XLSX| ZIP end-of-archive comment               |

The same mechanism powers `inflate` (DESIGN.md §7): the visible content is unchanged,
only the byte count grows.

---

## Supported formats

| Input              | Path                                                      |
|--------------------|-----------------------------------------------------------|
| JPEG/PNG/BMP/GIF/TIFF/WEBP | lossy re-encode; alpha preserved                  |
| MP3/AAC/M4A/OGG/OPUS/FLAC/WAV | ffmpeg, same codec, bitrate/quality knob       |
| MP4/MKV/MOV/WEBM/AVI | ffmpeg, same container, CRF knob                        |
| DOCX/PPTX/XLSX     | unzip → recompress media → repack (zero structural change)|
| DOC/PPT            | LibreOffice → DOCX/PPTX → compress → convert back          |
| PDF                | multimedia (keep text/vectors) **or** rasterize (image-only)|

---

## Development

```bash
uv run pytest                      # full suite (external tests auto-skip if a tool is absent)
uv run pytest -m "not external"    # offline, pure-Python subset
python assets/fetch_samples.py     # download public samples and run the engine on them
```

The test suite is hermetic: fixtures are generated on the fly (no network).
`assets/fetch_samples.py` is a separate integration demo against real public files.

---

## Design notes & limitations

- **DOC/PPT round-trips** through LibreOffice can drift layout slightly and exact byte
  targeting is approximate (OLE2 has no safe padding carrier). Use `--keep-ooxml` for
  precise, lossless-structure output.
- **Container size search** re-encodes every embedded asset per search step, so very
  large media-heavy documents take longer (no concurrency by design).
- **pngquant** is preferred for PNGs when installed; otherwise Pillow's alpha-aware
  quantizer is used.
- ZIP floor padding is capped at the 64 KiB archive-comment limit.

See [`DESIGN.md`](./DESIGN.md) for the full design rationale.
