"""Вибирає з експорту Telegram Desktop повідомлення, схожі на рецепти, і перелічує медіа.

Вхід: sources/telegram/<канал>/result.json (експорт у JSON)
      або sources/telegram/<канал>/messages*.html (експорт у HTML).
Вихід: sources/telegram/candidates.md — кандидати в рецепти, потім усі PDF, відео й фото з підписами.

  python scripts/telegram_extract.py [--min-score 4]
"""
import argparse
import html
import json
import re

from recipe_lib import SOURCES_DIR, utf8_stdout

TG_DIR = SOURCES_DIR / "telegram"
OUT = TG_DIR / "candidates.md"

KEYWORDS = re.compile(
    r"інгредієнт|рецепт|приготуванн|спосіб приготування|знадобиться|вам знадоб|"
    r"ингредиент|приготовлени|понадобится|"
    r"духовк|сковород|запік|запекти|відвар|обсмаж|перемішай|змішай|до готовності|випікан|"
    r"запек|обжар|перемеша|смеша|до готовности",
    re.I,
)
UNITS = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:г|гр|кг|мл|л|шт|ст\.?\s?л|ч\.?\s?л|склян|стакан|зубч|пучок)\b\.?|"
    r"\b(?:ст|ч)\.\s?л\.|за смаком|по вкусу|щіпка|щепотка",
    re.I,
)
LIST_LINE = re.compile(r"^\s*(?:[-–—•*▪️✅🔸🔹]|\d+[.)])\s*\S", re.M)
MESSAGE_RE = re.compile(r'<div class="message default clearfix(?: joined)?" id="message(\d+)">')


def score(text):
    s = 0
    s += min(len(KEYWORDS.findall(text)), 4)
    s += min(len(UNITS.findall(text)), 6)
    s += min(len(LIST_LINE.findall(text)), 4) // 2
    return s


def from_json(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    messages = []
    for msg in data.get("messages", []):
        if msg.get("type") != "message":
            continue
        t = msg.get("text", "")
        if isinstance(t, list):
            t = "".join(p if isinstance(p, str) else p.get("text", "") for p in t)
        media = [msg[k] for k in ("photo", "file") if msg.get(k)]
        messages.append({"id": msg.get("id"), "date": (msg.get("date") or "")[:10],
                         "text": (t or "").strip(), "media": media})
    return data.get("name") or path.parent.name, messages


def from_html(paths):
    messages, channel = [], None
    for path in paths:
        src = path.read_text(encoding="utf-8")
        if channel is None:
            m = re.search(r'<div class="text bold">\s*(.*?)\s*</div>', src, re.S)
            channel = html.unescape(m.group(1)).strip() if m else path.parent.name
        parts = MESSAGE_RE.split(src)
        for mid, body in zip(parts[1::2], parts[2::2]):
            date = re.search(r'class="pull_right date details" title="(\d\d)\.(\d\d)\.(\d{4})', body)
            text_m = re.search(r'<div class="text">(.*?)</div>', body, re.S)
            text = ""
            if text_m:
                text = re.sub(r"<br\s*/?>", "\n", text_m.group(1))
                text = html.unescape(re.sub(r"<[^>]+>", "", text)).strip()
            media = sorted({html.unescape(h) for h in re.findall(
                r'href="((?:files|photos|video_files|voice_messages|round_video_messages)/[^"]+)"', body)})
            messages.append({"id": int(mid), "date": f"{date.group(3)}-{date.group(2)}-{date.group(1)}" if date else "",
                             "text": text, "media": media})
    return channel, messages


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-score", type=int, default=4)
    args = ap.parse_args()

    exports = []
    for folder in sorted(p for p in TG_DIR.iterdir() if p.is_dir()):
        if (folder / "result.json").exists():
            exports.append((folder, from_json(folder / "result.json")))
        elif list(folder.glob("messages*.html")):
            pages = sorted(folder.glob("messages*.html"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 1))
            exports.append((folder, from_html(pages)))
    if not exports:
        print(f"Немає експортів. Поклади експорт Telegram Desktop (JSON або HTML) у {TG_DIR}/<назва-каналу>/")
        return

    out, total = ["# Кандидати в рецепти з Telegram", ""], 0
    for folder, (channel, messages) in exports:
        rel = folder.relative_to(SOURCES_DIR.parent).as_posix()
        found = [(m, score(m["text"])) for m in messages if len(m["text"]) >= 80]
        found = [(m, s) for m, s in found if s >= args.min_score]
        with_media = [m for m in messages if m["media"]]
        print(f"{channel}: повідомлень {len(messages)}, кандидатів {len(found)}, з медіа {len(with_media)}")
        total += len(found)
        out += [f"## {channel}", f"Папка: `{rel}`", "", "### Кандидати", ""]
        for m, s in found:
            out += [f"#### id {m['id']} · {m['date']} · оцінка {s}", "", m["text"], "", "---", ""]
        out += ["### Медіа з підписами", "", "| id | дата | файл | підпис |", "|---|---|---|---|"]
        for m in with_media:
            caption = m["text"].replace("\n", " ").replace("|", "/")[:160]
            for f in m["media"]:
                out.append(f"| {m['id']} | {m['date']} | `{f}` | {caption} |")
        out.append("")
    OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"Усього кандидатів: {total} → {OUT.relative_to(SOURCES_DIR.parent).as_posix()}")


if __name__ == "__main__":
    main()
