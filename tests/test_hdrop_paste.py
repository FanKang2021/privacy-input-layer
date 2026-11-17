"""文件粘贴竞态回归：handle_paste 必须在补发键前同步完成 HDROP 替换。"""

from pathlib import Path

import pytest

pytest.importorskip("win32clipboard")

import win32clipboard
import win32con

from pilayer.clipboard.watcher import ClipboardWatcher
from pilayer.engine import MappingStore, TextMasker
from pilayer.engine.image import ImageMasker


def make_watcher(tmp_path, monkeypatch, paths):
    state = {"hdrop": tuple(paths), "seq": 0}
    monkeypatch.setattr(win32clipboard, "OpenClipboard", lambda: True)
    monkeypatch.setattr(win32clipboard, "CloseClipboard", lambda: None)
    monkeypatch.setattr(win32clipboard, "EmptyClipboard", lambda: None)

    def set_cb(fmt, data):
        if fmt == win32con.CF_HDROP:
            payload = data[20:].decode("utf-16-le")
            state["hdrop"] = tuple(p for p in payload.split("\0") if p)
            state["seq"] += 1

    monkeypatch.setattr(win32clipboard, "SetClipboardData", set_cb)
    monkeypatch.setattr(win32clipboard, "GetClipboardData", lambda fmt: state["hdrop"])
    monkeypatch.setattr(
        win32clipboard, "IsClipboardFormatAvailable",
        lambda fmt: fmt == win32con.CF_HDROP and state["hdrop"] is not None,
    )
    monkeypatch.setattr(win32clipboard, "GetClipboardSequenceNumber", lambda: state["seq"])
    cfg = {"mode": "focus", "text_enabled": False, "hdrop_enabled": True,
           "image_enabled": False, "paste_injection": False}
    store = MappingStore(tmp_path / "m.db")
    masker = TextMasker(store, {"phone": True}, [])
    w = ClipboardWatcher(masker, ImageMasker({}), cfg, tmp_path / "copies")
    return w, state


def test_paste_swaps_hdrop_before_resend(tmp_path, monkeypatch):
    src = tmp_path / "creds.txt"
    src.write_text("call 13800138000", encoding="utf-8")
    w, state = make_watcher(tmp_path, monkeypatch, [str(src)])
    w.ai_focused = True
    assert w.handle_paste() is False  # worker 补发键时剪贴板已是脱敏副本
    (masked,) = state["hdrop"]
    assert masked != str(src) and ".masked.txt" in masked
    assert "[PHONE_" in Path(masked).read_text(encoding="utf-8")
    assert "files masked 1" in w.events[0]


def test_paste_outside_ai_restores_originals(tmp_path, monkeypatch):
    src = tmp_path / "creds.txt"
    src.write_text("call 13800138000", encoding="utf-8")
    w, state = make_watcher(tmp_path, monkeypatch, [str(src)])
    w.ai_focused = True
    w.handle_paste()
    w.ai_focused = False
    assert w.handle_paste() is False
    assert state["hdrop"] == (str(src),)


def test_already_masked_not_double_masked(tmp_path, monkeypatch):
    src = tmp_path / "creds.txt"
    src.write_text("call 13800138000", encoding="utf-8")
    w, state = make_watcher(tmp_path, monkeypatch, [str(src)])
    w.ai_focused = True
    w.handle_paste()
    first = state["hdrop"]
    w.handle_paste()
    assert state["hdrop"] == first
    assert ".masked.masked" not in first[0]