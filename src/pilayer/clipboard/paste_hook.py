"""Ctrl+V / Shift+Insert 瞬间剪贴板补偿：把粘贴动作本身变成拦截点。

切窗/换 tab 到守卫完成变换之间存在竞态窗口；低级键盘钩子在粘贴键
按下的瞬间同步执行毫秒级文本变换，关闭该窗口。图片 OCR 与文件副本
太慢，不在钩子内做，仍走切窗路径。
"""

import ctypes
import logging
import threading

import pythoncom
import win32con
import win32gui

log = logging.getLogger("pilayer.paste")

WH_KEYBOARD_LL = 13
VK_V = 0x56
VK_INSERT = 0x2D
VK_CONTROL = 0x11
VK_SHIFT = 0x10


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.c_uint32),
        ("scanCode", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
_user32 = ctypes.windll.user32
_user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, ctypes.c_void_p, ctypes.c_uint32]
_user32.SetWindowsHookExW.restype = ctypes.c_void_p
_user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
_user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
_user32.CallNextHookEx.restype = ctypes.c_long
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user32.GetAsyncKeyState.restype = ctypes.c_short


class PasteHook:
    def __init__(self, ensure):
        self.ensure = ensure
        self._stop = threading.Event()
        self._hook = None
        self._proc = None
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="pilayer-paste", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self):
        # 钩子事件投递到安装线程，必须在本线程泵消息
        pythoncom.CoInitialize()
        try:
            self._proc = HOOKPROC(self._cb)
            self._hook = _user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
            log.info("paste hook installed: %s", self._hook)
            while not self._stop.is_set():
                win32gui.PumpWaitingMessages()
                self._stop.wait(0.02)
        finally:
            if self._hook:
                _user32.UnhookWindowsHookEx(self._hook)
                self._hook = None
            pythoncom.CoUninitialize()

    def _cb(self, ncode, wparam, lparam):
        try:
            if ncode >= 0 and wparam in (win32con.WM_KEYDOWN, win32con.WM_SYSKEYDOWN):
                ks = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                ctrl = _user32.GetAsyncKeyState(VK_CONTROL) & 0x8000
                shift = _user32.GetAsyncKeyState(VK_SHIFT) & 0x8000
                if (ks.vkCode == VK_V and ctrl) or (ks.vkCode == VK_INSERT and shift):
                    self.ensure()
        except Exception as e:
            log.warning("paste hook error: %s", e)
        return _user32.CallNextHookEx(self._hook, ncode, wparam, lparam)