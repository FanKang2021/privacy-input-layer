"""图片打码：OCR 定位文字区域 -> 规则判定敏感 -> 像素填充（不可逆）。"""

from PIL import Image, ImageDraw

from ..i18n import t
from .rules import find_matches


class ImageOCRUnavailable(Exception):
    pass


class ImageMasker:
    def __init__(self, rules_cfg: dict, keywords: list[str] | None = None,
                 min_score: float = 0.5, fill=(40, 40, 40)):
        self.rules_cfg = rules_cfg
        self.keywords = keywords or []
        self.min_score = min_score
        self.fill = tuple(fill)
        self._ocr = None

    def _get_ocr(self):
        if self._ocr is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as e:
                raise ImageOCRUnavailable(t("ocr_missing")) from e
            self._ocr = RapidOCR()
        return self._ocr

    def mask(self, img: Image.Image) -> tuple[Image.Image, int]:
        import numpy as np

        arr = np.array(img.convert("RGB"))
        result, _ = self._get_ocr()(arr)
        if not result:
            return img, 0
        out = img.convert("RGB")
        draw = ImageDraw.Draw(out)
        count = 0
        for box, text, score in result:
            if float(score) < self.min_score:
                continue
            matches = find_matches(text, self.rules_cfg, self.keywords)
            if matches:
                draw.polygon([tuple(p) for p in box], fill=self.fill)
                count += len(matches)
        return out, count