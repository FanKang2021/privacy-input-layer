"""CLI：pilayer run / mask-text / restore-text / mask-file / restore-file / stats。"""

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
        description="AI 隐私输入层：内容进入 AI 客户端之前完成脱敏，全部本地运行",
    )
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run", help="启动托盘守卫（默认）")
    p = sub.add_parser("mask-text", help="脱敏一段文本并输出")
    p.add_argument("text")
    p = sub.add_parser("restore-text", help="还原文本中的占位符")
    p.add_argument("text")
    p = sub.add_parser("mask-file", help="生成文件脱敏副本")
    p.add_argument("path")
    p.add_argument("--dst", help="输出路径（默认 <name>.masked.<ext>）")
    p = sub.add_parser("restore-file", help="回填文件中的占位符")
    p.add_argument("path")
    p.add_argument("--dst", help="输出路径（默认 <name>.restored.<ext>）")
    sub.add_parser("stats", help="查看本地映射统计")
    sub.add_parser("install-sendto", help="安装右键『发送到 -> 脱敏副本』")
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
        bat = sendto / "脱敏副本.bat"
        bat.write_text(
            f'@echo off\r\n"{sys.executable}" -m pilayer mask-file "%1"\r\npause\r\n',
            encoding="gbk",
        )
        print(f"已安装：{bat}")
        return 0

    masker = _build_masker()
    if cmd == "mask-text":
        r = masker.mask(args.text)
        print(r.text)
        print(f"已脱敏 {r.count} 处", file=sys.stderr)
    elif cmd == "restore-text":
        r = masker.restore(args.text)
        print(r.text)
        print(f"已还原 {r.count} 处，无映射 {len(r.missing)} 处", file=sys.stderr)
    elif cmd == "mask-file":
        r = mask_file(args.path, masker, dst=args.dst)
        print(f"{r.dst}（脱敏 {r.count} 处）")
    elif cmd == "restore-file":
        r = restore_file(args.path, masker, dst=args.dst)
        print(f"{r.dst}（还原 {r.count} 处）")
    elif cmd == "stats":
        s = masker.store.stats()
        print(f"映射总数：{s['total']}")
        for kind, n in s["by_kind"].items():
            print(f"  {kind}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())