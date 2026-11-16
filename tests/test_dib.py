import struct

from PIL import Image

from pilayer.clipboard.dib import dib_to_image, image_to_dib


def _sample(w=40, h=30):
    return Image.linear_gradient("L").resize((w, h)).convert("RGB")


def test_dib_roundtrip():
    img = _sample()
    out = dib_to_image(image_to_dib(img))
    assert out is not None
    assert out.size == img.size
    assert list(out.getdata()) == list(img.getdata())


def test_top_down_dib():
    img = _sample()
    w, h = img.size
    dib = image_to_dib(img)
    stride = ((w * 3 + 3) // 4) * 4
    pixels = dib[40:]
    rows = [pixels[i * stride:(i + 1) * stride] for i in range(h)]
    top_down = dib[:8] + struct.pack("<i", -h) + dib[12:40] + b"".join(reversed(rows))
    out = dib_to_image(top_down)
    assert out is not None
    assert list(out.getdata()) == list(img.getdata())


def test_invalid_dib():
    assert dib_to_image(b"short") is None
    assert dib_to_image(bytes(40)) is None