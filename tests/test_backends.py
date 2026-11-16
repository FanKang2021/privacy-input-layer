import os
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


@pytest.mark.skipif(not (sys.platform == "linux" and os.environ.get("DISPLAY")), reason="needs X11")
def test_x11_clipboard_roundtrip():
    g = LinuxGuard()
    g.start()
    try:
        g.write_text("roundtrip 13800138000")
        time.sleep(0.4)
        assert g.read_text() == "roundtrip 13800138000"
        r = g.masker.mask("roundtrip 13800138000")
        g.write_text(r.text)
        time.sleep(0.4)
        assert g.read_text() == r.text
        assert g.masker.restore(g.read_text()).text == "roundtrip 13800138000"
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