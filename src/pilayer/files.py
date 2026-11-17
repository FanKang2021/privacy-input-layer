"""文件脱敏副本：txt/csv/md/json/log/docx/xlsx -> <name>.masked.<ext>。

pdf 不在首版范围（见 README 路线图）。
"""

from dataclasses import dataclass
from pathlib import Path

from .engine import TextMasker

TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".log"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
ODF_EXTS = {".odt", ".ods", ".odp"}
SUPPORTED_EXTS = TEXT_EXTS | IMAGE_EXTS | ODF_EXTS | {".docx", ".xlsx", ".pptx", ".pdf"}
LEGACY_EXTS = {".doc", ".xls", ".ppt"}


class UnsupportedFile(Exception):
    pass


@dataclass
class FileResult:
    src: Path
    dst: Path
    count: int


def masked_path(src: Path, suffix: str = ".masked") -> Path:
    return src.with_name(src.stem + suffix + src.suffix)


def _read_text(src: Path) -> str:
    raw = src.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _iter_docx_paragraphs(doc):
    for p in doc.paragraphs:
        yield p
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs
                for nested in cell.tables:
                    for nrow in nested.rows:
                        for ncell in nrow.cells:
                            yield from ncell.paragraphs
    for section in doc.sections:
        for part in (section.header, section.footer):
            if part is not None:
                yield from part.paragraphs


def _transform_paragraph(p, transform) -> int:
    """段落级处理：PII 可能跨 run 被拆开，整段合并后变换再写回首个 run。"""
    text = "".join(run.text for run in p.runs)
    if not text:
        return 0
    new_text, count = transform(text)
    if count == 0 or new_text == text:
        return 0
    for i, run in enumerate(p.runs):
        run.text = new_text if i == 0 else ""
    return count


def _mask_transform(masker: TextMasker):
    def transform(text: str):
        r = masker.mask(text)
        return r.text, r.count
    return transform


def _restore_transform(masker: TextMasker):
    def transform(text: str):
        r = masker.restore(text)
        return r.text, r.count
    return transform


def _mask_docx(src: Path, dst: Path, masker: TextMasker) -> int:
    from docx import Document

    doc = Document(str(src))
    count = 0
    for p in _iter_docx_paragraphs(doc):
        count += _transform_paragraph(p, _mask_transform(masker))
    doc.save(str(dst))
    return count


def _restore_docx(src: Path, dst: Path, masker: TextMasker) -> int:
    from docx import Document

    doc = Document(str(src))
    count = 0
    for p in _iter_docx_paragraphs(doc):
        count += _transform_paragraph(p, _restore_transform(masker))
    doc.save(str(dst))
    return count


def _transform_xlsx(src: Path, dst: Path, transform) -> int:
    from openpyxl import load_workbook

    wb = load_workbook(str(src))
    count = 0
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.data_type == "s" and isinstance(cell.value, str):
                    new_text, n = transform(cell.value)
                    if n:
                        cell.value = new_text
                        count += n
    wb.save(str(dst))
    return count


def mask_file(src: str | Path, masker: TextMasker, suffix: str = ".masked", dst: str | Path | None = None) -> FileResult:
    src = Path(src)
    ext = src.suffix.lower()
    if ext not in SUPPORTED_EXTS:
        if ext in LEGACY_EXTS:
            raise UnsupportedFile(
                f"legacy binary {ext} not supported; save as "
                f"{ {'.doc': '.docx', '.xls': '.xlsx', '.ppt': '.pptx'}[ext] } first"
            )
        raise UnsupportedFile(f"Unsupported {ext} file (supported: {', '.join(sorted(SUPPORTED_EXTS))})")
    dst = Path(dst) if dst else masked_path(src, suffix)
    if ext in TEXT_EXTS:
        result = masker.mask(_read_text(src))
        dst.write_text(result.text, encoding="utf-8")
        count = result.count
    elif ext in IMAGE_EXTS:
        count = _mask_image_file(src, dst, masker)
    elif ext == ".pdf":
        from .pdfmask import mask_pdf
        count = mask_pdf(src, dst, masker)
    elif ext == ".docx":
        count = _mask_docx(src, dst, masker)
    elif ext == ".pptx":
        count = _mask_pptx(src, dst, masker)
    elif ext in ODF_EXTS:
        count = _mask_odf(src, dst, masker)
    else:
        count = _transform_xlsx(src, dst, _mask_transform(masker))
    return FileResult(src, dst, count)


def _mask_image_file(src: Path, dst: Path, masker: TextMasker) -> int:
    from PIL import Image
    from .engine.image import ImageMasker
    im = ImageMasker(masker.rules_cfg, masker.keywords)
    with Image.open(src) as img:
        masked, count = im.mask(img)
        masked.save(dst)
    return count


def restore_file(src: str | Path, masker: TextMasker, dst: str | Path | None = None) -> FileResult:
    src = Path(src)
    ext = src.suffix.lower()
    if ext in IMAGE_EXTS or ext == ".pdf":
        raise UnsupportedFile(f"{ext} masking is irreversible (pixels destroyed); no restore")
    if ext not in SUPPORTED_EXTS:
        raise UnsupportedFile(f"Unsupported {ext} file")
    dst = Path(dst) if dst else src.with_name(src.stem + ".restored" + ext)
    if ext in TEXT_EXTS:
        result = masker.restore(_read_text(src))
        dst.write_text(result.text, encoding="utf-8")
        count = result.count
    elif ext == ".docx":
        count = _restore_docx(src, dst, masker)
    elif ext == ".pptx":
        count = _restore_pptx(src, dst, masker)
    elif ext in ODF_EXTS:
        count = _restore_odf(src, dst, masker)
    else:
        count = _transform_xlsx(src, dst, _restore_transform(masker))
    return FileResult(src, dst, count)


def _iter_pptx_paragraphs(prs):
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                for p in shape.text_frame.paragraphs:
                    yield p
            if shape.has_table:
                for row in shape.table.rows:
                    for cell in row.cells:
                        for p in cell.text_frame.paragraphs:
                            yield p


def _mask_pptx(src: Path, dst: Path, masker: TextMasker) -> int:
    from pptx import Presentation
    prs = Presentation(str(src))
    count = 0
    for p in _iter_pptx_paragraphs(prs):
        count += _transform_paragraph(p, _mask_transform(masker))
    prs.save(str(dst))
    return count


def _restore_pptx(src: Path, dst: Path, masker: TextMasker) -> int:
    from pptx import Presentation
    prs = Presentation(str(src))
    count = 0
    for p in _iter_pptx_paragraphs(prs):
        count += _transform_paragraph(p, _restore_transform(masker))
    prs.save(str(dst))
    return count


def _transform_odf(src: Path, dst: Path, transform) -> int:
    import zipfile
    import xml.etree.ElementTree as ET
    count = 0
    with zipfile.ZipFile(src) as zin:
        names = zin.namelist()
        data = {n: zin.read(n) for n in names}
    root = ET.fromstring(data["content.xml"])
    for el in root.iter():
        if el.text and el.text.strip():
            new, n = transform(el.text)
            if n:
                el.text = new
                count += n
        if el.tail and el.tail.strip():
            new, n = transform(el.tail)
            if n:
                el.tail = new
                count += n
    data["content.xml"] = ET.tostring(root, encoding="UTF-8", xml_declaration=True)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for n in names:
            zout.writestr(n, data[n])
    return count


def _mask_odf(src: Path, dst: Path, masker: TextMasker) -> int:
    return _transform_odf(src, dst, _mask_transform(masker))


def _restore_odf(src: Path, dst: Path, masker: TextMasker) -> int:
    return _transform_odf(src, dst, _restore_transform(masker))