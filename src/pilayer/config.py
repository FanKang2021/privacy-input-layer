"""配置加载：%APPDATA%/pilayer/config.yaml，缺省自动生成。"""

import copy
import os
from pathlib import Path

import yaml

DEFAULTS = {
    "guard": {
        "mode": "focus",
        "text_enabled": True,
        "image_enabled": True,
        "hdrop_enabled": True,
        "auto_restore": True,
        "notify": True,
        "auto_detect": True,
        "paste_hook": True,
        "paste_injection": True,
        "paste_chunk_size": 400,
        "paste_chunk_delay_ms": 40,
        "lazy_restore": True,
    },
    "ai_targets": {
        "processes": [
            # international desktop clients
            "Qoder CN.exe", "Qoder.exe", "Cursor.exe", "Claude.exe",
            "ChatGPT.exe", "Windsurf.exe", "Trae.exe", "Trae CN.exe",
            "CodeBuddy.exe", "Copilot.exe", "Gemini.exe", "LM Studio.exe",
            "Jan.exe", "Cherry Studio.exe", "Chatbox.exe", "AnythingLLM.exe",
            "Msty.exe",
            # China desktop clients
            "WorkBuddy.exe", "Comate.exe", "Lingma.exe", "Doubao.exe",
            "Kimi.exe", "Tongyi.exe", "DeepSeek.exe", "Yuanbao.exe",
            "ChatGLM.exe", "MiniMax.exe",
        ],
        "learned_processes": [],
        "browsers": [
            "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe",
            "Tabbit Browser.exe",
        ],
        "newtab_chat_browsers": ["Tabbit Browser.exe"],
        "newtab_titles": ["新标签页", "新建标签页", "New Tab", "New tab"],
        "title_patterns": [
            "ChatGPT", "Claude", "Gemini", "Copilot", "Poe", "Perplexity",
            "DeepSeek", "Kimi", "通义", "千问", "Qwen", "文心", "豆包",
            "智谱", "Grok", "Mistral", "Meta AI", "Google AI",
        ],
        "url_patterns": [
            "chatgpt.com", "claude.ai", "gemini.google.com",
            "copilot.microsoft.com", "poe.com", "perplexity.ai",
            "chat.deepseek.com", "kimi.com", "moonshot.cn",
            "tongyi.aliyun.com", "yiyan.baidu.com", "chatglm.cn",
            "doubao.com", "metaso.cn", "chat.qwen.ai", "grok.com",
            "chat.mistral.ai", "huggingface.co",
        ],
    },
    "rules": {
        "phone": True,
        "idcard": True,
        "bankcard": True,
        "bankcard_bin": True,
        "email": True,
        "privkey": True,
        "ip": True,
        "token": True,
        "secret": True,
        "url": True,
        "internal_domains": [],
        "custom_keywords": [],
    },
    "image": {"min_score": 0.5, "fill": [40, 40, 40]},
    "files": {"suffix": ".masked"},
    "store": {"ttl_days": 30},
    "ui": {"language": "en"},
}


def app_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    d = Path(base) / "pilayer"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | Path | None = None) -> dict:
    p = Path(path) if path else app_dir() / "config.yaml"
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        return _merge(DEFAULTS, user_cfg)
    cfg = copy.deepcopy(DEFAULTS)
    with open(p, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    return cfg