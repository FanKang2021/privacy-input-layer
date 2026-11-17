"""PDF masking: render pages -> OCR pixel-mask -> reassemble image-only PDF.

License-safe pipeline (pypdfium2 + img2pdf); avoids PyMuPDF AGPL.
Trade-off: output PDF loses its text layer (becomes image-based) — documented.
Scanned and text PDFs alike are covered uniformly.
"""

from pathlib import Path


def mask_pdf(src: Path, dst: Path, masker) -> int:
    try:
        import pypdfium2 as pdfium
        import img2pdf
        from PIL import Image
    except ImportError as e:
        from .files import UnsupportedFile
        raise UnsupportedFile("PDF masking requires [image] extras: pip install privacy-input-layer[image]") from e
    from .engine.image import ImageMasker

    im = ImageMasker(masker.rules_cfg, masker.keywords)
    try:
        pdf = pdfium.PdfDocument(str(src))
    except Exception as e:
        from .files import UnsupportedFile
        raise UnsupportedFile(f"invalid or unreadable PDF: {e}") from e
    masked_pages = []
    count = 0
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            bitmap = page.render(scale=2.0)
            pil = bitmap.to_pil()
            masked, n = im.mask(pil)
            count += n
            masked_pages.append(masked.convert("RGB"))
    finally:
        pdf.close()
    if not masked_pages:
        from .files import UnsupportedFile
        raise UnsupportedFile("empty PDF")
    dst.write_bytes(img2pdf.convert([_pil_to_bytes(p) for p in masked_pages]))
    return count


def _pil_to_bytes(img) -> bytes:
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()