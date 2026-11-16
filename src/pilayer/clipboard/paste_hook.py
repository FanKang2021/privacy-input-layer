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
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_uint16),
        ("wScan", ctypes.c_uint16),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _INPUT_UNION(ctypes.Union):
    # x64 下 MOUSEINPUT 决定 union 尺寸为 32（INPUT 总 40），padding 不可省
    _fields_ = [("ki", KEYBDINPUT), ("padding", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("union", _INPUT_UNION)]


_user32 = ctypes.windll.user32
_user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
_user32.SendInput.restype = ctypes.c_uint


def send_unicode(text: str) -> bool:
    """以 UTF-16 code unit 逐字符注入（含代理对），不经过剪贴板。"""
    units = text.encode("utf-16-le")
    events = []
    for i in range(0, len(units), 2):
        code = units[i] | (units[i + 1] << 8)
        for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
            inp = INPUT(type=INPUT_KEYBOARD)
            inp.union.ki = KEYBDINPUT(0, code, flags, 0, None)
            events.append(inp)
    if not events:
        return True
    arr = (INPUT * len(events))(*events)
    return _user32.SendInput(len(events), arr, ctypes.sizeof(INPUT)) == len(events)


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
    def __init__(self, on_paste, drain=None):
        """on_paste() -> True 表示已标记注入，吞掉该粘贴键；drain 在泵循环执行实际注入。"""
        self.on_paste = on_paste
        self.drain = drain or (lambda: None)
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
                self.drain()
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
                    if self.on_paste():
                        return 1  # 已注入，吞掉原粘贴键
        except Exception as e:
            log.warning("paste hook error: %s", e)
        return _user32.CallNextHookEx(self._hook, ncode, wparam, lparam)