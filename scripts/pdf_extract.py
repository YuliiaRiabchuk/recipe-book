"""Робота з PDF-джерелами: текст по сторінках, зображення, обкладинки рецептів.

  python scripts/pdf_extract.py text <pdf> <out.txt>             текст з маркерами "=== page N ==="
  python scripts/pdf_extract.py images <pdf> [--pages 5-12]       зображення на сторінках: індекс і розмір
  python scripts/pdf_extract.py sheet <pdf> <out.jpg> [--pages 5-12] [--min 300]
                                                                  контактний аркуш зображень для перегляду
  python scripts/pdf_extract.py cover <pdf> <page> <id> [--index N] [--crop x0,y0,x1,y1]
                                                                  зберегти site/img/<id>.jpg (до 900 px)

Сторінки нумеруються з 1, як у переглядачі PDF.
"""
import argparse
import io
import sys
from pathlib import Path

import pypdf
from PIL import Image, ImageDraw

from recipe_lib import SITE_FILE, utf8_stdout

IMG_DIR = SITE_FILE.parent / "img"


def page_range(spec, total):
    if not spec:
        return range(1, total + 1)
    a, _, b = spec.partition("-")
    return range(int(a), min(int(b or a), total) + 1)


def flatten(img):
    """Прозорий фон → білий, щоб вирізані фото страв не були на чорному."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, "white")
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")


def page_images(reader, n):
    out = []
    for i, im in enumerate(reader.pages[n - 1].images):
        try:
            img = im.image  # з маскою прозорості, на відміну від сирих im.data
            img.load()
        except Exception:
            try:
                img = Image.open(io.BytesIO(im.data))
                img.load()
            except Exception:
                continue
        out.append((i, flatten(img)))
    return out


def cmd_text(pdf, out):
    reader = pypdf.PdfReader(pdf)
    with open(out, "w", encoding="utf-8") as f:
        for n, p in enumerate(reader.pages, 1):
            f.write(f"\n=== page {n} ===\n{p.extract_text() or ''}")
    print(f"{len(reader.pages)} сторінок → {out}")


def cmd_images(pdf, pages):
    reader = pypdf.PdfReader(pdf)
    for n in page_range(pages, len(reader.pages)):
        imgs = page_images(reader, n)
        if imgs:
            print(f"page {n}: " + ", ".join(f"#{i} {im.size[0]}x{im.size[1]}" for i, im in imgs))


def cmd_sheet(pdf, out, pages, min_side):
    reader = pypdf.PdfReader(pdf)
    tiles = []
    for n in page_range(pages, len(reader.pages)):
        for i, im in page_images(reader, n):
            if max(im.size) >= min_side:
                tiles.append((f"p{n} #{i}", im.convert("RGB")))
    if not tiles:
        print("зображень немає")
        return
    w, h, cols = 220, 240, 6
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (w * cols, (h + 20) * rows), "white")
    draw = ImageDraw.Draw(sheet)
    for k, (label, im) in enumerate(tiles):
        im = im.copy()
        im.thumbnail((w - 6, h))
        x, y = (k % cols) * w, (k // cols) * (h + 20)
        sheet.paste(im, (x + 3, y + 18))
        draw.text((x + 4, y + 2), label, fill="black")
    sheet.save(out, quality=75)
    print(f"{len(tiles)} зображень → {out}")


def cmd_cover(pdf, page, rid, index, crop):
    reader = pypdf.PdfReader(pdf)
    imgs = page_images(reader, page)
    if not imgs:
        print(f"на сторінці {page} зображень немає")
        sys.exit(1)
    if index is None:
        index, img = max(imgs, key=lambda t: t[1].size[0] * t[1].size[1])
    else:
        img = dict(imgs)[index]
    img = img.convert("RGB")
    if crop:
        img = img.crop(tuple(int(v) for v in crop.split(",")))
    img.thumbnail((900, 900))
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    path = IMG_DIR / f"{rid}.jpg"
    img.save(path, quality=80, optimize=True)
    print(f"{path.relative_to(SITE_FILE.parent.parent).as_posix()} {img.size[0]}x{img.size[1]} {path.stat().st_size // 1024} KB (page {page} #{index})")


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("text"); t.add_argument("pdf"); t.add_argument("out")
    i = sub.add_parser("images"); i.add_argument("pdf"); i.add_argument("--pages")
    s = sub.add_parser("sheet"); s.add_argument("pdf"); s.add_argument("out"); s.add_argument("--pages"); s.add_argument("--min", type=int, default=300)
    c = sub.add_parser("cover"); c.add_argument("pdf"); c.add_argument("page", type=int); c.add_argument("id")
    c.add_argument("--index", type=int); c.add_argument("--crop")
    a = ap.parse_args()
    if a.cmd == "text":
        cmd_text(a.pdf, a.out)
    elif a.cmd == "images":
        cmd_images(a.pdf, a.pages)
    elif a.cmd == "sheet":
        cmd_sheet(a.pdf, a.out, a.pages, a.min)
    else:
        cmd_cover(a.pdf, a.page, a.id, a.index, a.crop)


if __name__ == "__main__":
    main()
