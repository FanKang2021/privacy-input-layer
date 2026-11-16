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
    },
}


def set_language(lang: str):
    global LANG
    LANG = lang if lang in STRINGS else "en"


def t(key: str, **kw) -> str:
    return STRINGS[LANG][key].format(**kw)