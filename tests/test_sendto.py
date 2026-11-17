"""SendTo bat：frozen exe 不支持 -m pilayer，须用 exe 原生 argv。"""

import sys

from pilayer import cli


def test_sendto_frozen_uses_exe_native_argv(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "pilayer-guard.exe"))
    bat = cli.install_sendto()
    text = bat.read_text(encoding="gbk")
    assert "-m pilayer" not in text
    assert 'mask-file "%~1"' in text
    assert "pause" in text  # 仅失败时 pause（if errorlevel 1）
    assert "shift" in text  # 多选文件循环


def test_sendto_source_uses_module_argv(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    bat = cli.install_sendto()
    assert "-m pilayer mask-file" in bat.read_text(encoding="gbk")