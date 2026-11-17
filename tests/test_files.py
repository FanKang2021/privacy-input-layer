import sys

import pytest
from docx import Document
from openpyxl import Workbook, load_workbook

from pilayer.files import UnsupportedFile, mask_file, restore_file


def test_text_file_roundtrip(tmp_path, masker):
    src = tmp_path / "note.txt"
    src.write_text("张三 13800138000", encoding="utf-8")
    r = mask_file(src, masker)
    assert r.dst.name == "note.masked.txt"
    assert r.count == 2
    masked = r.dst.read_text(encoding="utf-8")
    assert "13800138000" not in masked
    back = restore_file(r.dst, masker)
    assert back.dst.read_text(encoding="utf-8") == "张三 13800138000"


def test_csv_masked(tmp_path, masker):
    src = tmp_path / "data.csv"
    src.write_text("name,phone\n张三,13800138000\n", encoding="utf-8")
    r = mask_file(src, masker)
    content = r.dst.read_text(encoding="utf-8")
    assert "13800138000" not in content
    assert "张三" not in content
    assert r.count == 2


def test_docx_paragraph_and_table(tmp_path, masker):
    src = tmp_path / "report.docx"
    doc = Document()
    doc.add_paragraph("联系人：张三，电话 13800138000")
    table = doc.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "邮箱 zhangsan@example.com"
    doc.save(str(src))

    r = mask_file(src, masker)
    assert r.count == 3
    masked_doc = Document(str(r.dst))
    all_text = "\n".join(p.text for p in masked_doc.paragraphs)
    all_text += "\n" + masked_doc.tables[0].cell(0, 0).text
    assert "13800138000" not in all_text
    assert "zhangsan@example.com" not in all_text

    back = restore_file(r.dst, masker)
    restored_doc = Document(str(back.dst))
    assert "13800138000" in restored_doc.paragraphs[0].text
    assert "zhangsan@example.com" in restored_doc.tables[0].cell(0, 0).text


def test_xlsx_strings_and_formula(tmp_path, masker):
    src = tmp_path / "sheet.xlsx"
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "张三 13800138000"
    ws["B1"] = 12345
    ws["C1"] = "=1+1"
    wb.save(str(src))

    r = mask_file(src, masker)
    assert r.count == 2
    out = load_workbook(str(r.dst)).active
    assert "13800138000" not in out["A1"].value
    assert out["B1"].value == 12345
    assert out["C1"].value == "=1+1"

    back = restore_file(r.dst, masker)
    assert load_workbook(str(back.dst)).active["A1"].value == "张三 13800138000"


def test_unsupported_ext(tmp_path, masker):
    src = tmp_path / "x.pdf"
    src.write_bytes(b"%PDF-1.4")
    with pytest.raises(UnsupportedFile):
        mask_file(src, masker)


def test_gbk_text_file(tmp_path, masker):
    src = tmp_path / "gbk.txt"
    src.write_bytes("张三 13800138000".encode("gbk"))
    r = mask_file(src, masker)
    assert r.count == 2

def test_pptx_mask_restore(tmp_path, masker):
    from pptx import Presentation
    from pptx.util import Inches
    src = tmp_path / "deck.pptx"
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Contact 13800138000"
    prs.save(str(src))
    r = mask_file(src, masker)
    assert r.count >= 1
    out = Presentation(str(r.dst))
    assert "13800138000" not in out.slides[0].shapes.title.text
    back = restore_file(r.dst, masker)
    assert "13800138000" in Presentation(str(back.dst)).slides[0].shapes.title.text


def test_odt_mask_restore(tmp_path, masker):
    import zipfile
    src = tmp_path / "doc.odt"
    content = ('<?xml version="1.0" encoding="UTF-8"?>'
               '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
               ' xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
               '<office:body><office:text><text:p>call 13800138000</text:p></office:text></office:body>'
               '</office:document-content>')
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("content.xml", content)
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text")
    r = mask_file(src, masker)
    assert r.count == 1
    with zipfile.ZipFile(r.dst) as z:
        assert b"13800138000" not in z.read("content.xml")
    back = restore_file(r.dst, masker)
    with zipfile.ZipFile(back.dst) as z:
        assert b"13800138000" in z.read("content.xml")


def test_legacy_doc_unsupported(tmp_path, masker):
    src = tmp_path / "old.doc"
    src.write_bytes(b"\xd0\xcf\x11\xe0legacy")
    with pytest.raises(UnsupportedFile):
        mask_file(src, masker)


def test_image_mask_irreversible_restore(tmp_path, masker):
    from PIL import Image
    src = tmp_path / "pic.png"
    Image.new("RGB", (10, 10), "white").save(src)
    with pytest.raises(UnsupportedFile):
        restore_file(src, masker)


@pytest.mark.skipif(sys.platform != "win32", reason="needs Windows CJK font")
def test_image_and_pdf_ocr_mask(tmp_path, masker):
    import io
    from PIL import Image, ImageDraw, ImageFont
    from pilayer.engine.image import ImageMasker
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 36)
    img = Image.new("RGB", (700, 120), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 30), "电话 13800138000", font=font, fill="black")
    png = tmp_path / "id.png"
    img.save(png)
    r = mask_file(png, masker)
    assert r.count >= 1
    im = ImageMasker(masker.rules_cfg, masker.keywords)
    with Image.open(r.dst) as masked:
        _, n = im.mask(masked)
    assert n == 0  # 打码后 OCR 不再识别敏感信息
    import img2pdf
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(img2pdf.convert([str(png)]))
    rp = mask_file(pdf, masker)
    assert rp.count >= 1
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(str(rp.dst))
    page_img = doc[0].render(scale=2.0).to_pil()
    doc.close()
    _, n2 = im.mask(page_img)
    assert n2 == 0
