"""托盘应用：常驻守卫 + 开关 + 通知。"""

import ctypes
import logging
import os
import time

import pystray
from PIL import Image, ImageDraw

from .clipboard import ClipboardWatcher
from .config import app_dir, load_config
from .engine import MappingStore, TextMasker
from .engine.image import ImageMasker
from .i18n import set_language, t

log = logging.getLogger("pilayer")


def _icon_image(active: bool) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = (34, 139, 230, 255) if active else (130, 130, 130, 255)
    d.polygon([(32, 4), (58, 14), (58, 34), (32, 60), (6, 34), (6, 14)], fill=color)
    d.line([(20, 30), (29, 40), (46, 20)], fill=(255, 255, 255, 255), width=6)
    return img


class Application:
    def __init__(self, config_path=None):
        self.cfg = load_config(config_path)
        set_language(self.cfg.get("ui", {}).get("language", "en"))
        self.dir = app_dir()
        self.store = MappingStore(self.dir / "mappings.db")
        ttl = self.cfg.get("store", {}).get("ttl_days", 30)
        if ttl > 0:
            purged = self.store.purge_expired(ttl)
            if purged:
                log.info("purged %d expired mapping(s)", purged)
            copies = self.dir / "copies"
            if copies.exists():
                cutoff = time.time() - ttl * 86400
                for f in copies.iterdir():
                    if f.is_file() and f.stat().st_mtime < cutoff:
                        f.unlink()
        keywords = self.cfg["rules"].get("custom_keywords") or []
        self.masker = TextMasker(self.store, self.cfg["rules"], keywords)
        self.image_masker = ImageMasker(
            self.cfg["rules"], keywords,
            self.cfg["image"]["min_score"], self.cfg["image"]["fill"],
        )
        self.watcher = ClipboardWatcher(
            self.masker, self.image_masker, self.cfg["guard"],
            self.dir / "copies", self.cfg["files"]["suffix"],
            notify=self.notify,
        )
        self.focus = None
        if self.cfg["guard"].get("mode", "focus") == "focus":
            from .focus import ForegroundWatcher
            self.focus = ForegroundWatcher(self.cfg, self._on_focus)
        self.paste_hook = None
        if self.cfg["guard"].get("paste_hook", True):
            from .clipboard.paste_hook import PasteHook
            self.paste_hook = PasteHook(self.watcher.ensure_for_paste)
        self.icon = None

    def _on_focus(self, ai: bool):
        msg = self.watcher.set_focus(ai)
        log.info("on_focus ai=%s result=%s", ai, msg)
        if msg:
            prefix = t("focus_ai") if ai else t("focus_left")
            self.notify("privacy-input-layer", prefix + msg)

    def notify(self, title: str, msg: str):
        if self.cfg["guard"].get("notify") and self.icon:
            try:
                self.icon.notify(msg, title)
            except Exception:
                pass

    def _toggle(self, icon, item):
        self.watcher.enabled = not self.watcher.enabled
        icon.icon = _icon_image(self.watcher.enabled)
        state = t("guard_state_on") if self.watcher.enabled else t("guard_state_paused")
        self.notify("privacy-input-layer", state)

    def _status_text(self, item):
        return t("guard_on") if self.watcher.enabled else t("guard_paused")

    def _notify_text(self, item):
        return t("notify_on") if self.cfg["guard"].get("notify") else t("notify_off")

    def _toggle_notify(self, icon, item):
        self.cfg["guard"]["notify"] = not self.cfg["guard"].get("notify", True)
        self._save_config()
        icon.update_menu()

    def _toggle_language(self, icon, item):
        lang = "zh" if self.cfg.get("ui", {}).get("language", "en") == "en" else "en"
        self.cfg.setdefault("ui", {})["language"] = lang
        set_language(lang)
        self._save_config()
        icon.update_menu()

    def _save_config(self):
        import yaml
        (self.dir / "config.yaml").write_text(
            yaml.safe_dump(self.cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    def _menu(self):
        return pystray.Menu(
            pystray.MenuItem(self._status_text, self._toggle, default=True),
            pystray.MenuItem(self._notify_text, self._toggle_notify),
            pystray.MenuItem(lambda item: t("language"), self._toggle_language),
            pystray.MenuItem(lambda item: t("open_config"), lambda: os.startfile(str(self.dir / "config.yaml"))),
            pystray.MenuItem(lambda item: t("open_data"), lambda: os.startfile(str(self.dir))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda item: t("quit"), self._quit),
        )

    def _quit(self, icon, item):
        if self.paste_hook:
            self.paste_hook.stop()
        if self.focus:
            self.focus.stop()
        self.watcher.stop()
        icon.stop()
        self.store.close()

    def _setup(self, icon):
        # pystray 自定义 setup 不会自动置 visible，不显式开启则不会注册托盘图标
        icon.visible = True
        if self._promote_tray_icon():
            # explorer 仅在图标注册时读取 IsPromoted，提升后需重新注册才可见
            icon.visible = False
            icon.visible = True
        self.watcher.start()
        if self.paste_hook:
            self.paste_hook.start()
        if self.focus:
            self.focus.start()

    def _promote_tray_icon(self) -> bool:
        # Win11 默认隐藏新托盘图标（IsPromoted 空），只提升本应用自己的条目
        import sys
        import winreg

        for _ in range(10):
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, r"Control Panel\NotifyIconSettings",
                    0, winreg.KEY_READ,
                ) as k:
                    for i in range(winreg.QueryInfoKey(k)[0]):
                        sub = winreg.EnumKey(k, i)
                        with winreg.OpenKey(k, sub, 0, winreg.KEY_READ | winreg.KEY_WRITE) as sk:
                            try:
                                tip, _ = winreg.QueryValueEx(sk, "InitialTooltip")
                            except FileNotFoundError:
                                continue
                            if tip == "privacy-input-layer":
                                winreg.SetValueEx(sk, "IsPromoted", 0, winreg.REG_DWORD, 1)
                                return True
            except OSError:
                pass
            time.sleep(0.3)
        return False

    def run(self):
        logging.basicConfig(
            filename=str(self.dir / "pilayer.log"),
            level=logging.INFO,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )
        log.info("guard starting, mode=%s", self.cfg["guard"].get("mode", "focus"))
        # 单实例：重复启动时静默退出，避免两个守卫互相改写剪贴板
        kernel32 = ctypes.windll.kernel32
        self._mutex = kernel32.CreateMutexW(None, False, "PilayerSingleInstance")
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            log.info("another instance running, exit")
            return
        self.icon = pystray.Icon(
            "pilayer", _icon_image(True), "privacy-input-layer", menu=self._menu()
        )
        self.icon.run(setup=self._setup)