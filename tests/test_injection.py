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


def test_orphan_keyup_swallowed(monkeypatch):
    import ctypes
    import time as _t
    from win32con import WM_KEYDOWN, WM_KEYUP
    from pilayer.clipboard import paste_hook as ph
    monkeypatch.setattr(ph._user32, "GetAsyncKeyState", lambda vk: 0x8000 if vk == 0x11 else 0)
    monkeypatch.setattr(ph.PasteHook, "_resend", lambda self, *a: None)
    hook = ph.PasteHook(lambda: False)
    ks = ph.KBDLLHOOKSTRUCT(0x56, 0, 0, 0, None)
    assert hook._cb(0, WM_KEYDOWN, ctypes.byref(ks)) == 1
    assert 0x56 in hook._swallowed
    _t.sleep(0.2)
    ks2 = ph.KBDLLHOOKSTRUCT(0x56, 0, 0, 0, None)
    assert hook._cb(0, WM_KEYUP, ctypes.byref(ks2)) == 1
    assert not hook._swallowed


def test_resend_adapts_to_physical_modifiers(monkeypatch):
    import ctypes
    from pilayer.clipboard import paste_hook as ph
    sent = []
    monkeypatch.setattr(ph._user32, "SendInput", lambda n, arr, sz: sent.append([arr[i].union.ki.wVk for i in range(n)]) or n)
    hook = ph.PasteHook(lambda: False)
    # 物理 Ctrl 仍按住：只发 V
    monkeypatch.setattr(ph._user32, "GetAsyncKeyState", lambda vk: 0x8000 if vk == 0x11 else 0)
    hook._resend(0x56, True, False)
    assert sent[-1] == [0x56, 0x56]
    # 物理 Ctrl 已释放：完整组合
    monkeypatch.setattr(ph._user32, "GetAsyncKeyState", lambda vk: 0)
    hook._resend(0x56, True, False)
    assert sent[-1] == [0x11, 0x56, 0x56, 0x11]
