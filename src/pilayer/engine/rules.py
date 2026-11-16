"""PII 与凭据识别规则：手机号 / 身份证 / 银行卡 / 邮箱 / 私钥 / IP / 令牌 / 自定义关键词。"""

import re
from dataclasses import dataclass

PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
IDCARD_RE = re.compile(
    r"(?<!\d)\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)"
)
BANKCARD_RE = re.compile(r"(?<!\d)\d{16,19}(?!\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PRIVKEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.S,
)
IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
TOKEN_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{20,}"
    r"|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"
)

# 占位符优先级：重叠时私钥 > 令牌 > 身份证 > 银行卡 > 手机号 > 邮箱 > IP > 关键词
PRIORITY = {"PRIVKEY": 0, "TOKEN": 1, "IDCARD": 2, "BANKCARD": 3,
            "PHONE": 4, "EMAIL": 5, "IP": 6, "KEYWORD": 7}

_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CHECK = "10X98765432"


@dataclass(frozen=True)
class Match:
    kind: str
    start: int
    end: int
    text: str


def _idcard_valid(s: str) -> bool:
    total = sum(int(c) * w for c, w in zip(s[:17], _ID_WEIGHTS))
    return _ID_CHECK[total % 11] == s[-1].upper()


def _luhn_valid(s: str) -> bool:
    digits = [int(c) for c in s]
    odd = digits[-1::-2]
    even = digits[-2::-2]
    total = sum(odd) + sum(sum(divmod(d * 2, 10)) for d in even)
    return total % 10 == 0


def _ipv4_valid(s: str) -> bool:
    return all(0 <= int(o) <= 255 for o in s.split("."))


def find_matches(text: str, enabled: dict, keywords: list[str]) -> list[Match]:
    matches: list[Match] = []
    if enabled.get("privkey", True):
        for m in PRIVKEY_RE.finditer(text):
            matches.append(Match("PRIVKEY", m.start(), m.end(), m.group()))
    if enabled.get("token", True):
        for m in TOKEN_RE.finditer(text):
            matches.append(Match("TOKEN", m.start(), m.end(), m.group()))
    if enabled.get("idcard", True):
        for m in IDCARD_RE.finditer(text):
            if _idcard_valid(m.group()):
                matches.append(Match("IDCARD", m.start(), m.end(), m.group()))
    if enabled.get("bankcard", True):
        for m in BANKCARD_RE.finditer(text):
            if _luhn_valid(m.group()):
                matches.append(Match("BANKCARD", m.start(), m.end(), m.group()))
    if enabled.get("phone", True):
        for m in PHONE_RE.finditer(text):
            matches.append(Match("PHONE", m.start(), m.end(), m.group()))
    if enabled.get("email", True):
        for m in EMAIL_RE.finditer(text):
            matches.append(Match("EMAIL", m.start(), m.end(), m.group()))
    if enabled.get("ip", True):
        for m in IPV4_RE.finditer(text):
            if _ipv4_valid(m.group()):
                matches.append(Match("IP", m.start(), m.end(), m.group()))
    for kw in keywords:
        if not kw:
            continue
        for m in re.finditer(re.escape(kw), text):
            matches.append(Match("KEYWORD", m.start(), m.end(), m.group()))

    matches.sort(key=lambda m: (PRIORITY[m.kind], m.start, -(m.end - m.start)))
    chosen: list[Match] = []
    occupied: list[tuple[int, int]] = []
    for m in matches:
        if any(m.start < e and s < m.end for s, e in occupied):
            continue
        chosen.append(m)
        occupied.append((m.start, m.end))
    chosen.sort(key=lambda m: m.start)
    return chosen