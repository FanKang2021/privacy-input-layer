"""托盘应用：常驻守卫 + 开关 + 通知。"""

import ctypes
import os
import time

import pystray
from PIL import Image, ImageDraw

from .clipboard import ClipboardWatcher
from .config import app_dir, load_config
from .engine import MappingStore, TextMasker
from .engine.image import ImageMasker


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
        self.dir = app_dir()
        self.store = MappingStore(self.dir / "mappings.db")
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
        self.icon = None

    def notify(self, title: str, msg: str):
        if self.cfg["guard"].get("notify") and self.icon:
            try:
                self.icon.notify(msg, title)
            except Exception:
                pass

    def _toggle(self, icon, item):
        self.watcher.enabled = not self.watcher.enabled
        icon.icon = _icon_image(self.watcher.enabled)
        state = "已开启" if self.watcher.enabled else "已暂停"
        self.notify("privacy-input-layer", f"守卫{state}")

    def _status_text(self, item):
        return "守卫：" + ("开启" if self.watcher.enabled else "暂停")

    def _menu(self):
        return pystray.Menu(
            pystray.MenuItem(self._status_text, self._toggle, default=True),
            pystray.MenuItem("打开配置", lambda: os.startfile(str(self.dir / "config.yaml"))),
            pystray.MenuItem("打开数据目录", lambda: os.startfile(str(self.dir))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._quit),
        )

    def _quit(self, icon, item):
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
        # 单实例：重复启动时静默退出，避免两个守卫互相改写剪贴板
        kernel32 = ctypes.windll.kernel32
        self._mutex = kernel32.CreateMutexW(None, False, "PilayerSingleInstance")
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            return
        self.icon = pystray.Icon(
            "pilayer", _icon_image(True), "privacy-input-layer", menu=self._menu()
        )
        self.icon.run(setup=self._setup)