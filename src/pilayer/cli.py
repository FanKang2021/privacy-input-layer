"""CLI: pilayer run / mask-text / restore-text / mask-file / restore-file / stats / install-sendto."""

import argparse
import sys

from .config import app_dir, load_config
from .engine import MappingStore, TextMasker
from .files import mask_file, restore_file


def _build_masker() -> TextMasker:
    cfg = load_config()
    store = MappingStore(app_dir() / "mappings.db")
    keywords = cfg["rules"].get("custom_keywords") or []
    return TextMasker(store, cfg["rules"], keywords)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="pilayer",
        description="Privacy input layer for AI: mask content before it enters any AI client, 100% local",
    )
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run", help="start the tray guard (default)")
    p = sub.add_parser("mask-text", help="mask a text string and print it")
    p.add_argument("text")
    p = sub.add_parser("restore-text", help="restore placeholders in a text string")
    p.add_argument("text")
    p = sub.add_parser("mask-file", help="create a masked copy of a file")
    p.add_argument("path")
    p.add_argument("--dst", help="output path (default <name>.masked.<ext>)")
    p = sub.add_parser("restore-file", help="restore placeholders in a file")
    p.add_argument("path")
    p.add_argument("--dst", help="output path (default <name>.restored.<ext>)")
    sub.add_parser("stats", help="show local mapping statistics")
    sub.add_parser("purge", help="delete expired mappings (store.ttl_days)")
    sub.add_parser("unmask", help="restore placeholders currently on the clipboard")
    sub.add_parser("install-sendto", help='install right-click "Send to -> Masked copy"')
    args = parser.parse_args(argv)
    cmd = args.cmd or "run"

    if cmd == "run":
        from .app import Application
        Application().run()
        return 0

    if cmd == "install-sendto":
        import os
        from pathlib import Path

        sendto = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "SendTo"
        bat = sendto / "Masked copy.bat"
        bat.write_text(
            f'@echo off\r\n"{sys.executable}" -m pilayer mask-file "%1"\r\npause\r\n',
            encoding="gbk",
        )
        print(f"Installed: {bat}")
        return 0

    masker = _build_masker()
    if cmd == "mask-text":
        r = masker.mask(args.text)
        print(r.text)
        print(f"masked {r.count} item(s)", file=sys.stderr)
    elif cmd == "restore-text":
        r = masker.restore(args.text)
        print(r.text)
        print(f"restored {r.count}, unmapped {len(r.missing)}", file=sys.stderr)
    elif cmd == "mask-file":
        r = mask_file(args.path, masker, dst=args.dst)
        print(f"{r.dst} (masked {r.count} item(s))")
    elif cmd == "restore-file":
        r = restore_file(args.path, masker, dst=args.dst)
        print(f"{r.dst} (restored {r.count} item(s))")
    elif cmd == "stats":
        s = masker.store.stats()
        print(f"total mappings: {s['total']}")
        for kind, n in s["by_kind"].items():
            print(f"  {kind}: {n}")
    elif cmd == "purge":
        ttl = load_config().get("store", {}).get("ttl_days", 30)
        n = masker.store.purge_expired(ttl)
        print(f"purged {n} expired mapping(s) (ttl={ttl}d)")
    elif cmd == "unmask":
        import win32clipboard
        import win32con
        win32clipboard.OpenClipboard()
        try:
            text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        except Exception:
            text = ""
        finally:
            win32clipboard.CloseClipboard()
        r = masker.restore(text or "")
        if r.count:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, r.text)
            win32clipboard.CloseClipboard()
        print(f"restored {r.count} placeholder(s) on clipboard")
    return 0


if __name__ == "__main__":
    sys.exit(main())