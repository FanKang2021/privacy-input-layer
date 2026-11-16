from pilayer.clipboard.watcher import html_to_text


def test_fragment_extraction():
    raw = (
        "Version:0.9\r\nStartHTML:0000000105\r\nEndHTML:0000000200\r\n"
        "<!--StartFragment--><b>call</b> 13800138000<!--EndFragment-->"
    )
    assert html_to_text(raw) == "call 13800138000"


def test_entities_and_bytes():
    raw = "<!--StartFragment-->a &amp; b&#33;<!--EndFragment-->".encode("utf-8")
    assert html_to_text(raw) == "a & b!"


def test_no_fragment_fallback():
    assert html_to_text("<p>plain 13800138000</p>") == "plain 13800138000"


def test_empty():
    assert html_to_text("") is None
    assert html_to_text(None) is None