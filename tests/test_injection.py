import pytest

pytest.importorskip("win32clipboard")

import win32clipboard
import win32con

from pilayer.clipboard.watcher import ClipboardWatcher
from pilayer.clipboard import paste_hook
from pilayer.engine import MappingStore, TextMasker
from pilayer.engine.image import ImageMasker


def make_watcher(tmp_path, monkeypatch, ai=True, injection=True):
    state = {"text": None, "seq": 0}
    monkeypatch.setattr(win32clipboard, "OpenClipboard", lambda: True)
    monkeypatch.setattr(win32clipboard, "CloseClipboard", lambda: None)
    monkeypatch.setattr(win32clipboard, "EmptyClipboard", lambda: state.update(text=""))

    def set_cb(fmt, data):
        state["text"] = data
        state["seq"] += 1

    monkeypatch.setattr(win32clipboard, "SetClipboardData", set_cb)
    monkeypatch.setattr(win32clipboard, "GetClipboardData", lambda fmt: state["text"])
    monkeypatch.setattr(
        win32clipboard, "IsClipboardFormatAvailable",
        lambda fmt: fmt == win32con.CF_UNICODETEXT and state["text"] is not None,
    )
    monkeypatch.setattr(win32clipboard, "GetClipboardSequenceNumber", lambda: state["seq"])
    sent = []
    monkeypatch.setattr(paste_hook, "send_unicode", lambda t: (sent.append(t), True)[1])
    cfg = {"mode": "focus", "text_enabled": True, "hdrop_enabled": False,
           "image_enabled": False, "paste_injection": injection}
    store = MappingStore(tmp_path / "m.db")
    masker = TextMasker(store, {"phone": True}, [])
    w = ClipboardWatcher(masker, ImageMasker({}), cfg, tmp_path)
    w.ai_focused = ai
    return w, state, sent


def test_mask_direction_uses_clipboard_one_shot_paste(tmp_path, monkeypatch):
    w, state, sent = make_watcher(tmp_path, monkeypatch, ai=True)
    state["text"] = "call 13800138000"
    assert w.handle_paste() is False  # worker 补发真实 Ctrl+V，一次性粘贴
    assert "[PHONE_" in state["text"]  # 剪贴板为掩码态（安全）
    assert sent == []


def test_restore_direction_injects_plaintext_off_clipboard(tmp_path, monkeypatch):
    w, state, sent = make_watcher(tmp_path, monkeypatch, ai=False)
    state["text"] = "call 13800138000"
    w.ai_focused = True
    w.handle_paste()
    masked = state["text"]
    w.ai_focused = False
    assert w.handle_paste() is True
    w.drain_injection()
    assert sent[-1] == "call 13800138000"
    assert state["text"] == masked  # 明文不进剪贴板


def test_injection_failure_falls_back_to_clipboard(tmp_path, monkeypatch):
    w, state, sent = make_watcher(tmp_path, monkeypatch, ai=False)
    monkeypatch.setattr(paste_hook, "send_unicode", lambda t: False)
    state["text"] = "call [PHONE_1]"
    w.masker.store.get_or_create("PHONE", "13800138000")
    assert w.handle_paste() is True
    w.drain_injection()
    assert state["text"] == "call 13800138000"


def test_no_transform_passes_through(tmp_path, monkeypatch):
    w, state, sent = make_watcher(tmp_path, monkeypatch, ai=True)
    state["text"] = "call [PHONE_1]"
    assert w.handle_paste() is False
    assert sent == []


def test_injection_off_uses_legacy_compensation(tmp_path, monkeypatch):
    w, state, sent = make_watcher(tmp_path, monkeypatch, ai=True, injection=False)
    state["text"] = "call 13800138000"
    assert w.handle_paste() is False
    assert "[PHONE_" in state["text"]
    assert sent == []

def test_audit_events_contain_no_secrets(tmp_path, monkeypatch):
    w, state, sent = make_watcher(tmp_path, monkeypatch, ai=True)
    state["text"] = "call 13800138000"
    w.handle_paste()
    w.drain_injection()
    assert len(w.events) == 1
    assert "masked 1" in w.events[0]
    assert "13800138000" not in w.events[0]
