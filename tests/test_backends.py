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


@pytest.mark.skipif(sys.platform != "win32", reason="win32 tray/watcher only")
def test_recent_submenu_dynamic():
    from pilayer.app import Application
    a = Application()
    a.watcher.events.appendleft("12:00:00 masked 2 (SECRET)")
    menu = a._menu()
    # pystray 子菜单只认 Menu 实例；callable action 是点击回调（v0.5.2 前误用）
    recent = [i for i in menu.items if i.submenu][0]
    texts = [(i.text(None) if callable(i.text) else i.text) for i in recent.submenu.items]
    assert any("masked 2" in (t if isinstance(t, str) else "") for t in texts)
    a.watcher.events.appendleft("12:00:01 masked 3 (PHONE)")
    menu2 = a._menu()
    recent2 = [i for i in menu2.items if i.submenu][0]
    texts2 = [(i.text(None) if callable(i.text) else i.text) for i in recent2.submenu.items]
    assert any("masked 3" in (t if isinstance(t, str) else "") for t in texts2)


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
