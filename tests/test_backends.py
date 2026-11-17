import os
import shutil
import subprocess
import sys
import time

import pytest

from pilayer.backends.linux import LinuxGuard, classify_linux


def test_classify_linux():
    cfg = {"ai_targets": {"processes": [], "learned_processes": ["foo"], "title_patterns": ["ChatGPT"]}}
    assert classify_linux("cursor", "", cfg)
    assert classify_linux("foo", "", cfg)
    assert classify_linux("chrome", "ChatGPT - Chrome", cfg)
    assert not classify_linux("chrome", "GitHub", cfg)


def test_wayland_degraded(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    g = LinuxGuard()
    assert g.wayland and g.mode == "always"
    g.stop()


@pytest.mark.skipif(
    not (sys.platform == "linux" and os.environ.get("DISPLAY") and shutil.which("xclip")),
    reason="needs X11 + xclip",
)
def test_x11_clipboard_roundtrip():
    g = LinuxGuard()
    g.start()
    try:
        g.write_text("roundtrip 13800138000")
        time.sleep(0.4)
        out = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"], capture_output=True, text=True,
            timeout=5,
        ).stdout
        assert out == "roundtrip 13800138000"
        subprocess.run(
            ["xclip", "-selection", "clipboard", "-i"],
            input="external 13900139000", text=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
        )
        time.sleep(0.4)
        assert g.read_text() == "external 13900139000"
    finally:
        g.stop()


@pytest.mark.skipif(sys.platform != "darwin", reason="needs macOS")
def test_mac_pasteboard_roundtrip():
    from pilayer.backends.macos import MacGuard, classify_mac
    cfg = {"ai_targets": {"processes": [], "learned_processes": [], "title_patterns": ["ChatGPT"]}}
    assert classify_mac("com.openai.chat", "", cfg)
    assert classify_mac("com.x", "ChatGPT", cfg)
    assert not classify_mac("com.x", "Safari", cfg)
    g = MacGuard()
    g.write_text("mac roundtrip 13800138000")
    assert g.read_text() == "mac roundtrip 13800138000"
    r = g.masker.mask("mac roundtrip 13800138000")
    g.write_text(r.text)
    assert g.masker.restore(g.read_text()).text == "mac roundtrip 13800138000"
    g.stop()

def test_config_migration_old_injection_default(tmp_path):
    import yaml
    from pilayer.config import load_config
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump({"guard": {"paste_injection": True}}), encoding="utf-8")
    cfg = load_config(p)
    assert cfg["guard"]["paste_injection"] is False
    assert cfg["guard"]["_cfg_version"] == 2
    # 迁移后用户显式改回 true 应被尊重
    cfg["guard"]["paste_injection"] = True
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    assert load_config(p)["guard"]["paste_injection"] is True


@pytest.mark.skipif(sys.platform != "win32", reason="win32 mouse hook only")
def test_drag_gesture_fires_show_hide_callbacks():
    import ctypes as c
    from pilayer.focus import ForegroundWatcher, MSLLHOOKSTRUCT
    starts, ends = [], []
    w = ForegroundWatcher({}, lambda ai: None,
                          on_drag_start=lambda: starts.append(1),
                          on_drag_end=lambda: ends.append(1))

    def ev(x, y):
        m = MSLLHOOKSTRUCT()
        m.pt.x, m.pt.y = x, y
        return c.byref(m)

    w._mouse_cb(0, 0x0201, ev(0, 0))
    w._mouse_cb(0, 0x0200, ev(60, 60))
    w._mouse_cb(0, 0x0200, ev(80, 80))
    assert starts == [1]  # 越过阈值只触发一次
    w._mouse_cb(0, 0x0202, ev(80, 80))
    assert ends == [1]


@pytest.mark.skipif(sys.platform != "win32", reason="win32 tray/watcher only")
def test_events_hook_fires(tmp_path):
    from pilayer.clipboard.watcher import ClipboardWatcher
    from pilayer.engine import MappingStore, TextMasker
    from pilayer.engine.image import ImageMasker
    calls = []
    w = ClipboardWatcher(
        TextMasker(MappingStore(tmp_path / "m.db"), {}, []), ImageMasker({}),
        {}, tmp_path, on_event=lambda: calls.append(1),
    )
    w.events.appendleft("x")
    assert calls == [1]


@pytest.mark.skipif(sys.platform != "win32", reason="win32 winevent only")
def test_drag_start_hook_warns():
    from pilayer.focus import ForegroundWatcher
    calls = []
    w = ForegroundWatcher({}, lambda ai: None, on_drag=lambda: calls.append(1))
    w._on_drag_event(None, 0x000D, None, 0, 0, 0, 0)
    assert calls == [1]


@pytest.mark.skipif(sys.platform != "win32", reason="win32 tray only")
def test_drag_warn_throttled():
    from pilayer.app import Application
    a = Application()
    msgs = []
    a.notify = lambda title, msg: msgs.append(msg)
    a._on_drag()
    a._on_drag()
    assert len(msgs) == 1


@pytest.mark.skipif(sys.platform != "win32", reason="win32 mouse hook only")
def test_mouse_gesture_sets_candidate():
    import ctypes as c
    from pilayer.focus import ForegroundWatcher, MSLLHOOKSTRUCT
    w = ForegroundWatcher({}, lambda ai: None, on_drag=lambda: None)

    def ev(x, y):
        m = MSLLHOOKSTRUCT()
        m.pt.x, m.pt.y = x, y
        return c.byref(m)

    w._mouse_cb(0, 0x0201, ev(0, 0))
    w._drag_track[3] -= 1  # 模拟按住 >200ms
    w._mouse_cb(0, 0x0200, ev(60, 60))
    w._mouse_cb(0, 0x0202, ev(60, 60))
    assert w._drag_candidate is not None
    # 单击（无位移）不产生候选
    w._drag_candidate = None
    w._mouse_cb(0, 0x0201, ev(0, 0))
    w._drag_track[3] -= 1
    w._mouse_cb(0, 0x0202, ev(0, 0))
    assert w._drag_candidate is None


@pytest.mark.skipif(sys.platform != "win32", reason="win32 only")
def test_drag_cross_proc_into_ai_warns(monkeypatch):
    import pilayer.focus as f
    calls = []
    w = f.ForegroundWatcher(
        {"ai_targets": {"processes": ["workbuddy.exe"]}},
        lambda ai: None, on_drag=lambda: calls.append(1),
    )
    monkeypatch.setattr(f, "process_name", lambda h: {1: "explorer.exe", 2: "workbuddy.exe"}[h])
    monkeypatch.setattr(f.win32gui, "GetWindowText", lambda h: "")
    w._evaluate_drag((1, 2))
    assert calls == [1]
    w._evaluate_drag((2, 2))  # 同窗划选不警告
    assert calls == [1]
