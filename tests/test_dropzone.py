"""脱敏浮窗：drop 解析+脱敏+中继回调。"""

from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("win32clipboard")

from pilayer import dropzone as dz
from pilayer.engine import MappingStore, TextMasker


def test_handle_drop_masks_and_calls_on_masked(tmp_path, monkeypatch):
    src = tmp_path / "creds.txt"
    src.write_text("call 13800138000", encoding="utf-8")

    def fake_query(h, i, buf, n):
        if i == 0xFFFFFFFF:
            return 1
        if buf is None:
            return len(str(src))
        buf.value = str(src)
        return len(str(src))

    monkeypatch.setattr(dz, "_shell32", SimpleNamespace(
        DragQueryFileW=fake_query, DragFinish=lambda h: None,
    ))
    got = []
    masker = TextMasker(MappingStore(tmp_path / "m.db"), {"phone": True}, [])
    zone = dz.DropZone(masker, tmp_path / "copies", ".masked", on_masked=got.append)
    zone._handle_drop(1)
    assert len(got) == 1
    paths = got[0]  # on_masked 收到的是路径列表
    assert len(paths) == 1 and ".masked.txt" in paths[0]
    assert "[PHONE_" in Path(paths[0]).read_text(encoding="utf-8")


def test_relay_writes_hdrop_and_resends(monkeypatch):
    from pilayer.app import Application
    a = Application()
    wrote = []
    resent = []
    monkeypatch.setattr(a.watcher, "_write_hdrop", lambda p: wrote.append(p))
    a.focus = SimpleNamespace(last_ai_hwnd=123)
    a.paste_hook = SimpleNamespace(_resend=lambda *args: resent.append(args))
    monkeypatch.setattr("ctypes.windll.user32.SetForegroundWindow", lambda h: True)
    a._on_zone_masked(["C:\\x.masked.txt"])
    assert wrote == [["C:\\x.masked.txt"]]
    assert resent and resent[0][0] == 0x56