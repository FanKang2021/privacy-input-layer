import pytest

pytest.importorskip("win32clipboard")

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

def test_html_only_clipboard_normalized(tmp_path, monkeypatch):
    import win32clipboard
    import win32con
    from pilayer.clipboard.watcher import ClipboardWatcher
    from pilayer.engine import MappingStore, TextMasker
    from pilayer.engine.image import ImageMasker
    html = ("Version:0.9\r\n<!--StartFragment--><div>line1 passwd: \"S1\"</div>"
            "<div>line2 plain</div><!--EndFragment-->")
    state = {"text": None}
    monkeypatch.setattr(win32clipboard, "OpenClipboard", lambda: True)
    monkeypatch.setattr(win32clipboard, "CloseClipboard", lambda: None)
    monkeypatch.setattr(win32clipboard, "EmptyClipboard", lambda: None)
    monkeypatch.setattr(win32clipboard, "SetClipboardData", lambda f, d: state.update(text=d))
    monkeypatch.setattr(win32clipboard, "GetClipboardData", lambda f: html)
    monkeypatch.setattr(win32clipboard, "IsClipboardFormatAvailable",
                        lambda f: f == __import__("pilayer.clipboard.watcher", fromlist=["CF_HTML"]).CF_HTML)
    monkeypatch.setattr(win32clipboard, "GetClipboardSequenceNumber", lambda: 1)
    store = MappingStore(tmp_path / "m.db")
    w = ClipboardWatcher(TextMasker(store, {"phone": True}, []), ImageMasker({}),
                         {"mode": "focus"}, tmp_path)
    w._normalize_html_clipboard()
    assert state["text"] == 'line1 passwd: "S1"\nline2 plain'
