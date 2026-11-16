"""配置加载：%APPDATA%/pilayer/config.yaml，缺省自动生成。"""

import copy
import os
from pathlib import Path

import yaml

DEFAULTS = {
    "guard": {
        "text_enabled": True,
        "image_enabled": True,
        "hdrop_enabled": True,
        "auto_restore": True,
        "notify": True,
    },
    "rules": {
        "phone": True,
        "idcard": True,
        "bankcard": True,
        "email": True,
        "privkey": True,
        "ip": True,
        "token": True,
        "custom_keywords": [],
    },
    "image": {"min_score": 0.5, "fill": [40, 40, 40]},
    "files": {"suffix": ".masked"},
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