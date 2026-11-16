def test_mask_and_restore_roundtrip(masker):
    text = "张三的手机 13800138000，邮箱 zhangsan@example.com"
    r = masker.mask(text)
    assert r.count == 3
    assert "13800138000" not in r.text
    assert "张三" not in r.text
    back = masker.restore(r.text)
    assert back.text == text
    assert back.count == 3
    assert back.missing == []


def test_same_original_reuses_placeholder(masker):
    a = masker.mask("电话 13800138000")
    b = masker.mask("再发一次 13800138000")
    assert a.text.split()[-1] == b.text.split()[-1]


def test_different_originals_get_different_placeholders(masker):
    a = masker.mask("13800138000")
    b = masker.mask("13900139000")
    assert a.text != b.text


def test_no_pii_untouched(masker):
    r = masker.mask("今天天气不错")
    assert r.count == 0
    assert r.text == "今天天气不错"


def test_restore_missing_mapping(masker):
    r = masker.restore("未知占位符 [PHONE_999]")
    assert r.count == 0
    assert r.missing == ["[PHONE_999]"]
    assert r.text == "未知占位符 [PHONE_999]"


def test_store_persists(tmp_path):
    from pilayer.engine import MappingStore, TextMasker

    cfg = {"phone": True}
    s1 = MappingStore(tmp_path / "m.db")
    m1 = TextMasker(s1, cfg)
    masked = m1.mask("13800138000").text
    s1.close()
    s2 = MappingStore(tmp_path / "m.db")
    m2 = TextMasker(s2, cfg)
    assert m2.restore(masked).text == "13800138000"
    s2.close()


def test_stats(masker):
    masker.mask("13800138000 a@b.co")
    s = masker.store.stats()
    assert s["total"] == 2
    assert s["by_kind"]["PHONE"] == 1