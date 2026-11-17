"""桌面脱敏浮窗：自有 drop target，OLE 边界内唯一合法透明拦截点。

拖原件到浮窗 -> 脱敏副本 -> 中继（剪贴板 HDROP + 补发 Ctrl+V）到最近 AI 窗口。
不注入宿主、不装驱动：浮窗是我们自己的窗口，Drop 数据对象直接交给我们。
"""

import ctypes
import logging
import sys
import threading
from pathlib import Path

if sys.platform == "win32":
    import pythoncom
    import win32api
    import win32con
    import win32gui

log = logging.getLogger("pilayer.dropzone")

WM_DROPFILES = 0x0233
WM_APP_SHOW = 0x8001
WM_APP_HIDE = 0x8002
_user32 = ctypes.windll.user32 if sys.platform == "win32" else None
_shell32 = ctypes.windll.shell32 if sys.platform == "win32" else None

if sys.platform == "win32":
    _shell32.DragAcceptFiles.argtypes = [ctypes.c_void_p, ctypes.c_bool]
    _shell32.DragQueryFileW.argtypes = [
        ctypes.c_void_p, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint,
    ]
    _shell32.DragQueryFileW.restype = ctypes.c_uint
    _shell32.DragFinish.argtypes = [ctypes.c_void_p]


class DropZone:
    def __init__(self, masker, copies_dir: Path, suffix: str, on_masked, notify=None):
        self.masker = masker
        self.copies_dir = copies_dir
        self.suffix = suffix
        self.on_masked = on_masked
        self.notify = notify or (lambda title, msg: None)
        self._hwnd = None
        self._thread = None
        self._proc = None
        self._status = "拖文件到此脱敏"
        self._visible = False
        self._stopping = False

    def start(self):
        self._thread = threading.Thread(target=self._run, name="pilayer-dropzone", daemon=True)
        self._thread.start()

    def stop(self):
        self._stopping = True
        if self._hwnd:
            try:
                win32gui.PostMessage(self._hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=3)

    def show(self):
        if self._hwnd:
            win32gui.ShowWindow(self._hwnd, win32con.SW_SHOW)
            self._visible = True

    def hide(self):
        if self._hwnd:
            win32gui.ShowWindow(self._hwnd, win32con.SW_HIDE)
            self._visible = False

    def request_show(self):
        if self._hwnd:
            win32gui.PostMessage(self._hwnd, WM_APP_SHOW, 0, 0)

    def request_hide(self):
        if self._hwnd:
            win32gui.PostMessage(self._hwnd, WM_APP_HIDE, 0, 0)

    def _run(self):
        pythoncom.CoInitialize()
        try:
            wc = win32gui.WNDCLASS()
            wc.lpfnWndProc = self._wnd_proc
            wc.lpszClassName = "PilayerDropZone"
            wc.hInstance = win32api.GetModuleHandle(None)
            wc.hbrBackground = win32gui.GetStockObject(win32con.WHITE_BRUSH)
            cls = win32gui.RegisterClass(wc)
            cx = _user32.GetSystemMetrics(0)
            cy = _user32.GetSystemMetrics(1)
            self._hwnd = win32gui.CreateWindowEx(
                win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW,
                cls, "privacy-input-layer 脱敏浮窗",
                win32con.WS_POPUP | win32con.WS_CAPTION | win32con.WS_SYSMENU,
                cx - 300, cy - 200, 280, 150,
                0, 0, wc.hInstance, None,
            )
            _shell32.DragAcceptFiles(self._hwnd, True)
            win32gui.ShowWindow(self._hwnd, win32con.SW_HIDE)
            self._visible = False
            log.info("dropzone window created hwnd=%s", self._hwnd)
            win32gui.PumpMessages()
        except Exception as e:
            log.exception("dropzone run error: %s", e)
        finally:
            if self._hwnd:
                _shell32.DragAcceptFiles(self._hwnd, False)
            pythoncom.CoUninitialize()

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_DROPFILES:
            try:
                self._handle_drop(wparam)
            except Exception as e:
                log.exception("dropzone drop error: %s", e)
            return 0
        if msg == win32con.WM_PAINT:
            hdc, ps = win32gui.BeginPaint(hwnd)
            rect = win32gui.GetClientRect(hwnd)
            win32gui.DrawTextW(hdc, self._status, -1, rect,
                               win32con.DT_CENTER | win32con.DT_VCENTER | win32con.DT_WORDBREAK)
            win32gui.EndPaint(hwnd, ps)
            return 0
        if msg == win32con.WM_LBUTTONDOWN:
            _user32.ReleaseCapture()
            _user32.SendMessageW(hwnd, win32con.WM_NCLBUTTONDOWN, 2, 0)  # HTCAPTION 拖动
            return 0
        if msg == WM_APP_SHOW:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            self._visible = True
            return 0
        if msg == WM_APP_HIDE:
            win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
            self._visible = False
            return 0
        if msg == win32con.WM_CLOSE:
            # 手动 X 仅隐藏（可再开）；stop() 置 _stopping 才真正销毁
            if self._stopping:
                win32gui.DestroyWindow(hwnd)
            else:
                win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
                self._visible = False
            return 0
        if msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    def _set_status(self, text):
        self._status = text
        if self._hwnd:
            win32gui.InvalidateRect(self._hwnd, None, True)

    def _handle_drop(self, hdrop):
        n = _shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
        paths = []
        for i in range(n):
            length = _shell32.DragQueryFileW(hdrop, i, None, 0)
            buf = ctypes.create_unicode_buffer(length + 1)
            _shell32.DragQueryFileW(hdrop, i, buf, length + 1)
            paths.append(buf.value)
        _shell32.DragFinish(hdrop)
        log.info("dropzone received %d file(s)", len(paths))
        from .files import SUPPORTED_EXTS, mask_file
        self.copies_dir.mkdir(parents=True, exist_ok=True)
        masked = []
        for p in paths:
            src = Path(p)
            if src.suffix.lower() not in SUPPORTED_EXTS or src.stem.endswith(self.suffix):
                continue
            dst = self.copies_dir / (src.stem + self.suffix + src.suffix)
            try:
                mask_file(src, self.masker, self.suffix, dst=dst)
                masked.append(str(dst))
            except Exception as e:
                log.warning("dropzone mask %s: %s", src.name, e)
        if not masked:
            self._set_status("无可脱敏文件")
            return
        self._set_status(f"已脱敏 {len(masked)} 个，中继中…")
        self.on_masked(masked)