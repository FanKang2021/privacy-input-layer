"""Windows 剪贴板守卫：事件监听 + 文本脱敏/还原 + 图片打码 + 文件副本替换。

防自触发：写入剪贴板后记录序列号，下一次 WM_CLIPBOARDUPDATE 若序列号
相同则跳过，避免"脱敏->触发->再脱敏"循环。
"""

import ctypes
import struct
import threading
import time
from pathlib import Path

import pythoncom
import win32api
import win32clipboard
import win32con
import win32gui

from ..engine import TextMasker
from ..engine.image import ImageMasker, ImageOCRUnavailable
from ..files import SUPPORTED_EXTS, mask_file
from .dib import dib_to_image, image_to_dib

WM_CLIPBOARDUPDATE = 0x031D

# pywin32 未封装这两个 API，直接调 user32
_user32 = ctypes.windll.user32
_user32.AddClipboardFormatListener.argtypes = [ctypes.c_void_p]
_user32.AddClipboardFormatListener.restype = ctypes.c_bool
_user32.RemoveClipboardFormatListener.argtypes = [ctypes.c_void_p]
_user32.RemoveClipboardFormatListener.restype = ctypes.c_bool


class ClipboardWatcher:
    def __init__(self, masker: TextMasker, image_masker: ImageMasker,
                 guard_cfg: dict, copies_dir: Path, file_suffix: str = ".masked",
                 notify=None):
        self.masker = masker
        self.image_masker = image_masker
        self.cfg = guard_cfg
        self.copies_dir = copies_dir
        self.file_suffix = file_suffix
        self.notify = notify or (lambda title, msg: None)
        self.enabled = True
        self._hwnd = None
        self._suppress_seq = None
        self._thread = None
        self._image_warned = False

    # ---------- 生命周期 ----------

    def start(self):
        self._thread = threading.Thread(target=self._run, name="pilayer-clipboard", daemon=True)
        self._thread.start()

    def stop(self):
        if self._hwnd:
            try:
                win32gui.PostMessage(self._hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self):
        pythoncom.CoInitialize()
        try:
            wc = win32gui.WNDCLASS()
            wc.lpfnWndProc = self._wnd_proc
            wc.lpszClassName = "PilayerClipboardWatcher"
            wc.hInstance = win32api.GetModuleHandle(None)
            cls = win32gui.RegisterClass(wc)
            self._hwnd = win32gui.CreateWindowEx(
                0, cls, "pilayer", 0, 0, 0, 0, 0,
                win32con.HWND_MESSAGE, 0, wc.hInstance, None,
            )
            if not _user32.AddClipboardFormatListener(self._hwnd):
                raise ctypes.WinError()
            self._suppress_seq = win32clipboard.GetClipboardSequenceNumber()
            win32gui.PumpMessages()
        finally:
            pythoncom.CoUninitialize()

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_CLIPBOARDUPDATE:
            try:
                seq = win32clipboard.GetClipboardSequenceNumber()
                if seq != self._suppress_seq:
                    self._on_update()
            except Exception as e:
                self.notify("privacy-input-layer", f"处理剪贴板出错：{e}")
            return 0
        if msg == win32con.WM_DESTROY:
            try:
                _user32.RemoveClipboardFormatListener(hwnd)
            except Exception:
                pass
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    # ---------- 剪贴板读写 ----------

    def _open(self, retries: int = 20) -> bool:
        for _ in range(retries):
            try:
                win32clipboard.OpenClipboard()
                return True
            except Exception:
                time.sleep(0.03)
        return False

    def _mark_self_write(self):
        self._suppress_seq = win32clipboard.GetClipboardSequenceNumber()

    def _write_text(self, text: str):
        if not self._open():
            return
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()
        self._mark_self_write()

    def _write_dib(self, dib: bytes):
        if not self._open():
            return
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_DIB, dib)
        finally:
            win32clipboard.CloseClipboard()
        self._mark_self_write()

    def _write_hdrop(self, paths: list[str]):
        payload = "\0".join(paths) + "\0\0"
        data = struct.pack("<IiiII", 20, 0, 0, 0, 1) + payload.encode("utf-16-le")
        if not self._open():
            return
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_HDROP, data)
        finally:
            win32clipboard.CloseClipboard()
        self._mark_self_write()

    # ---------- 事件分发 ----------

    def _on_update(self):
        if not self.enabled:
            return
        if self.cfg.get("hdrop_enabled") and win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
            self._handle_hdrop()
        elif self.cfg.get("image_enabled") and win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB):
            self._handle_image()
        elif self.cfg.get("text_enabled") and win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            self._handle_text()

    def _handle_text(self):
        if not self._open():
            return
        try:
            text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        except Exception:
            return
        finally:
            win32clipboard.CloseClipboard()
        if not isinstance(text, str) or not text.strip():
            return

        if self.cfg.get("auto_restore") and self.masker.has_placeholder(text):
            r = self.masker.restore(text)
            if r.count:
                self._write_text(r.text)
                msg = f"已还原 {r.count} 处占位符"
                if r.missing:
                    msg += f"（{len(r.missing)} 处无映射，保留原样）"
                self.notify("privacy-input-layer", msg)
            return

        r = self.masker.mask(text)
        if r.count:
            self._write_text(r.text)
            kinds = "/".join(sorted(set(r.kinds)))
            self.notify("privacy-input-layer", f"已脱敏 {r.count} 处（{kinds}），粘贴即安全")

    def _handle_image(self):
        if not self._open():
            return
        try:
            dib = win32clipboard.GetClipboardData(win32con.CF_DIB)
        except Exception:
            return
        finally:
            win32clipboard.CloseClipboard()
        img = dib_to_image(dib)
        if img is None:
            return
        try:
            masked, count = self.image_masker.mask(img)
        except ImageOCRUnavailable as e:
            if not self._image_warned:
                self._image_warned = True
                self.notify("privacy-input-layer", str(e))
            return
        if count:
            self._write_dib(image_to_dib(masked))
            self.notify("privacy-input-layer", f"图片已打码 {count} 处敏感区域")

    def _handle_hdrop(self):
        if not self._open():
            return
        try:
            paths = win32clipboard.GetClipboardData(win32con.CF_HDROP)
        except Exception:
            return
        finally:
            win32clipboard.CloseClipboard()
        if not paths:
            return
        self.copies_dir.mkdir(parents=True, exist_ok=True)
        new_paths = []
        masked_count = 0
        for p in paths:
            src = Path(p)
            if src.suffix.lower() in SUPPORTED_EXTS and src.exists():
                dst = self.copies_dir / (src.stem + self.file_suffix + src.suffix)
                try:
                    result = mask_file(src, self.masker, self.file_suffix, dst=dst)
                    new_paths.append(str(result.dst))
                    masked_count += 1
                    continue
                except Exception:
                    pass
            new_paths.append(p)
        if masked_count:
            self._write_hdrop(new_paths)
            self.notify(
                "privacy-input-layer",
                f"已替换 {masked_count} 个文件为脱敏副本（{self.copies_dir}）",
            )