"""Linux backend: X11 full feature; Wayland degraded (clipboard-only, always-on).

Clipboard I/O delegates to xclip/xsel (robust C selection implementation);
change detection polls. Xlib is used only for XGrabKey paste hook and
_NET_ACTIVE_WINDOW focus (core requests). Injection via xdotool.
Wayland's security model forbids global injection / foreground queries, so the
guard degrades honestly to clipboard-only always-on (wl-clipboard).
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


def _clip_tool():
    for tool in ("xclip", "xsel"):
        if shutil.which(tool):
            return tool
    return None


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
        self._last_clip = None
        self._tool = None if self.wayland else _clip_tool()
        self._d = None
        self._kc_v = self._kc_i = None
        if not self.wayland:
            if not self._tool:
                log.warning("xclip/xsel not found; clipboard guard inactive")
            try:
                from Xlib import display, X
                self._X = X
                self._d = display.Display()
                root = self._d.screen().root
                self._root = root
                self._ACTIVE = self._d.intern_atom("_NET_ACTIVE_WINDOW")
                self._WMCLASS = self._d.intern_atom("WM_CLASS")
                self._NETNAME = self._d.intern_atom("_NET_WM_NAME")
                self._UTF8 = self._d.intern_atom("UTF8_STRING")
                kc = self._d.keysym_to_keycode(0x76)  # v
                root.grab_key(kc, X.ControlMask, True, X.GrabModeAsync, X.GrabModeAsync)
                ki = self._d.keysym_to_keycode(0xff63)  # Insert
                root.grab_key(ki, X.ShiftMask, True, X.GrabModeAsync, X.GrabModeAsync)
                self._kc_v, self._kc_i = kc, ki
            except Exception as e:
                log.warning("X11 hook unavailable: %s", e)
                self._d = None

    # ---------- clipboard ----------

    def read_text(self):
        if self.wayland:
            r = subprocess.run(["wl-paste", "--no-newline"], capture_output=True, text=True, timeout=5)
            return r.stdout if r.returncode == 0 else None
        if not self._tool:
            return None
        if self._tool == "xclip":
            r = subprocess.run(["xclip", "-selection", "clipboard", "-o"],
                               capture_output=True, text=True, timeout=5)
        else:
            r = subprocess.run(["xsel", "--clipboard", "--output"],
                               capture_output=True, text=True, timeout=5)
        return r.stdout if r.returncode == 0 else None

    def write_text(self, text):
        if self.wayland:
            subprocess.run(["wl-copy"], input=text, text=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            self._last_clip = text
            return
        if not self._tool:
            return
        # xclip/xsel -i 会 fork 守护进程持有 selection；若继承 capture 管道会令
        # subprocess.run 等待 EOF 永久挂起 → 写路径一律 DEVNULL
        if self._tool == "xclip":
            subprocess.run(["xclip", "-selection", "clipboard", "-i"],
                           input=text, text=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        else:
            subprocess.run(["xsel", "--clipboard", "--input"],
                           input=text, text=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        self._last_clip = text

    # ---------- focus ----------

    def _frontmost(self):
        if self._d is None:
            return "", ""
        try:
            prop = self._root.get_full_property(self._ACTIVE, self._X.AnyPropertyType)
            if not prop or not prop.value:
                return "", ""
            w = self._d.create_resource_object("window", prop.value[0])
            cls = w.get_full_property(self._WMCLASS, self._X.AnyPropertyType)
            name = w.get_full_property(self._NETNAME, self._UTF8)
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
            capture_output=True, timeout=10,
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

    # ---------- loop ----------

    def _loop(self):
        from Xlib import X
        while not self._stop.is_set():
            try:
                while self._d.pending_events():
                    ev = self._d.next_event()
                    if ev.type == X.KeyPress:
                        threading.Thread(
                            target=self._paste_worker, args=(ev.detail,), daemon=True
                        ).start()
            except Exception as e:
                log.warning("X loop error: %s", e)
            text = self.read_text()
            if text != self._last_clip:
                self._last_clip = text
                self._on_copy()
            cls, name = self._frontmost()
            ai = self._classify(cls, name) if self.mode == "focus" else True
            if ai != self.ai_focused:
                self.ai_focused = ai
                if ai:
                    self._on_copy()
            self._stop.wait(0.3)

    def _paste_worker(self, detail):
        if not self._handle_paste():
            try:
                from Xlib.ext import xtest
                mod = self._X.ControlMask if detail == self._kc_v else self._X.ShiftMask
                xtest.fake_input(self._d, self._X.KeyPress, detail, mod)
                xtest.fake_input(self._d, self._X.KeyRelease, detail, mod)
                self._d.flush()
            except Exception as e:
                log.warning("key resend error: %s", e)

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
        elif self._tool:
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