"""Вибирає з експорту Telegram Desktop повідомлення, схожі на рецепти.

Вхід: sources/telegram/<канал>/result.json (Export chat history → JSON).
Вихід: sources/telegram/candidates.md

  python scripts/telegram_extract.py [--min-score 4]
"""
import argparse
import json
import re

from recipe_lib import SOURCES_DIR, utf8_stdout

TG_DIR = SOURCES_DIR / "telegram"
OUT = TG_DIR / "candidates.md"

KEYWORDS = re.compile(
    r"інгредієнт|рецепт|приготуванн|спосіб приготування|знадобиться|вам знадоб|"
    r"ингредиент|приготовлени|понадобится|"
    r"духовк|сковород|запік|запекти|відвар|обсмаж|перемішай|змішай|до готовності|"
    r"духовк|запек|обжар|перемеша|смеша|до готовности",
    re.I,
)
UNITS = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:г|гр|кг|мл|л|шт|ст\.?\s?л|ч\.?\s?л|склян|стакан|зубч|пучок)\b\.?|"
    r"\b(?:ст|ч)\.\s?л\.|за смаком|по вкусу|щіпка|щепотка",
    re.I,
)
LIST_LINE = re.compile(r"^\s*(?:[-–—•*▪️✅🔸🔹]|\d+[.)])\s*\S", re.M)


def message_text(msg):
    t = msg.get("text", "")
    if isinstance(t, list):
        return "".join(p if isinstance(p, str) else p.get("text", "") for p in t)
    return t or ""


def score(text):
    s = 0
    s += min(len(KEYWORDS.findall(text)), 4)
    s += min(len(UNITS.findall(text)), 6)
    s += min(len(LIST_LINE.findall(text)), 4) // 2
    return s


def main():
    utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-score", type=int, default=4)
    args = ap.parse_args()

    exports = sorted(TG_DIR.glob("*/result.json"))
    if not exports:
        print(f"Немає експортів. Поклади result.json у {TG_DIR}/<назва-каналу>/result.json")
        return

    out, total = ["# Кандидати в рецепти з Telegram", ""], 0
    for path in exports:
        data = json.loads(path.read_text(encoding="utf-8"))
        channel = data.get("name") or path.parent.name
        found = []
        for msg in data.get("messages", []):
            if msg.get("type") != "message":
                continue
            text = message_text(msg).strip()
            if len(text) < 80:
                continue
            sc = score(text)
            if sc >= args.min_score:
                found.append((msg, text, sc))
        print(f"{channel}: кандидатів {len(found)}, повідомлень {len(data.get('messages', []))}")
        total += len(found)
        out += [f"## {channel}", f"Файл: `{path.relative_to(SOURCES_DIR.parent).as_posix()}`", ""]
        for msg, text, sc in found:
            date = (msg.get("date") or "")[:10]
            photo = " · є фото" if msg.get("photo") else ""
            out += [f"### id {msg.get('id')} · {date} · оцінка {sc}{photo}", "", text, "", "---", ""]
    OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"Усього кандидатів: {total} → {OUT.relative_to(SOURCES_DIR.parent).as_posix()}")


if __name__ == "__main__":
    main()
