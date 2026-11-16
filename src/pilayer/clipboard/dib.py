"""DIB <-> PIL 图像转换（剪贴板 CF_DIB 格式）。"""

import io
import struct

from PIL import Image


def dib_to_image(dib: bytes) -> Image.Image | None:
    if len(dib) < 40:
        return None
    hdr_size = struct.unpack_from("<I", dib, 0)[0]
    if hdr_size < 40:
        return None
    width, height, planes, bitcount, compression = struct.unpack_from("<iiHHI", dib, 4)
    if compression != 0 or bitcount not in (24, 32) or width <= 0 or height == 0:
        return None
    top_down = height < 0
    if top_down:
        dib = dib[:8] + struct.pack("<i", -height) + dib[12:]
    offset = 14 + hdr_size
    bmp = b"BM" + struct.pack("<IHHI", 14 + len(dib), 0, 0, offset) + dib
    try:
        img = Image.open(io.BytesIO(bmp))
        img.load()
    except Exception:
        return None
    if top_down:
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
    return img.convert("RGB")


def image_to_dib(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "BMP")
    return buf.getvalue()[14:]