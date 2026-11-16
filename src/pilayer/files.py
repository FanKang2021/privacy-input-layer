"""文件脱敏副本：txt/csv/md/json/log/docx/xlsx -> <name>.masked.<ext>。

pdf 不在首版范围（见 README 路线图）。
"""

from dataclasses import dataclass
from pathlib import Path

from .engine import TextMasker

TEXT_EXTS = {".txt", ".md", ".csv", ".json", ".log"}
SUPPORTED_EXTS = TEXT_EXTS | {".docx", ".xlsx"}


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
        raise UnsupportedFile(f"暂不支持 {ext} 文件（支持：{', '.join(sorted(SUPPORTED_EXTS))}）")
    dst = Path(dst) if dst else masked_path(src, suffix)
    if ext in TEXT_EXTS:
        result = masker.mask(_read_text(src))
        dst.write_text(result.text, encoding="utf-8")
        count = result.count
    elif ext == ".docx":
        count = _mask_docx(src, dst, masker)
    else:
        count = _transform_xlsx(src, dst, _mask_transform(masker))
    return FileResult(src, dst, count)


def restore_file(src: str | Path, masker: TextMasker, dst: str | Path | None = None) -> FileResult:
    src = Path(src)
    ext = src.suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise UnsupportedFile(f"暂不支持 {ext} 文件")
    dst = Path(dst) if dst else src.with_name(src.stem + ".restored" + ext)
    if ext in TEXT_EXTS:
        result = masker.restore(_read_text(src))
        dst.write_text(result.text, encoding="utf-8")
        count = result.count
    elif ext == ".docx":
        count = _restore_docx(src, dst, masker)
    else:
        count = _transform_xlsx(src, dst, _restore_transform(masker))
    return FileResult(src, dst, count)