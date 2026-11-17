"""前台焦点识别：判断当前前台窗口是否为 AI 对话客户端。

进程白名单直接命中；浏览器进程则读地址栏 URL 匹配域名。
浏览器内导航/换 tab 不触发前台事件，故浏览器前台期间 1s 轮询 URL。
"""

import ctypes
import logging
import re
import threading
import time
from urllib.parse import urlparse

import sys

if sys.platform == "win32":
    import pythoncom
    import win32api
    import win32con
    import win32gui
    import win32process

log = logging.getLogger("pilayer.focus")

EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_SYSTEM_DRAGDROPSTART = 0x000D
WINEVENT_OUTOFCONTEXT = 0x0000
WH_MOUSE_LL = 14
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202

if sys.platform == "win32":
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    WinEventProc = ctypes.WINFUNCTYPE(
        None, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
        ctypes.c_long, ctypes.c_long, ctypes.c_uint32, ctypes.c_uint32,
    )
    MouseHookProc = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
    )

    class _POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("pt", _POINT),
            ("mouseData", ctypes.c_uint32),
            ("flags", ctypes.c_uint32),
            ("time", ctypes.c_uint32),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    _user32.SetWindowsHookExW.argtypes = [
        ctypes.c_int, MouseHookProc, ctypes.c_void_p, ctypes.c_uint32,
    ]
    _user32.SetWindowsHookExW.restype = ctypes.c_void_p
    _user32.CallNextHookEx.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
    ]
    _user32.CallNextHookEx.restype = ctypes.c_long

    # pywin32 无 win32gui.MSG，消息循环用 ctypes 自有结构
    class _MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", ctypes.c_void_p),
            ("message", ctypes.c_uint32),
            ("wParam", ctypes.c_void_p),
            ("lParam", ctypes.c_void_p),
            ("time", ctypes.c_uint32),
            ("pt", _POINT),
        ]

    _user32.GetMessageW.argtypes = [
        ctypes.POINTER(_MSG), ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
    ]
    _user32.GetMessageW.restype = ctypes.c_int
    _user32.TranslateMessage.argtypes = [ctypes.POINTER(_MSG)]
    _user32.DispatchMessageW.argtypes = [ctypes.POINTER(_MSG)]
    _user32.DispatchMessageW.restype = ctypes.c_long


_URLISH_RE = re.compile(r"^[\w-]+(\.[\w-]+)+(/[^\s]*)?$")
_ADDRESS_BAR_KEYS = ("address", "地址", "搜索或输入", "search or enter")

from .engine.rules import _MODEL_RE, _AI_DISCLAIMER_RE, _CHAT_INPUT_RE, _PICKER_TYPES


def process_name(hwnd) -> str:
    pid = win32process.GetWindowThreadProcessId(hwnd)[1]
    h = _kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_uint32(1024)
        if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1].lower()
        return ""
    finally:
        _kernel32.CloseHandle(h)


def url_host(url: str) -> str:
    try:
        return (urlparse(url if "://" in url else "http://" + url).hostname or "").lower()
    except ValueError:
        return ""


def looks_like_url(s: str) -> bool:
    s = (s or "").strip()
    if not s or len(s) > 200 or any(c.isspace() for c in s):
        return False
    if s.startswith(("http://", "https://", "www.")):
        return True
    if not _URLISH_RE.match(s):
        return False
    tld = s.split("/", 1)[0].rsplit(".", 1)[-1]
    return tld.isalpha() and len(tld) >= 2


def classify_target(process: str, url: str | None, cfg: dict, title: str = "") -> bool:
    t = cfg.get("ai_targets", {})
    if process in [p.lower() for p in t.get("processes", [])]:
        return True
    if process in [p.lower() for p in t.get("learned_processes", [])]:
        return True
    if process in [b.lower() for b in t.get("browsers", [])]:
        if url:
            host = url_host(url)
            for pat in t.get("url_patterns", []):
                pat = pat.lower()
                if host == pat or host.endswith("." + pat):
                    return True
        # 标题兜底：浏览器窗口标题 = 页面标题 - 浏览器名，不依赖 UIA 可用性
        tl = (title or "").lower()
        for pat in t.get("title_patterns", []):
            if pat.lower() in tl:
                return True
    return False


def browser_url(hwnd) -> str | None:
    """读浏览器地址栏；优先按控件名定位，回退扫描 URL 形态的编辑框。"""
    try:
        import uiautomation as auto
    except ImportError:
        return None
    try:
        root = auto.ControlFromHandle(hwnd)
        if root is None:
            return None
        fallback = None
        visited = 0
        # BFS：地址栏位于浅层 UI chrome，DFS 会先钻进网页内容耗尽配额
        queue = [(root, 0)]
        while queue and visited < 600:
            ctrl, depth = queue.pop(0)
            if depth > 6:
                continue
            visited += 1
            if ctrl.ControlTypeName == "EditControl":
                name = (ctrl.Name or "").lower()
                try:
                    value = ctrl.GetValuePattern().Value
                except Exception:
                    value = None
                if value is not None and any(k in name for k in _ADDRESS_BAR_KEYS):
                    return value
                if fallback is None and value and looks_like_url(value):
                    fallback = value
            child = ctrl.GetFirstChildControl()
            while child is not None:
                queue.append((child, depth + 1))
                child = child.GetNextSiblingControl()
        return fallback
    except Exception:
        return None


def ai_ui_signature(hwnd) -> str | None:
    """零配置 AI 对话识别：扫描窗口 UIA 树的三类通用签名。

    1. 模型选择器控件（spark-x2.6 / Qwen3.8-Max / gpt-4o …）
    2. AI 声明短文本（内容由 AI 生成 / AI helper / Powered by inkeep …）
    3. 聊天输入框特征（Ask … a question / prompt / 想聊点 …）

    浏览器场景：模型选择器签名只信 document 子树内（含 iframe 嵌套 document），
    排除浏览器外壳自带的 AI 按钮；输入框/声明/短文本签名全树扫描。
    """
    try:
        import uiautomation as auto
    except ImportError:
        return None
    try:
        root = auto.ControlFromHandle(hwnd)
        if root is None:
            return None
        queue = [(root, 0, False)]
        visited = 0
        while queue and visited < 3000:
            ctrl, depth, in_doc = queue.pop(0)
            if depth > 24:
                continue
            visited += 1
            name = ctrl.Name or ""
            ctype = ctrl.ControlTypeName
            if ctype == "DocumentControl":
                in_doc = True
            if in_doc and ctype in _PICKER_TYPES and _MODEL_RE.search(name):
                return f"model-picker:{name[:40]}"
            if ctype == "TextControl" and len(name) <= 40 and _MODEL_RE.search(name):
                return f"model-label:{name[:40]}"
            if len(name) <= 60 and _AI_DISCLAIMER_RE.search(name):
                return f"ai-disclaimer:{name[:40]}"
            if ctype == "TextControl" and len(name) <= 60 and _CHAT_INPUT_RE.search(name):
                return f"chat-heading:{name[:40]}"
            if ctype in ("EditControl", "CustomControl", "PaneControl"):
                try:
                    value = ctrl.GetValuePattern().Value or ""
                except Exception:
                    value = ""
                help_text = ctrl.HelpText or ""
                for field in (name, value, help_text):
                    if field and len(field) <= 60 and _CHAT_INPUT_RE.search(field):
                        return f"chat-input:{field[:40]}"
            child = ctrl.GetFirstChildControl()
            while child is not None:
                queue.append((child, depth + 1, in_doc))
                child = child.GetNextSiblingControl()
        return None
    except Exception:
        return None


class ForegroundWatcher:
    def __init__(self, cfg: dict, on_change, on_drag=None,
                 on_drag_start=None, on_drag_end=None):
        self.cfg = cfg
        self.on_change = on_change
        self.on_drag = on_drag
        self.on_drag_start = on_drag_start
        self.on_drag_end = on_drag_end
        self._stop = threading.Event()
        self._state = None
        self._hook = None
        self._proc = None
        self._drag_hook = None
        self._drag_proc = None
        self._mouse_hook = None
        self._mouse_proc = None
        self._mouse_tid = None
        self._drag_track = None
        self._drag_candidate = None
        self._mouse_events = 0
        self._mouse_events_logged = 0
        self._mouse_log_at = 0.0
        self.last_ai_hwnd = None
        self._threads = []
        self._heur_cache = None

    def _browsers(self) -> list[str]:
        return [b.lower() for b in self.cfg.get("ai_targets", {}).get("browsers", [])]

    def start(self):
        targets = [self._pump, self._poll]
        if self.on_drag and self.cfg.get("guard", {}).get("drag_warn", True):
            targets.append(self._mouse_pump)
        for target in targets:
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)
        self._evaluate()

    def stop(self):
        self._stop.set()
        if self._mouse_tid:
            try:
                win32api.PostThreadMessage(self._mouse_tid, win32con.WM_QUIT, 0, 0)
            except Exception:
                pass
        for t in self._threads:
            t.join(timeout=2)

    def _pump(self):
        # OUTOFCONTEXT 事件只投递到安装钩子的线程，钩子必须在本线程安装
        pythoncom.CoInitialize()
        try:
            self._proc = WinEventProc(self._on_event)
            self._hook = _user32.SetWinEventHook(
                EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND,
                None, self._proc, 0, 0, WINEVENT_OUTOFCONTEXT,
            )
            log.info("focus hook installed: %s (err=%s)", self._hook, _kernel32.GetLastError())
            if self.on_drag:
                self._drag_proc = WinEventProc(self._on_drag_event)
                self._drag_hook = _user32.SetWinEventHook(
                    EVENT_SYSTEM_DRAGDROPSTART, EVENT_SYSTEM_DRAGDROPSTART,
                    None, self._drag_proc, 0, 0, WINEVENT_OUTOFCONTEXT,
                )
                log.info("drag-start hook installed: %s", self._drag_hook)
            while not self._stop.is_set():
                win32gui.PumpWaitingMessages()
                self._stop.wait(0.05)
        finally:
            if self._hook:
                _user32.UnhookWinEvent(self._hook)
                self._hook = None
            if self._drag_hook:
                _user32.UnhookWinEvent(self._drag_hook)
                self._drag_hook = None
            pythoncom.CoUninitialize()

    def _mouse_pump(self):
        # 独立线程 + 阻塞 GetMessage：鼠标事件即时分发；
        # 与 _pump 共线程会被 50ms 泵间隔/UIA 重活延迟致系统鼠标卡顿
        pythoncom.CoInitialize()
        try:
            self._mouse_tid = win32api.GetCurrentThreadId()
            self._mouse_proc = MouseHookProc(self._mouse_cb)
            self._mouse_hook = _user32.SetWindowsHookExW(
                WH_MOUSE_LL, self._mouse_proc, None, 0,
            )
            log.info("mouse gesture hook installed: %s", self._mouse_hook)
            msg = _MSG()
            try:
                while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                    _user32.TranslateMessage(ctypes.byref(msg))
                    _user32.DispatchMessageW(ctypes.byref(msg))
            except Exception as e:
                log.exception("mouse pump loop error: %s", e)
            log.info("mouse pump exited")
        finally:
            if self._mouse_hook:
                _user32.UnhookWindowsHookEx(self._mouse_hook)
                self._mouse_hook = None
            pythoncom.CoUninitialize()

    def _poll(self):
        pythoncom.CoInitialize()
        try:
            last_title = None
            while not self._stop.wait(0.3):
                now = time.time()
                if now - self._mouse_log_at > 5 and self._mouse_events != self._mouse_events_logged:
                    log.info("mouse hook events=%d", self._mouse_events)
                    self._mouse_events_logged = self._mouse_events
                    self._mouse_log_at = now
                cand = self._drag_candidate
                if cand:
                    self._drag_candidate = None
                    log.info("drag candidate %s->%s", cand[0], cand[1])
                    try:
                        self._evaluate_drag(cand)
                    except Exception as e:
                        log.warning("drag evaluate error: %s", e)
                hwnd = win32gui.GetForegroundWindow()
                title = win32gui.GetWindowText(hwnd)
                # 浏览器内换 tab/导航、或任何应用标题变化时重新评估
                if process_name(hwnd) in self._browsers() or title != last_title:
                    last_title = title
                    self._evaluate(hwnd)
        finally:
            pythoncom.CoUninitialize()

    def _on_event(self, hook, event, hwnd, id_object, id_child, thread, ms):
        if id_object != 0 or not hwnd:
            return
        try:
            self._evaluate(hwnd)
        except Exception as e:
            log.warning("focus event error: %s", e)

    def _on_drag_event(self, hook, event, hwnd, id_object, id_child, thread, ms):
        # OLE 拖拽起点：无法拦截数据对象，但可在风险动作瞬间警告（拖拽不经过剪贴板）
        try:
            self.on_drag()
        except Exception as e:
            log.warning("drag event error: %s", e)

    def _root_at(self, x, y):
        try:
            h = win32gui.WindowFromPoint((x, y))
            return win32gui.GetAncestor(h, win32con.GA_ROOT) if h else 0
        except Exception:
            return 0

    def _mouse_cb(self, ncode, wparam, lparam):
        # LL 回调只做轻量记录；进程解析/分类留给 _poll 线程。
        # 落点用光标下窗口而非前台：拖入后台窗口不一定激活它
        if ncode >= 0:
            self._mouse_events += 1
            ms = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            x, y = ms.pt.x, ms.pt.y
            if wparam == WM_LBUTTONDOWN:
                self._drag_track = [self._root_at(x, y), x, y, time.time(), 0, 0]
            elif wparam == WM_MOUSEMOVE and self._drag_track:
                t = self._drag_track
                t[4] += abs(x - t[1]) + abs(y - t[2])
                t[1], t[2] = x, y
                if t[4] > 32 and not t[5]:
                    t[5] = 1
                    if self.on_drag_start:
                        try:
                            self.on_drag_start()
                        except Exception:
                            pass
            elif wparam == WM_LBUTTONUP and self._drag_track:
                t = self._drag_track
                self._drag_track = None
                if time.time() - t[3] > 0.2 and t[4] > 32:
                    self._drag_candidate = (t[0], self._root_at(x, y))
                if self.on_drag_end:
                    try:
                        self.on_drag_end()
                    except Exception:
                        pass
        return _user32.CallNextHookEx(self._mouse_hook, ncode, wparam, lparam)

    def _evaluate_drag(self, cand):
        start, end = cand
        if not start or not end or start == end:
            log.info("drag skip same/zero window (%s,%s)", start, end)
            return
        proc_s = process_name(start)
        proc_e = process_name(end)
        if not proc_e or proc_s == proc_e:
            log.info("drag skip same proc %s", proc_s)
            return  # 同应用内划选/框选，不是跨应用拖放
        title = win32gui.GetWindowText(end)
        url = browser_url(end) if proc_e in self._browsers() else None
        ai = classify_target(proc_e, url, self.cfg, title)
        if not ai and self._state and win32gui.GetForegroundWindow() == end:
            ai = True
        log.info("drag evaluate %s->%s ai=%s", proc_s, proc_e, ai)
        if ai:
            self.on_drag()

    def _is_newtab_chat(self, proc: str, url: str | None, title: str) -> bool:
        t = self.cfg.get("ai_targets", {})
        if proc not in [n.lower() for n in t.get("newtab_chat_browsers", [])]:
            return False
        newtab_titles = [s.lower() for s in t.get("newtab_titles", [])]
        # 窗口标题带 " - Browser" 后缀；地址栏 UIA Value 可能是占位文案而非空串
        prefix = (title or "").split(" - ")[0].strip().lower()
        return url == "" or prefix in newtab_titles

    def _ui_signature(self, hwnd, title: str) -> str | None:
        if not self.cfg.get("guard", {}).get("auto_detect", True):
            return None
        key = (hwnd, title)
        now = time.time()
        if self._heur_cache and self._heur_cache[0] == key and now - self._heur_cache[1] < 5:
            return self._heur_cache[2]
        result = ai_ui_signature(hwnd)
        self._heur_cache = (key, now, result)
        return result

    def _evaluate(self, hwnd=None):
        hwnd = hwnd or win32gui.GetForegroundWindow()
        if not hwnd:
            return
        proc = process_name(hwnd)
        title = win32gui.GetWindowText(hwnd)
        url = browser_url(hwnd) if proc in self._browsers() else None
        ai = classify_target(proc, url, self.cfg, title)
        sig = None
        if not ai and self._is_newtab_chat(proc, url, title):
            ai = True
        if not ai:
            sig = self._ui_signature(hwnd, title)
            ai = sig is not None
        if ai != self._state:
            # 日志不记标题/URL/控件原文：可能含 PII 或秘密（OWASP Logging）
            log.info("focus flip -> %s (proc=%s sig=%s)", ai, proc, sig.split(":")[0] if sig else None)
            self._state = ai
            if ai:
                self.last_ai_hwnd = hwnd
            self.on_change(ai)