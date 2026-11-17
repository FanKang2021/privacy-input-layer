"""托盘应用：常驻守卫 + 开关 + 通知。"""

import ctypes
import logging
import os
import sys
import threading
import time
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from .clipboard.watcher import ClipboardWatcher
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
            notify=self.notify, on_learn=self._on_learn, ai_cfg=self.cfg,
            on_event=self._refresh_menu,
        )
        self.focus = None
        if self.cfg["guard"].get("mode", "focus") == "focus":
            from .focus import ForegroundWatcher
            self.focus = ForegroundWatcher(self.cfg, self._on_focus, on_drag=self._on_drag)
        self.paste_hook = None
        if self.cfg["guard"].get("paste_hook", True):
            from .clipboard.paste_hook import PasteHook
            self.paste_hook = PasteHook(self.watcher.handle_paste, self.watcher.drain_injection)
            self.watcher.resend_cb = lambda: self.paste_hook._resend(*self.paste_hook._last_combo)
        self.icon = None
        self._update = None

    def _on_learn(self, proc: str):
        learned = self.cfg.setdefault("ai_targets", {}).setdefault("learned_processes", [])
        if proc in learned:
            return
        learned.append(proc)
        self._save_config()
        log.info("learned AI client: %s", proc)
        self.notify("privacy-input-layer", t("learned", proc=proc))

    def _on_focus(self, ai: bool):
        msg = self.watcher.set_focus(ai)
        log.info("on_focus ai=%s result=%s", ai, msg)
        if msg:
            prefix = t("focus_ai") if ai else t("focus_left")
            self.notify("privacy-input-layer", prefix + msg)

    def _on_drag(self):
        if not self.cfg["guard"].get("drag_warn", True) or not self.watcher.enabled:
            return
        now = time.time()
        if now - getattr(self, "_last_drag_warn", 0) < 60:
            return
        self._last_drag_warn = now
        log.info("drag-start warning issued")
        self.notify("privacy-input-layer", t("drag_warn"))

    def notify(self, title: str, msg: str):
        if self.cfg["guard"].get("notify") and self.icon:
            try:
                self.icon.notify(msg, title)
            except Exception:
                pass

    def _refresh_menu(self):
        if self.icon:
            try:
                # 子菜单是 Menu 实例快照：update_menu 只重渲染旧树，
                # 必须重建整棵描述符才能刷新事件流水（setter 自带 update_menu）
                self.icon.menu = self._menu()
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

    def _autostart_enabled(self) -> bool:
        import winreg
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
            ) as k:
                winreg.QueryValueEx(k, "Pilayer")
            return True
        except OSError:
            return False

    def _set_autostart(self, enable: bool):
        import sys
        import winreg
        exe = Path(sys.executable).with_name("pythonw.exe")
        cmd = f'"{exe if exe.exists() else sys.executable}" -m pilayer run'
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        ) as k:
            if enable:
                winreg.SetValueEx(k, "Pilayer", 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(k, "Pilayer")
                except FileNotFoundError:
                    pass

    def _toggle_autostart(self, icon, item):
        self._set_autostart(not self._autostart_enabled())
        icon.update_menu()

    def _recent_menu(self):
        entries = list(self.watcher.events)[:5]
        if not entries:
            return pystray.Menu(pystray.MenuItem(lambda item: t("recent_empty"), None, enabled=False))
        return pystray.Menu(*[
            pystray.MenuItem(lambda item, s=s: s, None, enabled=False) for s in entries
        ])

    def _restore_now(self, icon, item):
        msg = self.watcher._restore_text_current()
        self.notify("privacy-input-layer", msg or t("nothing_restore"))

    def _mask_files(self, icon, item):
        threading.Thread(target=self._mask_files_work, daemon=True).start()

    def _install_sendto(self, icon, item):
        from .cli import install_sendto
        try:
            bat = install_sendto()
        except Exception as e:
            log.warning("install sendto: %s", e)
            return
        self.notify("privacy-input-layer", t("sendto_done", path=bat))

    def _mask_files_work(self):
        """拖拽走 OLE 不经过剪贴板，无法透明拦截；提供手动脱敏副本出口。"""
        import ctypes
        from ctypes import wintypes
        import win32con
        from .files import SUPPORTED_EXTS, UnsupportedFile, mask_file

        class OFN(ctypes.Structure):
            _fields_ = [
                ("lStructSize", wintypes.DWORD),
                ("hwndOwner", wintypes.HWND),
                ("hInstance", wintypes.HANDLE),
                ("lpstrFilter", wintypes.LPCWSTR),
                ("lpstrCustomFilter", wintypes.LPWSTR),
                ("nMaxCustFilter", wintypes.DWORD),
                ("nFilterIndex", wintypes.DWORD),
                ("lpstrFile", wintypes.LPWSTR),
                ("nMaxFile", wintypes.DWORD),
                ("lpstrFileTitle", wintypes.LPWSTR),
                ("nMaxFileTitle", wintypes.DWORD),
                ("lpstrInitialDir", wintypes.LPCWSTR),
                ("lpstrTitle", wintypes.LPCWSTR),
                ("Flags", wintypes.DWORD),
                ("nFileOffset", wintypes.WORD),
                ("nFileExtension", wintypes.WORD),
                ("lpstrDefExt", wintypes.LPCWSTR),
                ("lCustData", wintypes.LPARAM),
                ("lpfnHook", ctypes.c_void_p),
                ("lpTemplateName", wintypes.LPCWSTR),
                ("pvReserved", ctypes.c_void_p),
                ("dwReserved", wintypes.DWORD),
                ("FlagsEx", wintypes.DWORD),
            ]

        buf = ctypes.create_unicode_buffer(4096)
        ofn = OFN()
        ofn.lStructSize = ctypes.sizeof(OFN)
        ofn.lpstrFilter = "Supported\0*" + ";*".join(sorted(SUPPORTED_EXTS)) + "\0All files\0*.*\0"
        ofn.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
        ofn.nMaxFile = 4096
        ofn.lpstrTitle = t("mask_files")
        ofn.Flags = (win32con.OFN_EXPLORER | win32con.OFN_FILEMUSTEXIST
                     | win32con.OFN_PATHMUSTEXIST | win32con.OFN_NOCHANGEDIR)
        fn = ctypes.windll.comdlg32.GetOpenFileNameW
        fn.argtypes = [ctypes.POINTER(OFN)]
        fn.restype = wintypes.BOOL
        if not fn(ctypes.byref(ofn)):
            return
        src = Path(buf.value)
        self.watcher.copies_dir.mkdir(parents=True, exist_ok=True)
        dst = self.watcher.copies_dir / (src.stem + self.watcher.file_suffix + src.suffix)
        try:
            mask_file(src, self.masker, self.watcher.file_suffix, dst=dst)
        except UnsupportedFile:
            self.notify("privacy-input-layer", t("mask_files_none"))
            return
        except Exception as e:
            log.warning("mask %s: %s", src, e)
            self.notify("privacy-input-layer", t("mask_files_none"))
            return
        self.watcher.events.appendleft(f"{time.strftime('%H:%M:%S')} files masked 1 (manual)")
        self.notify("privacy-input-layer", t("mask_files_done", n=1, dir=self.watcher.copies_dir))
        os.startfile(str(self.watcher.copies_dir))

    def _toggle_mode(self, icon, item):
        cur = self.cfg["guard"].get("mode", "focus")
        new = "always" if cur == "focus" else "focus"
        self.cfg["guard"]["mode"] = new
        self.watcher.mode = new
        if new == "focus":
            if not self.focus:
                from .focus import ForegroundWatcher
                self.focus = ForegroundWatcher(self.cfg, self._on_focus, on_drag=self._on_drag)
            self.focus.start()
        else:
            if self.focus:
                self.focus.stop()
                self.focus = None
            self.watcher.ai_focused = False
        self._save_config()
        icon.update_menu()
        self.notify("privacy-input-layer", t("mode_focus") if new == "focus" else t("mode_always"))

    def _save_config(self):
        import yaml
        (self.dir / "config.yaml").write_text(
            yaml.safe_dump(self.cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    def _menu(self):
        return pystray.Menu(
            pystray.MenuItem(lambda item: self._provenance, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(self._status_text, self._toggle, default=True),
            pystray.MenuItem(self._notify_text, self._toggle_notify),
            pystray.MenuItem(lambda item: t("language"), self._toggle_language),
            pystray.MenuItem(
                lambda item: t("mode_focus") if self.cfg["guard"].get("mode", "focus") == "focus" else t("mode_always"),
                self._toggle_mode,
            ),
            pystray.MenuItem(lambda item: t("recent"), self._recent_menu()),
            pystray.MenuItem(lambda item: t("restore_now"), self._restore_now),
            pystray.MenuItem(lambda item: t("mask_files"), self._mask_files),
            pystray.MenuItem(lambda item: t("sendto_install"), self._install_sendto),
            pystray.MenuItem(
                lambda item: t("autostart_on") if self._autostart_enabled() else t("autostart_off"),
                self._toggle_autostart,
            ),
            pystray.MenuItem(lambda item: t("open_config"), lambda: os.startfile(str(self.dir / "config.yaml"))),
            pystray.MenuItem(lambda item: t("open_data"), lambda: os.startfile(str(self.dir))),
            pystray.MenuItem(lambda item: t("check_updates"), lambda: self._check_update()),
            pystray.MenuItem(
                lambda item: t("update_available", v=self._update["latest"]),
                lambda: __import__("webbrowser").open(self._update["url"]),
                visible=lambda item: bool(self._update),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda item: t("quit"), self._quit),
        )

    def _check_update(self):
        from . import updater
        from . import __version__

        def work():
            status, res = updater.check_update()
            log.info("update check: %s %s", status, res)
            if status == "newer":
                self._update = res
                msg = t("update_available", v=res["latest"])
            elif status == "current":
                msg = t("up_to_date", v=__version__)
            else:
                msg = t("update_failed")
            # 手动检查强制反馈，不受静默设置抑制
            if self.icon:
                try:
                    self.icon.notify(msg, "privacy-input-layer")
                except Exception:
                    pass
                self.icon.update_menu()
        threading.Thread(target=work, daemon=True).start()

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
        if self.cfg["guard"].get("update_check", False):
            self._check_update()

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
        from . import __version__
        try:
            from . import _buildinfo
            build = f"{_buildinfo.SHA[:7]} {_buildinfo.TIME}"
        except Exception:
            build = "dev"
        frozen = getattr(sys, "frozen", False)
        self._provenance = f"v{__version__} · {build} · {'binary' if frozen else 'source'}"
        log.info("guard starting v%s build=%s frozen=%s exe=%s mode=%s",
                 __version__, build, frozen, sys.executable,
                 self.cfg["guard"].get("mode", "focus"))
        # 单实例：重复启动时静默退出，避免两个守卫互相改写剪贴板
        kernel32 = ctypes.windll.kernel32
        self._mutex = kernel32.CreateMutexW(None, False, "PilayerSingleInstance")
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            log.info("another instance running, exit")
            return
        self.icon = pystray.Icon(
            "pilayer", _icon_image(True), f"privacy-input-layer v{__version__}", menu=self._menu()
        )
        self.icon.run(setup=self._setup)