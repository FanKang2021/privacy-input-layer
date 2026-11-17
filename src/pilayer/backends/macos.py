"""macOS backend: shares the engine with the Windows reference implementation.

Clipboard: NSPasteboard changeCount polling. Paste hook + injection: CGEventTap
(requires Accessibility permission; without it the guard degrades to
clipboard-compensation on copy). Focus: NSWorkspace frontmost app + AX scan.
"""

import logging
import threading
import time
from collections import deque

from AppKit import NSPasteboard, NSWorkspace, NSPasteboardTypeString
import Quartz

from ..config import app_dir, load_config
from ..engine import MappingStore, TextMasker, PLACEHOLDER_RE
from ..engine.rules import _MODEL_RE, _AI_DISCLAIMER_RE, _CHAT_INPUT_RE
from ..i18n import set_language, t

log = logging.getLogger("pilayer.macos")

BUNDLES = [
    "com.openai.chat", "com.anthropic.claudefordesktop", "com.qoder.qoder",
    "com.qoder.qodercn", "com.todesktop.230313mzl4w4u92", "com.cursor.Cursor",
    "com.exafunction.windsurf", "com.trae.app", "com.workbuddy.app",
    "com.bytedance.doubao", "com.moonshot.kimi", "com.alibaba.tongyi",
    "com.deepseek.chat", "com.tencent.yuanbao", "com.zhipu.chatglm",
    "com.google.Gemini", "com.microsoft.Copilot",
]


def _ax_trusted() -> bool:
    try:
        import ApplicationServices as AS
        return bool(AS.AXIsProcessTrusted())
    except Exception:
        return False


def classify_mac(bundle: str, name: str, cfg: dict) -> bool:
    t_cfg = cfg.get("ai_targets", {})
    if bundle.lower() in [b.lower() for b in BUNDLES + t_cfg.get("processes", [])]:
        return True
    if bundle.lower() in [b.lower() for b in t_cfg.get("learned_processes", [])]:
        return True
    for pat in t_cfg.get("title_patterns", []):
        if pat.lower() in name.lower():
            return True
    return False


def ax_signature(pid) -> str | None:
    """Best-effort Accessibility scan for AI-conversation signatures."""
    try:
        import ApplicationServices as AS
        app = AS.AXUIElementCreateApplication(pid)
        queue = [(app, 0)]
        seen = 0
        while queue and seen < 800:
            el, depth = queue.pop(0)
            if depth > 12:
                continue
            seen += 1
            err, children = AS.AXUIElementCopyAttributeValue(el, "AXChildren", None)
            if err == 0 and children:
                for c in children:
                    queue.append((c, depth + 1))
            err, role = AS.AXUIElementCopyAttributeValue(el, "AXRole", None)
            err, name = AS.AXUIElementCopyAttributeValue(el, "AXTitle", None)
            if err or not name:
                err, name = AS.AXUIElementCopyAttributeValue(el, "AXValue", None)
            if err or not isinstance(name, str):
                continue
            if role in ("AXComboBox", "AXButton", "AXMenuItem") and _MODEL_RE.search(name):
                return f"model-picker:{name[:40]}"
            if len(name) <= 60 and _AI_DISCLAIMER_RE.search(name):
                return f"ai-disclaimer:{name[:40]}"
            if role in ("AXTextField", "AXTextArea") and _CHAT_INPUT_RE.search(name):
                return f"chat-input:{name[:40]}"
        return None
    except Exception:
        return None


class MacGuard:
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
        self.mode = self.cfg["guard"].get("mode", "focus")
        self._stop = threading.Event()
        self._pb = NSPasteboard.generalPasteboard()
        self._change = self._pb.changeCount()
        self._trusted = _ax_trusted()
        self.icon = None

    # ---------- clipboard ----------

    def read_text(self):
        return self._pb.stringForType_(NSPasteboardTypeString)

    def write_text(self, text):
        self._pb.clearContents()
        self._pb.setString_forType_(text, NSPasteboardTypeString)
        self._change = self._pb.changeCount()

    # ---------- focus ----------

    def _frontmost(self):
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return "", "", 0
        return (app.bundleIdentifier() or "", app.localizedName() or "", app.processIdentifier())

    def _classify(self, bundle, name, pid):
        return classify_mac(bundle, name, self.cfg) or ax_signature(pid) is not None

    # ---------- injection ----------

    def send_text(self, text):
        if not self._trusted:
            return False
        for ch in text:
            for down in (True, False):
                ev = Quartz.CGEventCreateKeyboardEvent(None, 0, down)
                Quartz.CGEventKeyboardSetUnicodeString(ev, 1, ch)
                Quartz.CGEventPost(Quartz.kCGSessionEventTap, ev)
        return True

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
        self.events.appendleft(f"{time.strftime('%H:%M:%S')} {'masked' if self.ai_focused else 'restored'} {r.count}")
        if self.send_text(r.text):
            return True
        self.write_text(r.text)
        return False

    # ---------- loops ----------

    def _tap_callback(self, proxy, etype, event, refcon):
        try:
            if etype == Quartz.kCGEventKeyDown:
                code = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
                flags = Quartz.CGEventGetFlags(event)
                if code == 9 and (flags & Quartz.kCGEventFlagMaskCommand):  # Cmd+V
                    if self._handle_paste():
                        return None
        except Exception as e:
            log.warning("tap error: %s", e)
        return event

    def _tap_loop(self):
        mask = Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault, mask, self._tap_callback, None,
        )
        if not tap:
            log.warning("CGEventTap unavailable (Accessibility permission?)")
            return
        src = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetCurrent(), src, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(tap, True)
        Quartz.CFRunLoopRun()

    def _poll_loop(self):
        while not self._stop.wait(0.3):
            try:
                cc = self._pb.changeCount()
                if cc != self._change:
                    self._change = cc
                    self._on_copy()
                bundle, name, pid = self._frontmost()
                ai = self._classify(bundle, name, pid) if self.mode == "focus" else True
                if ai != self.ai_focused:
                    self.ai_focused = ai
                    if ai:
                        self._on_copy()
            except Exception as e:
                log.warning("poll error: %s", e)

    def _on_copy(self):
        if not self.enabled:
            return
        if self._mask_clipboard_image():
            return
        text = self.read_text()
        if not text:
            return
        if self.mode == "focus" and not self.ai_focused:
            return  # injection restores on paste; clipboard never holds our plaintext
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

    def _mask_clipboard_image(self) -> bool:
        from AppKit import NSPasteboardTypeTIFF, NSPasteboardTypePNG
        types = self._pb.types() or []
        has_img = NSPasteboardTypeTIFF in types or NSPasteboardTypePNG in types
        if not has_img:
            return False
        if self.mode == "focus" and not self.ai_focused:
            return False
        data = self._pb.dataForType_(NSPasteboardTypePNG) or self._pb.dataForType_(NSPasteboardTypeTIFF)
        if not data:
            return False
        import io
        from PIL import Image
        from ..engine.image import ImageMasker
        try:
            img = Image.open(io.BytesIO(bytes(data)))
            im = ImageMasker(self.masker.rules_cfg, self.masker.keywords)
            masked, count = im.mask(img)
            if not count:
                return False
            buf = io.BytesIO()
            masked.convert("RGB").save(buf, format="PNG")
            self._pb.clearContents()
            self._pb.setData_forType_(buf.getvalue(), NSPasteboardTypePNG)
            self.events.appendleft(f"{time.strftime('%H:%M:%S')} image masked {count}")
            return True
        except Exception as e:
            log.warning("mac image mask error: %s", e)
            return False

    def start(self):
        threading.Thread(target=self._poll_loop, daemon=True).start()
        if self._trusted:
            threading.Thread(target=self._tap_loop, daemon=True).start()
        else:
            log.warning("Accessibility not trusted; paste hook disabled, clipboard compensation active")

    def stop(self):
        self._stop.set()

class MacApp:
    def __init__(self, config_path=None):
        self.guard = MacGuard(config_path)
        self.icon = None

    def notify(self, title, msg):
        if self.guard.cfg["guard"].get("notify") and self.icon:
            try:
                self.icon.notify(msg, title)
            except Exception:
                pass

    def _toggle(self, icon, item):
        self.guard.enabled = not self.guard.enabled
        self.notify("privacy-input-layer", t("guard_state_on") if self.guard.enabled else t("guard_state_paused"))

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
