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