"""Windows 剪贴板守卫：事件监听 + 文本脱敏/还原 + 图片打码 + 文件副本替换。

两种模式：
- focus：仅 AI 客户端前台时脱敏；离开 AI 时还原。切窗瞬间变换当前剪贴板。
- always：全局常开（复制即脱敏、复制占位符即还原）。

防自触发：写入剪贴板后记录序列号，下一次 WM_CLIPBOARDUPDATE 若序列号
相同则跳过，避免"脱敏->触发->再脱敏"循环。
"""

import ctypes
import html as _html
import logging
import re
import struct
import threading
import time
from collections import deque
from html.parser import HTMLParser
from pathlib import Path

import pythoncom
import win32api
import win32clipboard
import win32con
import win32gui

from ..i18n import t
from ..engine import TextMasker
from ..engine import PLACEHOLDER_RE
from ..engine.image import ImageMasker, ImageOCRUnavailable
from ..files import SUPPORTED_EXTS, mask_file
from .dib import dib_to_image, image_to_dib

WM_CLIPBOARDUPDATE = 0x031D

log = logging.getLogger("pilayer.clipboard")


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(raw) -> str | None:
    """CF_HTML-only 复制源的回退提取：取 StartFragment 片段去标签。"""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if not isinstance(raw, str):
        return None
    m = re.search(r"<!--StartFragment-->(.*?)<!--EndFragment-->", raw, re.S)
    frag = m.group(1) if m else raw
    p = _TextExtractor()
    try:
        p.feed(frag)
    except Exception:
        return None
    text = _html.unescape("".join(p.parts))
    return text or None

# pywin32 未封装这两个 API，直接调 user32
_user32 = ctypes.windll.user32
_user32.AddClipboardFormatListener.argtypes = [ctypes.c_void_p]
_user32.AddClipboardFormatListener.restype = ctypes.c_bool
_user32.RemoveClipboardFormatListener.argtypes = [ctypes.c_void_p]
_user32.RemoveClipboardFormatListener.restype = ctypes.c_bool


class ClipboardWatcher:
    def __init__(self, masker: TextMasker, image_masker: ImageMasker,
                 guard_cfg: dict, copies_dir: Path, file_suffix: str = ".masked",
                 notify=None, on_learn=None, ai_cfg=None):
        self.masker = masker
        self.image_masker = image_masker
        self.cfg = guard_cfg
        self.copies_dir = copies_dir
        self.file_suffix = file_suffix
        self.notify = notify or (lambda title, msg: None)
        self.on_learn = on_learn
        self.ai_cfg = ai_cfg
        self.enabled = True
        self.mode = guard_cfg.get("mode", "focus")
        self.ai_focused = False
        self._hdrop_last: list[tuple[str, str]] | None = None
        self._pending_inject: str | None = None
        self._chunk_queue: deque = deque()
        self._chunk_next_at = 0.0
        self.resend_cb = None
        self.events: deque = deque(maxlen=20)
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
                    result = self._on_update()
                    if result:
                        self.notify("privacy-input-layer", result)
            except Exception as e:
                self.notify("privacy-input-layer", t("clip_error", e=e))
            return 0
        if msg == win32con.WM_DESTROY:
            try:
                _user32.RemoveClipboardFormatListener(hwnd)
            except Exception:
                pass
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    # ---------- 焦点感知 ----------

    def set_focus(self, ai: bool) -> str | None:
        if self.mode != "focus" or ai == self.ai_focused:
            return None
        self.ai_focused = ai
        if ai:
            return self._apply_focus()
        # 懒还原：离开 AI 不主动把明文写回共享剪贴板，
        # 由粘贴钩子/复制事件按需还原（lazy_restore=false 恢复旧行为）
        if not self.cfg.get("lazy_restore", True):
            return self._apply_focus()
        return None

    def _apply_focus(self) -> str | None:
        if not self.enabled:
            return None
        if self.cfg.get("hdrop_enabled") and win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
            return self._handle_hdrop() if self.ai_focused else self._restore_hdrop()
        if self.cfg.get("image_enabled") and win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB):
            return self._handle_image() if self.ai_focused else None
        if self.cfg.get("text_enabled") and self._text_available():
            return self._mask_text_current() if self.ai_focused else self._restore_text_current()
        return None

    # ---------- 剪贴板读写 ----------

    def _open(self, retries: int = 20, delay: float = 0.03) -> bool:
        for _ in range(retries):
            try:
                win32clipboard.OpenClipboard()
                return True
            except Exception:
                time.sleep(delay)
        return False

    def _mark_self_write(self):
        self._suppress_seq = win32clipboard.GetClipboardSequenceNumber()

    def _write_text(self, text: str, fast: bool = False):
        opened = self._open(3, 0.01) if fast else self._open()
        if not opened:
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

    def _text_available(self) -> bool:
        return (
            win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT)
            or win32clipboard.IsClipboardFormatAvailable(win32con.CF_HTML)
        )

    def _read_text(self, fast: bool = False) -> str | None:
        opened = self._open(3, 0.01) if fast else self._open()
        if not opened:
            return None
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                return text if isinstance(text, str) else None
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_HTML):
                return html_to_text(win32clipboard.GetClipboardData(win32con.CF_HTML))
            return None
        except Exception:
            return None
        finally:
            win32clipboard.CloseClipboard()

    def _read_hdrop(self) -> tuple[str, ...] | None:
        if not self._open():
            return None
        try:
            return win32clipboard.GetClipboardData(win32con.CF_HDROP)
        except Exception:
            return None
        finally:
            win32clipboard.CloseClipboard()

    # ---------- 变换逻辑（返回通知消息或 None） ----------

    def _on_update(self) -> str | None:
        if not self.enabled:
            return None
        self._maybe_learn()
        if self.mode == "focus" and not self.ai_focused:
            # 非 AI 前台：只还原，不脱敏
            if self.cfg.get("hdrop_enabled") and win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
                return self._restore_hdrop()
            if self.cfg.get("text_enabled") and self._text_available():
                # 注入式下剪贴板不持有我方明文：复制事件不还原，粘贴时注入
                if self.cfg.get("paste_injection", True):
                    return None
                return self._restore_text_current()
            return None
        if self.cfg.get("hdrop_enabled") and win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
            return self._handle_hdrop()
        if self.cfg.get("image_enabled") and win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB):
            return self._handle_image()
        if self.cfg.get("text_enabled") and self._text_available():
            return self._handle_text()
        return None

    def _maybe_learn(self):
        """自学习：复制含 >=2 个我方占位符的文本且来源未分类 => 记为 AI 客户端。"""
        if not self.on_learn or self.ai_cfg is None or not self._text_available():
            return
        txt = self._read_text(fast=True)
        if not txt or len(PLACEHOLDER_RE.findall(txt)) < 2:
            return
        from ..focus import classify_target, process_name
        proc = process_name(win32gui.GetForegroundWindow())
        if proc and not classify_target(proc, None, self.ai_cfg):
            self.on_learn(proc)

    def handle_paste(self) -> bool:
        """粘贴键瞬间：注入式直接把目标文本送进焦点窗口，剪贴板不动。

        返回 True 表示已注入（钩子吞键）；False 放行原粘贴。
        注入失败（UIPI 提权窗口等）回退剪贴板写入后放行。
        """
        if not self.enabled:
            return False
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
            return False
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB):
            return False
        if not self._text_available():
            return False
        if not self.cfg.get("paste_injection", True):
            self.ensure_for_paste()
            return False
        text = self._read_text()
        if not text:
            return False
        if self.mode == "focus":
            if self.ai_focused:
                r = self.masker.mask(text)
                target = r.text
                if r.count:
                    kinds = "/".join(sorted(set(r.kinds)))
                    self.events.appendleft(f"{time.strftime('%H:%M:%S')} masked {r.count} ({kinds})")
                direction = "mask"
            else:
                r = self.masker.restore(text)
                target = r.text
                if r.count:
                    self.events.appendleft(f"{time.strftime('%H:%M:%S')} restored {r.count}")
                direction = "restore"
        elif self.cfg.get("auto_restore") and self.masker.has_placeholder(text):
            r = self.masker.restore(text)
            target = r.text
            if r.count:
                self.events.appendleft(f"{time.strftime('%H:%M:%S')} restored {r.count}")
            direction = "restore"
        else:
            r = self.masker.mask(text)
            target = r.text
            if r.count:
                kinds = "/".join(sorted(set(r.kinds)))
                self.events.appendleft(f"{time.strftime('%H:%M:%S')} masked {r.count} ({kinds})")
            direction = "mask"
        if target == text:
            return False
        if direction == "mask":
            # 掩码态上剪贴板是安全的：走真实粘贴；大文本分块摊销宿主渲染成本
            size = int(self.cfg.get("paste_chunk_size", 400) or 0)
            if size <= 0 or len(target) <= size:
                self._write_text(target)
                self._chunk_queue.clear()
                return False
            chunks = [target[i:i + size] for i in range(0, len(target), size)]
            self._write_text(chunks[0])
            self._chunk_queue = deque(chunks[1:])
            self._chunk_next_at = time.time() + self.cfg.get("paste_chunk_delay_ms", 40) / 1000
            return False
        self._pending_inject = target
        return True

    def drain_injection(self):
        if self._chunk_queue and self.resend_cb and time.time() >= self._chunk_next_at:
            chunk = self._chunk_queue.popleft()
            self._write_text(chunk)
            self._chunk_next_at = time.time() + self.cfg.get("paste_chunk_delay_ms", 40) / 1000
            self.resend_cb()
        target = getattr(self, "_pending_inject", None)
        if not target:
            return
        self._pending_inject = None
        from . import paste_hook
        # 等物理修饰键真正释放（合成 keyup 会被 Ctrl 自动重复 keydown 覆盖）
        deadline = time.time() + 3.0
        while time.time() < deadline and (
            paste_hook._user32.GetAsyncKeyState(0x11) & 0x8000
            or paste_hook._user32.GetAsyncKeyState(0x10) & 0x8000
            or paste_hook._user32.GetAsyncKeyState(0x12) & 0x8000
        ):
            time.sleep(0.01)
        if paste_hook._user32.GetAsyncKeyState(0x11) & 0x8000:
            # 用户仍按住 Ctrl：回退剪贴板路径（罕见，隐私 trade-off 已文档化）
            self._write_text(target)
            return
        ok = paste_hook.send_unicode(target)
        log.info("paste inject drain ok=%s len=%d", ok, len(target))
        if not ok:
            self._write_text(target)

    def ensure_for_paste(self):
        """粘贴键瞬间的毫秒级补偿：只处理文本，图片/文件走切窗路径。"""
        if not self.enabled:
            return
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_HDROP):
            return
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB):
            return
        if not self._text_available():
            return
        if self.mode == "focus":
            if self.ai_focused:
                self._mask_text_current(fast=True)
            else:
                self._restore_text_current(fast=True)
            return
        text = self._read_text(fast=True)
        if not text or not text.strip():
            return
        if self.cfg.get("auto_restore") and self.masker.has_placeholder(text):
            self._restore_text_current(fast=True)
        else:
            self._mask_text_current(fast=True)

    def _mask_text_current(self, fast: bool = False) -> str | None:
        text = self._read_text(fast=fast)
        if not text or not text.strip():
            return None
        r = self.masker.mask(text)
        if r.count:
            self._write_text(r.text, fast=fast)
            kinds = "/".join(sorted(set(r.kinds)))
            self.events.appendleft(f"{time.strftime('%H:%M:%S')} masked {r.count} ({kinds})")
            return t("masked", count=r.count, kinds=kinds)
        return None

    def _restore_text_current(self, fast: bool = False) -> str | None:
        text = self._read_text(fast=fast)
        if not text or not self.masker.has_placeholder(text):
            return None
        r = self.masker.restore(text)
        if r.count:
            self._write_text(r.text, fast=fast)
            self.events.appendleft(f"{time.strftime('%H:%M:%S')} restored {r.count}")
            msg = t("restored", count=r.count)
            if r.missing:
                msg += t("restored_missing", n=len(r.missing))
            return msg
        return None

    def _handle_text(self) -> str | None:
        if self.mode == "focus":
            return self._mask_text_current() if self.ai_focused else self._restore_text_current()
        text = self._read_text()
        if not text or not text.strip():
            return None
        if self.cfg.get("auto_restore") and self.masker.has_placeholder(text):
            return self._restore_text_current()
        return self._mask_text_current()

    def _handle_image(self) -> str | None:
        if not self._open():
            return None
        try:
            dib = win32clipboard.GetClipboardData(win32con.CF_DIB)
        except Exception:
            return None
        finally:
            win32clipboard.CloseClipboard()
        img = dib_to_image(dib)
        if img is None:
            return None
        try:
            masked, count = self.image_masker.mask(img)
        except ImageOCRUnavailable as e:
            if not self._image_warned:
                self._image_warned = True
                return str(e)
            return None
        if count:
            self._write_dib(image_to_dib(masked))
            self.events.appendleft(f"{time.strftime('%H:%M:%S')} image masked {count}")
            return t("image_masked", count=count)
        return None

    def _handle_hdrop(self) -> str | None:
        paths = self._read_hdrop()
        if not paths:
            return None
        self.copies_dir.mkdir(parents=True, exist_ok=True)
        new_paths = []
        pairs = []
        for p in paths:
            src = Path(p)
            if src.suffix.lower() in SUPPORTED_EXTS and src.exists():
                dst = self.copies_dir / (src.stem + self.file_suffix + src.suffix)
                try:
                    mask_file(src, self.masker, self.file_suffix, dst=dst)
                    new_paths.append(str(dst))
                    pairs.append((p, str(dst)))
                    continue
                except Exception:
                    pass
            new_paths.append(p)
        if pairs:
            self._hdrop_last = pairs
            self._write_hdrop(new_paths)
            self.events.appendleft(f"{time.strftime('%H:%M:%S')} files masked {len(pairs)}")
            return t("hdrop", n=len(pairs), dir=self.copies_dir)
        return None

    def _restore_hdrop(self) -> str | None:
        if not self._hdrop_last:
            return None
        paths = self._read_hdrop()
        if not paths or list(paths) != [m for _, m in self._hdrop_last]:
            return None
        self._write_hdrop([o for o, _ in self._hdrop_last])
        self._hdrop_last = None
        return t("hdrop_restored")