"""Shared pytest fixtures.

Tests are hermetic: media fixtures are generated on the fly (deterministic, no
network). Tests that need an external binary are marked ``external`` and skipped
automatically when the tool is missing, so the suite is green on any machine.
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from resize_kit.core.adapters.registry import default_registry


# --- tool gating --------------------------------------------------------------


def _have(tool: str) -> bool:
    return shutil.which(tool) is not None


requires_ffmpeg = pytest.mark.skipif(not _have("ffmpeg"), reason="ffmpeg not installed")
requires_soffice = pytest.mark.skipif(
    not (_have("soffice") or _have("libreoffice")), reason="LibreOffice not installed"
)


@pytest.fixture(scope="session")
def registry():
    return default_registry()


# --- image fixtures -----------------------------------------------------------


def _gradient(w: int, h: int, seed: int = 0) -> Image.Image:
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = ((x * 7 + y * 3 + seed) % 256, (x * 3 + seed) % 256, (y * 5) % 256)
    return img


@pytest.fixture
def make_jpeg(tmp_path):
    def _make(name="img.jpg", w=640, h=480, quality=95) -> Path:
        p = tmp_path / name
        _gradient(w, h).save(p, "JPEG", quality=quality)
        return p

    return _make


@pytest.fixture
def make_png_alpha(tmp_path):
    def _make(name="img.png", w=400, h=400) -> Path:
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = img.load()
        cx, cy, r = w // 2, h // 2, min(w, h) // 3
        for y in range(h):
            for x in range(w):
                if (x - cx) ** 2 + (y - cy) ** 2 < r * r:
                    d[x, y] = (x % 256, y % 256, 128, 255)
        p = tmp_path / name
        img.save(p, "PNG")
        return p

    return _make


# --- audio / video fixtures (ffmpeg) -----------------------------------------


@pytest.fixture
def make_mp3(tmp_path):
    def _make(name="a.mp3", duration=4, bitrate="256k") -> Path:
        p = tmp_path / name
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
             "-c:a", "libmp3lame", "-b:a", bitrate, str(p)],
            capture_output=True, check=True,
        )
        return p

    return _make


@pytest.fixture
def make_mp4(tmp_path):
    def _make(name="v.mp4", size="640x480", rate=15, duration=3) -> Path:
        p = tmp_path / name
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i",
             f"testsrc=size={size}:rate={rate}:duration={duration}",
             "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(p)],
            capture_output=True, check=True,
        )
        return p

    return _make


# --- container fixtures -------------------------------------------------------


@pytest.fixture
def make_docx(tmp_path):
    def _make(name="doc.docx") -> Path:
        jpg = BytesIO(); _gradient(900, 700, 10).save(jpg, "JPEG", quality=95)
        png = BytesIO(); _gradient(500, 500, 99).convert("RGBA").save(png, "PNG")
        ct = (
            '<?xml version="1.0"?><Types '
            'xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="jpg" ContentType="image/jpeg"/>'
            '<Default Extension="png" ContentType="image/png"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.'
            'wordprocessingml.document.main+xml"/></Types>'
        )
        # A minimal but *valid* WordprocessingML body so LibreOffice can open it.
        document = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:body>'
            '<w:p><w:r><w:t>resize-kit test document</w:t></w:r></w:p>'
            '<w:sectPr/></w:body></w:document>'
        )
        p = tmp_path / name
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", ct)
            z.writestr("word/document.xml", document)
            z.writestr("word/media/image1.jpg", jpg.getvalue())
            z.writestr("word/media/image2.png", png.getvalue())
        return p

    return _make


@pytest.fixture(scope="session")
def legacy_doc(tmp_path_factory):
    """A real legacy .doc produced by LibreOffice (built once per session)."""
    if not (_have("soffice") or _have("libreoffice")):
        pytest.skip("LibreOffice not installed")
    base = tmp_path_factory.mktemp("legacy")
    docx = base / "seed.docx"
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body>'
        '<w:p><w:r><w:t>resize-kit legacy round-trip test</w:t></w:r></w:p>'
        '<w:sectPr/></w:body></w:document>'
    )
    ct = (
        '<?xml version="1.0"?><Types '
        'xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.'
        'wordprocessingml.document.main+xml"/></Types>'
    )
    root_rels = (
        '<?xml version="1.0"?><Relationships '
        'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>'
    )
    with zipfile.ZipFile(docx, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("word/document.xml", document)
    profile = base / "profile"
    subprocess.run(
        ["soffice", "--headless", f"-env:UserInstallation=file://{profile}",
         "--convert-to", "doc:MS Word 97", "--outdir", str(base), str(docx)],
        capture_output=True, check=True, timeout=180,
    )
    doc = base / "seed.doc"
    if not doc.exists():
        pytest.skip("LibreOffice did not produce a .doc")
    return doc


@pytest.fixture
def make_pdf(tmp_path):
    def _make(name="doc.pdf", pages=2) -> Path:
        import fitz

        doc = fitz.open()
        for i in range(pages):
            page = doc.new_page(width=600, height=800)
            jb = BytesIO(); _gradient(800, 600, i * 30).save(jb, "JPEG", quality=92)
            page.insert_image(fitz.Rect(20, 20, 580, 440), stream=jb.getvalue())
            page.insert_text((50, 500), f"Vector text page {i}", fontsize=20)
        p = tmp_path / name
        doc.save(p, garbage=4, deflate=True)
        doc.close()
        return p

    return _make
