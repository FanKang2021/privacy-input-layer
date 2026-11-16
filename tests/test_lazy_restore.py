import win32clipboard
import win32con

from pilayer.clipboard import ClipboardWatcher
from pilayer.engine import MappingStore, TextMasker
from pilayer.engine.image import ImageMasker


def make_watcher(tmp_path, monkeypatch, lazy=True, injection=True):
    state = {"text": None, "seq": 0}

    def open_cb():
        return True

    def set_cb(fmt, data):
        state["text"] = data
        state["seq"] += 1

    monkeypatch.setattr(win32clipboard, "OpenClipboard", open_cb)
    monkeypatch.setattr(win32clipboard, "CloseClipboard", lambda: None)
    monkeypatch.setattr(win32clipboard, "EmptyClipboard", lambda: state.update(text=""))
    monkeypatch.setattr(win32clipboard, "SetClipboardData", set_cb)
    monkeypatch.setattr(win32clipboard, "GetClipboardData", lambda fmt: state["text"])
    monkeypatch.setattr(
        win32clipboard, "IsClipboardFormatAvailable",
        lambda fmt: fmt == win32con.CF_UNICODETEXT and state["text"] is not None,
    )
    monkeypatch.setattr(win32clipboard, "GetClipboardSequenceNumber", lambda: state["seq"])

    cfg = {"mode": "focus", "text_enabled": True, "hdrop_enabled": False,
           "image_enabled": False, "lazy_restore": lazy, "paste_injection": injection}
    store = MappingStore(tmp_path / "m.db")
    masker = TextMasker(store, {"phone": True}, [])
    w = ClipboardWatcher(masker, ImageMasker({}), cfg, tmp_path)
    return w, state


def test_lazy_restore_keeps_plaintext_off_clipboard(tmp_path, monkeypatch):
    w, state = make_watcher(tmp_path, monkeypatch, lazy=True)
    state["text"] = "call 13800138000"
    assert w.set_focus(True) is not None
    assert "[PHONE_" in state["text"]
    masked = state["text"]
    assert w.set_focus(False) is None
    assert state["text"] == masked  # 不主动写回明文


def test_proactive_restore_when_lazy_off(tmp_path, monkeypatch):
    w, state = make_watcher(tmp_path, monkeypatch, lazy=False)
    state["text"] = "call 13800138000"
    w.set_focus(True)
    assert w.set_focus(False) is not None
    assert state["text"] == "call 13800138000"


def test_copy_event_outside_ai_keeps_masked_under_injection(tmp_path, monkeypatch):
    w, state = make_watcher(tmp_path, monkeypatch, lazy=True, injection=True)
    state["text"] = "call 13800138000"
    w.set_focus(True)
    w.set_focus(False)
    masked = state["text"]
    state["text"] = masked  # 模拟在非 AI 处复制占位符文本
    assert w._on_update() is None  # 注入式下不写回明文
    assert state["text"] == masked


def test_on_demand_restore_via_copy_event_legacy(tmp_path, monkeypatch):
    w, state = make_watcher(tmp_path, monkeypatch, lazy=True, injection=False)
    state["text"] = "call 13800138000"
    w.set_focus(True)
    w.set_focus(False)
    masked = state["text"]
    state["text"] = masked
    assert w._on_update() is not None
    assert state["text"] == "call 13800138000"