import win32clipboard
import win32con

from pilayer import focus
from pilayer.clipboard import ClipboardWatcher
from pilayer.engine import MappingStore, TextMasker
from pilayer.engine.image import ImageMasker
from pilayer.focus import classify_target


def test_classify_learned():
    cfg = {"ai_targets": {"processes": [], "learned_processes": ["Foo.exe"]}}
    assert classify_target("foo.exe", None, cfg)
    assert not classify_target("bar.exe", None, cfg)


def test_learning_from_placeholder_rich_copy(tmp_path, monkeypatch):
    state = {"text": "[PHONE_1] and [PHONE_2]", "seq": 0}
    monkeypatch.setattr(win32clipboard, "OpenClipboard", lambda: True)
    monkeypatch.setattr(win32clipboard, "CloseClipboard", lambda: None)
    monkeypatch.setattr(win32clipboard, "GetClipboardData", lambda fmt: state["text"])
    monkeypatch.setattr(
        win32clipboard, "IsClipboardFormatAvailable",
        lambda fmt: fmt == win32con.CF_UNICODETEXT,
    )
    monkeypatch.setattr(focus, "process_name", lambda hwnd: "unknown.exe")
    learned = []
    ai_cfg = {"ai_targets": {"processes": [], "learned_processes": []}}
    store = MappingStore(tmp_path / "m.db")
    w = ClipboardWatcher(
        TextMasker(store, {"phone": True}, []), ImageMasker({}),
        {"mode": "focus"}, tmp_path,
        on_learn=learned.append, ai_cfg=ai_cfg,
    )
    w._maybe_learn()
    assert learned == ["unknown.exe"]
    ai_cfg["ai_targets"]["learned_processes"].append("unknown.exe")
    w._maybe_learn()
    assert learned == ["unknown.exe"]  # 已分类不再学


def test_single_placeholder_not_learned(tmp_path, monkeypatch):
    state = {"text": "only [PHONE_1] here"}
    monkeypatch.setattr(win32clipboard, "OpenClipboard", lambda: True)
    monkeypatch.setattr(win32clipboard, "CloseClipboard", lambda: None)
    monkeypatch.setattr(win32clipboard, "GetClipboardData", lambda fmt: state["text"])
    monkeypatch.setattr(
        win32clipboard, "IsClipboardFormatAvailable",
        lambda fmt: fmt == win32con.CF_UNICODETEXT,
    )
    monkeypatch.setattr(focus, "process_name", lambda hwnd: "unknown.exe")
    learned = []
    store = MappingStore(tmp_path / "m.db")
    w = ClipboardWatcher(
        TextMasker(store, {"phone": True}, []), ImageMasker({}),
        {"mode": "focus"}, tmp_path,
        on_learn=learned.append, ai_cfg={"ai_targets": {}},
    )
    w._maybe_learn()
    assert learned == []