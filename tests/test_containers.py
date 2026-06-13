from __future__ import annotations

import zipfile

import fitz
import pytest

from resize_kit.core.detect import detect_format
from resize_kit.core.handlers.legacy_office import LegacyOfficeHandler
from resize_kit.core.handlers.ooxml import OOXMLHandler
from resize_kit.core.handlers.pdf import PdfHandler
from resize_kit.core.media_type import FileFormat
from resize_kit.core.models import CompressionTarget, PdfMode

from .conftest import requires_soffice


def test_ooxml_ratio_preserves_structure(make_docx, tmp_path):
    src = make_docx()
    with zipfile.ZipFile(src) as z:
        names = z.namelist()
    out = tmp_path / "out.docx"
    res = OOXMLHandler().handle(
        src, CompressionTarget.ratio_of(0.5), output_path=out, work=tmp_path / "w"
    )
    assert res.final_bytes <= src.stat().st_size * 0.5
    with zipfile.ZipFile(out) as z:
        assert z.namelist() == names  # zero structural change
        assert z.testzip() is None


def test_ooxml_band_with_floor_padding(make_docx, tmp_path):
    src = make_docx()
    o = src.stat().st_size
    out = tmp_path / "out.docx"
    res = OOXMLHandler().handle(
        src, CompressionTarget.band(int(o * 0.6), int(o * 0.7)), output_path=out, work=tmp_path / "w"
    )
    assert int(o * 0.6) <= res.final_bytes <= int(o * 0.7) and res.landed_in_band
    with zipfile.ZipFile(out) as z:
        assert z.testzip() is None


def test_pdf_multimedia_keeps_text(make_pdf, tmp_path):
    src = make_pdf()
    out = tmp_path / "out.pdf"
    res = PdfHandler().handle(
        src, CompressionTarget.ratio_of(0.5), output_path=out, work=tmp_path / "w",
        pdf_mode=PdfMode.MULTIMEDIA,
    )
    assert res.final_bytes < src.stat().st_size
    doc = fitz.open(out)
    text = doc[0].get_text()
    doc.close()
    assert "Vector text" in text


def test_pdf_rasterize_drops_text_and_hits_band(make_pdf, tmp_path):
    src = make_pdf()
    out = tmp_path / "out.pdf"
    res = PdfHandler().handle(
        src, CompressionTarget.band(20 * 1024, 45 * 1024), output_path=out, work=tmp_path / "w",
        pdf_mode=PdfMode.RASTERIZE,
    )
    assert 20 * 1024 <= res.final_bytes <= 45 * 1024 and res.landed_in_band
    doc = fitz.open(out)
    text = doc[0].get_text().strip()
    doc.close()
    assert text == ""


@pytest.mark.external
@requires_soffice
def test_legacy_doc_roundtrip(legacy_doc, tmp_path):
    assert detect_format(legacy_doc) is FileFormat.DOC
    out = tmp_path / "out.doc"
    res = LegacyOfficeHandler().handle(
        legacy_doc, CompressionTarget.ratio_of(0.7), output_path=out, work=tmp_path / "w",
        fmt=FileFormat.DOC,
    )
    assert detect_format(out) is FileFormat.DOC
    assert res.final_bytes > 0


@pytest.mark.external
@requires_soffice
def test_legacy_keep_ooxml(legacy_doc, tmp_path):
    out = tmp_path / "out.docx"
    LegacyOfficeHandler().handle(
        legacy_doc, CompressionTarget.ratio_of(0.7), output_path=out, work=tmp_path / "w",
        fmt=FileFormat.DOC, keep_ooxml=True,
    )
    assert detect_format(out) is FileFormat.DOCX
