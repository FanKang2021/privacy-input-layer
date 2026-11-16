"""文本脱敏与还原。"""

from dataclasses import dataclass, field

from .rules import find_matches
from .store import MappingStore, PLACEHOLDER_RE


@dataclass
class MaskResult:
    text: str
    count: int
    kinds: list[str] = field(default_factory=list)


@dataclass
class RestoreResult:
    text: str
    count: int
    missing: list[str] = field(default_factory=list)


class TextMasker:
    def __init__(self, store: MappingStore, rules_cfg: dict, keywords: list[str] | None = None):
        self.store = store
        self.rules_cfg = rules_cfg
        self.keywords = keywords or []

    def mask(self, text: str) -> MaskResult:
        matches = find_matches(text, self.rules_cfg, self.keywords)
        if not matches:
            return MaskResult(text, 0)
        parts: list[str] = []
        kinds: list[str] = []
        pos = 0
        for m in matches:
            placeholder = self.store.get_or_create(m.kind, m.text)
            parts.append(text[pos:m.start])
            parts.append(placeholder)
            kinds.append(m.kind)
            pos = m.end
        parts.append(text[pos:])
        return MaskResult("".join(parts), len(matches), kinds)

    def has_placeholder(self, text: str) -> bool:
        return bool(PLACEHOLDER_RE.search(text))

    def restore(self, text: str) -> RestoreResult:
        restored, count, missing = self.store.restore(text)
        return RestoreResult(restored, count, missing)