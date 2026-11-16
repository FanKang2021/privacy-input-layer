"""Linux backend: X11 full feature; Wayland degraded (clipboard-only, always-on).

X11: XFixes selection events, XGrabKey paste hook, xdotool injection (fallback:
clipboard write), _NET_ACTIVE_WINDOW focus. Wayland's security model forbids
global input injection / foreground queries, so the guard degrades honestly.
"""

import logging
import os
import shutil
import subprocess
import threading
import time
from collections import deque

from ..config import app_dir, load_config
from ..engine import MappingStore, TextMasker
from ..i18n import set_language, t

log = logging.getLogger("pilayer.linux")

WM_CLASSES = [
    "qoder", "cursor", "claude", "chatgpt", "windsurf", "trae", "codebuddy",
    "workbuddy", "comate", "lingma", "doubao", "kimi", "tongyi", "deepseek",
    "yuanbao", "chatglm", "minimax", "lm studio", "jan", "cherry studio",
    "chatbox", "anythingllm", "msty", "copilot", "gemini",
]


def classify_linux(cls: str, name: str, cfg: dict) -> bool:
    t_cfg = cfg.get("ai_targets", {})
    for pat in WM_CLASSES + [p.lower() for p in t_cfg.get("processes", [])]:
        if pat in cls:
            return True
    if cls in [p.lower() for p in t_cfg.get("learned_processes", [])]:
        return True
    for pat in t_cfg.get("title_patterns", []):
        if pat.lower() in name.lower():
            return True
    return False


class LinuxGuard:
    def __init__(self, config_path=None):
        self.cfg = load_config(config_path)
        set_language(self.cfg.get("ui", {}).get("language", "en"))
        self.dir = app_dir()
        self.store = MappingStore(self.dir / "mappings.db")
        ttl = self.cfg.get("store", {}).get("ttl_days", 30)
        if ttl > 0:
            self.store.purge_expired(ttl)
        self.masker = TextMasker(
            self.store, self.cfg["rules"], self.cfg["rules"].get("custom_keywords") or []
        )
        self.events = deque(maxlen=20)
        self.enabled = True
        self.ai_focused = False
        self.wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        self.mode = "always" if self.wayland else self.cfg["guard"].get("mode", "focus")
        self._stop = threading.Event()
        self._sel_text = None
        self._read_result = None
        self._read_done = threading.Event()
        self._last_clip = None
        if not self.wayland:
            from Xlib import display, X
            from Xlib.ext import xfixes
            self._X = X
            self.d = display.Display()
            self.root = self.d.screen().root
            self.win = self.root.create_window(
                -1, -1, 1, 1, 0, self.d.screen().root_depth,
                X.CopyFromParent, X.CopyFromParent,
                event_mask=X.PropertyChangeMask,
            )
            self.CLIP = self.d.intern_atom("CLIPBOARD")
            self.UTF8 = self.d.intern_atom("UTF8_STRING")
            self.PROP = self.d.intern_atom("PILAYER_SEL")
            self.ACTIVE = self.d.intern_atom("_NET_ACTIVE_WINDOW")
            self.WMCLASS = self.d.intern_atom("WM_CLASS")
            self.NETNAME = self.d.intern_atom("_NET_WM_NAME")
            self.d.xfixes_query_version(5, 0)
            xfixes.select_selection_input(
                self.d, self.win, self.CLIP,
                xfixes.XFixesSetSelectionOwnerNotifyMask,
            )
            kc = self.d.keysym_to_keycode(0x76)  # v
            self.root.grab_key(kc, X.ControlMask, True, X.GrabModeAsync, X.GrabModeAsync)
            ki = self.d.keysym_to_keycode(0xff63)  # Insert
            self.root.grab_key(ki, X.ShiftMask, True, X.GrabModeAsync, X.GrabModeAsync)
            self._kc_v, self._kc_i = kc, ki

    # ---------- clipboard ----------

    def read_text(self):
        if self.wayland:
            r = subprocess.run(["wl-paste", "--no-newline"], capture_output=True, text=True)
            return r.stdout if r.returncode == 0 else None
        self._read_done.clear()
        self._read_result = None
        self.win.convert_selection(self.CLIP, self.UTF8, self.PROP, self._X.CurrentTime)
        self.d.flush()
        if not self._read_done.wait(0.6):
            return None
        return self._read_result

    def write_text(self, text):
        if self.wayland:
            subprocess.run(["wl-copy"], input=text, text=True, capture_output=True)
            self._last_clip = text
            return
        self._sel_text = text
        self.win.set_selection_owner(self.CLIP, self._X.CurrentTime)
        self.d.flush()

    # ---------- focus ----------

    def _frontmost(self):
        prop = self.root.get_full_property(self.ACTIVE, self._X.AnyPropertyType)
        if not prop or not prop.value:
            return "", ""
        wid = prop.value[0]
        try:
            w = self.d.create_resource_object("window", wid)
            cls = w.get_full_property(self.WMCLASS, self._X.AnyPropertyType)
            name = w.get_full_property(self.NETNAME, self.UTF8)
            cls_s = bytes(cls.value).decode("utf-8", "replace").lower() if cls else ""
            name_s = bytes(name.value).decode("utf-8", "replace") if name else ""
            return cls_s, name_s
        except Exception:
            return "", ""

    def _classify(self, cls, name):
        return classify_linux(cls, name, self.cfg)

    # ---------- paste ----------

    def send_text(self, text):
        if not shutil.which("xdotool"):
            return False
        r = subprocess.run(
            ["xdotool", "type", "--clearmodifiers", "--delay", "1", text],
            capture_output=True,
        )
        return r.returncode == 0

    def _handle_paste(self):
        if not self.enabled:
            return False
        text = self.read_text()
        if not text:
            return False
        if self.mode == "focus":
            r = self.masker.mask(text) if self.ai_focused else self.masker.restore(text)
        elif self.cfg["guard"].get("auto_restore") and self.masker.has_placeholder(text):
            r = self.masker.restore(text)
        else:
            r = self.masker.mask(text)
        if r.text == text:
            return False
        self.events.appendleft(f"{time.strftime('%H:%M:%S')} paste {r.count}")
        if self.send_text(r.text):
            return True
        self.write_text(r.text)
        return False

    def _on_copy(self):
        if not self.enabled:
            return
        text = self.read_text()
        if not text:
            return
        if self.mode == "focus" and not self.ai_focused:
            return
        if self.masker.has_placeholder(text) and self.cfg["guard"].get("auto_restore"):
            r = self.masker.restore(text)
            if r.count:
                self.write_text(r.text)
                self.events.appendleft(f"{time.strftime('%H:%M:%S')} restored {r.count}")
            return
        r = self.masker.mask(text)
        if r.count:
            self.write_text(r.text)
            kinds = "/".join(sorted(set(r.kinds)))
            self.events.appendleft(f"{time.strftime('%H:%M:%S')} masked {r.count} ({kinds})")

    # ---------- event loop ----------

    def _serve_selection(self, ev):
        from Xlib import X
        from Xlib.protocol import event
        if ev.target == self.UTF8 and self._sel_text is not None:
            ev.requestor.change_property(ev.property, self.UTF8, 8, self._sel_text.encode("utf-8"))
            prop = ev.property
        else:
            prop = X.NONE
        notify = event.SelectionNotify(
            time=X.CurrentTime, requestor=ev.requestor,
            selection=ev.selection, target=ev.target, property=prop,
        )
        ev.requestor.send_event(notify)
        self.d.flush()

    def _loop(self):
        from Xlib import X
        while not self._stop.is_set():
            while self.d.pending_events():
                ev = self.d.next_event()
                if ev.type == X.SelectionNotify:
                    prop = self.win.get_full_property(self.PROP, self.UTF8)
                    self.win.delete_property(self.PROP)
                    self._read_result = bytes(prop.value).decode("utf-8", "replace") if prop else None
                    self._read_done.set()
                elif ev.type == X.SelectionRequest:
                    self._serve_selection(ev)
                elif ev.type == X.SelectionClear:
                    self._sel_text = None
                elif ev.type == X.KeyPress:
                    # grab 已消费按键；worker 决定是否注入，未处理则补发原键
                    threading.Thread(target=self._paste_worker, args=(ev.detail,), daemon=True).start()
                elif ev.type == self.d.xfixes_event_base + 0:  # XFixesSelectionNotify
                    threading.Thread(target=self._on_copy, daemon=True).start()
            if not self.wayland:
                cls, name = self._frontmost()
                ai = self._classify(cls, name) if self.mode == "focus" else True
                if ai != self.ai_focused:
                    self.ai_focused = ai
                    if ai:
                        threading.Thread(target=self._on_copy, daemon=True).start()
            self._stop.wait(0.02)

    def _paste_worker(self, detail):
        from Xlib import X
        from Xlib.ext import xtest
        if not self._handle_paste():
            mod = X.ControlMask if detail == self._kc_v else X.ShiftMask
            xtest.fake_input(self.d, X.KeyPress, detail, mod)
            xtest.fake_input(self.d, X.KeyRelease, detail, mod)
            self.d.flush()

    def _wayland_loop(self):
        while not self._stop.wait(0.3):
            text = self.read_text()
            if text != self._last_clip:
                self._last_clip = text
                self._on_copy()

    def start(self):
        if self.wayland:
            log.warning("Wayland: degraded clipboard-only always-on mode")
            threading.Thread(target=self._wayland_loop, daemon=True).start()
        else:
            threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._stop.set()


class LinuxApp:
    def __init__(self, config_path=None):
        self.guard = LinuxGuard(config_path)
        self.icon = None

    def notify(self, title, msg):
        if self.guard.cfg["guard"].get("notify") and self.icon:
            try:
                self.icon.notify(msg, title)
            except Exception:
                pass

    def _toggle(self, icon, item):
        self.guard.enabled = not self.guard.enabled

    def _toggle_notify(self, icon, item):
        self.guard.cfg["guard"]["notify"] = not self.guard.cfg["guard"].get("notify", True)
        self._save()
        icon.update_menu()

    def _toggle_language(self, icon, item):
        lang = "zh" if self.guard.cfg.get("ui", {}).get("language", "en") == "en" else "en"
        self.guard.cfg.setdefault("ui", {})["language"] = lang
        set_language(lang)
        self._save()
        icon.update_menu()

    def _save(self):
        import yaml
        (self.guard.dir / "config.yaml").write_text(
            yaml.safe_dump(self.guard.cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    def _recent(self):
        import pystray
        entries = list(self.guard.events)[:5]
        if not entries:
            return pystray.Menu(pystray.MenuItem(lambda item: t("recent_empty"), None, enabled=False))
        return pystray.Menu(*[pystray.MenuItem(lambda item, s=s: s, None, enabled=False) for s in entries])

    def _quit(self, icon, item):
        self.guard.stop()
        icon.stop()
        self.guard.store.close()

    def run(self):
        import pystray
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.polygon([(32, 4), (58, 14), (58, 34), (32, 60), (6, 34), (6, 14)], fill=(34, 139, 230, 255))
        d.line([(20, 30), (29, 40), (46, 20)], fill=(255, 255, 255, 255), width=6)
        menu = pystray.Menu(
            pystray.MenuItem(lambda item: t("guard_on") if self.guard.enabled else t("guard_paused"), self._toggle, default=True),
            pystray.MenuItem(lambda item: t("notify_on") if self.guard.cfg["guard"].get("notify") else t("notify_off"), self._toggle_notify),
            pystray.MenuItem(lambda item: t("language"), self._toggle_language),
            pystray.MenuItem(lambda item: t("recent"), self._recent()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda item: t("quit"), self._quit),
        )
        self.icon = pystray.Icon("pilayer", img, "privacy-input-layer", menu=menu)
        self.icon.run(setup=lambda icon: self.guard.start())