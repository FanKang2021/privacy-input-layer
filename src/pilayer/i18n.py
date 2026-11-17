"""托盘/通知文案中英文切换。"""

LANG = "en"

STRINGS = {
    "en": {
        "guard_on": "Guard: on",
        "guard_paused": "Guard: paused",
        "notify_on": "Notifications: on",
        "notify_off": "Notifications: off (silent)",
        "language": "Language: English",
        "open_config": "Open config",
        "open_data": "Open data dir",
        "quit": "Quit",
        "masked": "Masked {count} item(s) ({kinds}) - paste is safe",
        "restored": "Restored {count} placeholder(s)",
        "restored_missing": " ({n} unmapped, kept as-is)",
        "image_masked": "Image masked: {count} sensitive region(s)",
        "hdrop": "Swapped {n} file(s) to masked copies ({dir})",
        "hdrop_restored": "File paths restored to originals",
        "clip_error": "Clipboard error: {e}",
        "ocr_missing": "Image masking requires OCR extras: pip install privacy-input-layer[image]",
        "focus_ai": "AI focus: ",
        "focus_left": "Left AI: ",
        "guard_state_on": "Guard on",
        "guard_state_paused": "Guard paused",
        "learned": "Learned AI client: {proc}",
        "autostart_on": "Start with Windows: on",
        "autostart_off": "Start with Windows: off",
        "check_updates": "Check for updates",
        "update_available": "Update available: v{v} (open Releases)",
        "up_to_date": "Up to date (v{v})",
        "update_failed": "Update check failed (network?)",
        "mode_focus": "Mode: focus-aware",
        "mode_always": "Mode: always-on",
        "recent": "Recent masks",
        "recent_empty": "(no events yet)",
        "restore_now": "Restore clipboard now",
        "nothing_restore": "No placeholders on clipboard",
    },
    "zh": {
        "guard_on": "守卫：开启",
        "guard_paused": "守卫：暂停",
        "notify_on": "通知：开启",
        "notify_off": "通知：静默",
        "language": "语言：中文",
        "open_config": "打开配置",
        "open_data": "打开数据目录",
        "quit": "退出",
        "masked": "已脱敏 {count} 处（{kinds}），粘贴即安全",
        "restored": "已还原 {count} 处占位符",
        "restored_missing": "（{n} 处无映射，保留原样）",
        "image_masked": "图片已打码 {count} 处敏感区域",
        "hdrop": "已替换 {n} 个文件为脱敏副本（{dir}）",
        "hdrop_restored": "文件路径已还原为原件",
        "clip_error": "处理剪贴板出错：{e}",
        "ocr_missing": "图片打码需要 OCR 依赖：pip install privacy-input-layer[image]",
        "focus_ai": "进入 AI 对话：",
        "focus_left": "离开 AI 对话：",
        "guard_state_on": "守卫已开启",
        "guard_state_paused": "守卫已暂停",
        "learned": "已学习 AI 客户端：{proc}",
        "autostart_on": "开机自启：开",
        "autostart_off": "开机自启：关",
        "check_updates": "检查更新",
        "update_available": "有新版 v{v}（打开 Releases）",
        "up_to_date": "已是最新（v{v}）",
        "update_failed": "检查更新失败（网络？）",
        "mode_focus": "模式：焦点感知",
        "mode_always": "模式：全局常开",
        "recent": "最近脱敏",
        "recent_empty": "（暂无事件）",
        "restore_now": "立即还原剪贴板",
        "nothing_restore": "剪贴板无占位符",
    },
}


def set_language(lang: str):
    global LANG
    LANG = lang if lang in STRINGS else "en"


def t(key: str, **kw) -> str:
    return STRINGS[LANG][key].format(**kw)