"""Валідує recipes/*.md, генерує data/recipes.json і вбудовує дані в site/index.html.

Запуск: python scripts/build.py [--check]   (--check: тільки валідація, без запису)
"""
import datetime as dt
import json
import re
import sys

from recipe_lib import (
    CATEGORIES, DATA_DIR, GUIDES_DIR, ROOT, NUTRIENT_KEYS, NUTRITION_STATUSES, SITE_FILE, SOURCE_TYPES,
    STATUSES, SUBCATEGORIES, UNITS, parse_stages, parse_steps, read_recipe, recipe_files, sections, utf8_stdout,
)

ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
TAG_RE = re.compile(r"^[a-zа-яіїєґʼ'0-9]+(-[a-zа-яіїєґʼ'0-9]+)*$")
MARKER_RE = re.compile(r"(<!-- DATA:START -->)(.*?)(<!-- DATA:END -->)", re.S)
WARNINGS = []
REQUIRED = ["id", "title", "source", "category", "tags", "servings", "time", "ingredients",
            "nutrition_per_serving", "nutrition_status", "status", "rating", "added"]
OPTIONAL = ["subcategory", "photo", "videos", "related", "form_cm",
            "cooked_g", "nutrition_per_100g", "cooked_g_est", "nutrition_notes"]


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate(meta, body, stem):
    errs = []
    for key in REQUIRED:
        if key not in meta:
            errs.append(f"бракує поля '{key}'")
    unknown = set(meta) - set(REQUIRED) - set(OPTIONAL)
    if unknown:
        errs.append(f"невідомі поля: {', '.join(sorted(unknown))}")
    if errs:
        return errs

    if meta["id"] != stem:
        errs.append(f"id '{meta['id']}' не збігається з назвою файлу '{stem}.md'")
    if not isinstance(meta["id"], str) or not ID_RE.match(meta["id"]):
        errs.append("id: тільки латиниця в нижньому регістрі, цифри й дефіси (kebab-case)")
    if not isinstance(meta["title"], str) or not meta["title"].strip():
        errs.append("title: порожня назва")

    src = meta["source"]
    if not isinstance(src, dict):
        errs.append("source: має містити type, name, ref")
    else:
        if src.get("type") not in SOURCE_TYPES:
            errs.append(f"source.type '{src.get('type')}': дозволено {', '.join(SOURCE_TYPES)}")
        for k in ("name", "ref"):
            if k not in src:
                errs.append(f"source.{k}: поле відсутнє (може бути порожнім рядком)")
        extra = set(src) - {"type", "name", "ref"}
        if extra:
            errs.append(f"source: невідомі поля {', '.join(sorted(extra))}")

    if meta["category"] not in CATEGORIES:
        errs.append(f"category '{meta['category']}': дозволено {', '.join(CATEGORIES)}")
    subs = SUBCATEGORIES.get(meta["category"])
    sub = meta.get("subcategory")
    if subs and sub not in subs:
        errs.append(f"subcategory '{sub}': для «{meta['category']}» обовʼязкове, дозволено: {'; '.join(subs)}")
    elif not subs and sub is not None:
        errs.append(f"subcategory: у «{meta['category']}» підрозділів немає, прибери поле")

    tags = meta["tags"]
    if not isinstance(tags, list):
        errs.append("tags: має бути списком, наприклад [швидко, на-вихідні]")
    else:
        for t in tags:
            if not isinstance(t, str) or not TAG_RE.match(t):
                errs.append(f"tags: '{t}' — малими літерами, слова через дефіс")

    if not isinstance(meta["servings"], int) or isinstance(meta["servings"], bool) or meta["servings"] < 1:
        errs.append("servings: ціле число від 1")

    time = meta["time"]
    if not isinstance(time, dict) or set(time) != {"prep", "cook"}:
        errs.append("time: має бути { prep: хв, cook: хв }")
    else:
        for k in ("prep", "cook"):
            if time[k] is not None and (not isinstance(time[k], int) or time[k] < 0):
                errs.append(f"time.{k}: ціле число хвилин або null")

    ings = meta["ingredients"]
    if not isinstance(ings, list) or not ings:
        errs.append("ingredients: непорожній список")
    else:
        for i, ing in enumerate(ings, 1):
            where = f"ingredients[{i}]"
            if not isinstance(ing, dict):
                errs.append(f"{where}: має бути {{ name, qty, unit, note }}")
                continue
            missing = {"name", "qty", "unit", "note"} - set(ing)
            if missing:
                errs.append(f"{where}: бракує {', '.join(sorted(missing))}")
                continue
            extra = set(ing) - {"name", "qty", "unit", "note", "part"}
            if extra:
                errs.append(f"{where}: невідомі поля {', '.join(sorted(extra))}")
            name = ing["name"]
            if not isinstance(name, str) or not name.strip():
                errs.append(f"{where}: порожня назва")
                continue
            where = f"інгредієнт '{name}'"
            if ing["qty"] is not None and (not is_num(ing["qty"]) or ing["qty"] <= 0):
                errs.append(f"{where}: qty має бути додатним числом або null")
            if ing["qty"] is None:
                if ing["unit"] not in ("", None) and ing["unit"] not in UNITS:
                    errs.append(f"{where}: невідома одиниця '{ing['unit']}'")
            elif ing["unit"] not in UNITS:
                errs.append(f"{where}: одиниця '{ing['unit']}' не з дозволених: {', '.join(UNITS)}")
            if not isinstance(ing["note"], str):
                errs.append(f"{where}: note має бути рядком (\"\", якщо нотатки немає)")
            part = ing.get("part")
            if part is not None and (not isinstance(part, str) or not part.strip() or part != part.lower()):
                errs.append(f"{where}: part — назва частини малими літерами, напр. «основа»")

    nut = meta["nutrition_per_serving"]
    if not isinstance(nut, dict) or set(nut) != set(NUTRIENT_KEYS):
        errs.append("nutrition_per_serving: має бути { kcal, protein, fat, carbs }")
    else:
        for k in NUTRIENT_KEYS:
            if nut[k] is not None and (not is_num(nut[k]) or nut[k] < 0):
                errs.append(f"nutrition_per_serving.{k}: невідʼємне число або null")
    if meta["nutrition_status"] not in NUTRITION_STATUSES:
        errs.append(f"nutrition_status '{meta['nutrition_status']}': дозволено {', '.join(NUTRITION_STATUSES)}")
    elif isinstance(nut, dict):
        filled = [nut.get(k) is not None for k in NUTRIENT_KEYS]
        if meta["nutrition_status"] == "немає" and any(filled):
            errs.append("nutrition_status 'немає', але КБЖВ заповнено")
        if meta["nutrition_status"] != "немає" and not all(filled):
            errs.append(f"nutrition_status '{meta['nutrition_status']}', але КБЖВ порожнє")

    if meta["status"] not in STATUSES:
        errs.append(f"status '{meta['status']}': дозволено {', '.join(STATUSES)}")
    r = meta["rating"]
    if r is not None and (not isinstance(r, int) or not 1 <= r <= 5):
        errs.append("rating: ціле від 1 до 5 або null")

    added = meta["added"]
    if not isinstance(added, dt.date):
        try:
            dt.date.fromisoformat(str(added))
        except ValueError:
            errs.append(f"added '{added}': дата у форматі YYYY-MM-DD")

    errs += validate_optional(meta)

    secs = sections(body)
    if "Кроки" not in secs:
        errs.append("у тілі немає розділу '## Кроки'")
    elif not parse_steps(secs["Кроки"]):
        errs.append("розділ '## Кроки' порожній: кроки нумерованим списком 1. 2. 3.")
    else:
        errs += validate_stages(secs["Кроки"], ings if isinstance(ings, list) else [])
    if "Мої нотатки" not in secs:
        errs.append("у тілі немає розділу '## Мої нотатки'")
    return errs


QTY_MARK_RE = re.compile(r"\{([^}]*)\}")
QTY_MARK_OK = re.compile(r"^\d+(?:[.,]\d+)?(?:\s+\S.*)?$")


def validate_stages(text, ings):
    """Частини й етапи: кожна part має етап «### Назва», кроки не губляться поза етапами, {кількість} у кроках коректна."""
    errs = []
    stages = parse_stages(text)
    parts = []
    for ing in ings:
        p = isinstance(ing, dict) and ing.get("part")
        if isinstance(p, str) and p not in parts:
            parts.append(p)
    for step in parse_steps(text):
        for mark in QTY_MARK_RE.findall(step):
            if not QTY_MARK_OK.match(mark.strip()):
                errs.append(f"крок: «{{{mark}}}» — у фігурних дужках число й одиниця, напр. {{100 г}}")
    if not stages:
        if parts:
            errs.append(f"інгредієнти поділено на частини ({', '.join(parts)}), а в «Кроках» немає етапів ### Назва")
        return errs
    if sum(len(s["steps"]) for s in stages) != len(parse_steps(text)):
        errs.append("у «Кроках» є нумеровані кроки до першого етапу ###: перенеси їх в етап")
    titles = [s["title"].lower() for s in stages]
    for s in stages:
        if not s["steps"]:
            errs.append(f"етап «{s['title']}» без кроків")
    for p in parts:
        if p not in titles:
            errs.append(f"частина «{p}» не має свого етапу: додай «### {p.capitalize()}» у «Кроки»")
    return errs


def validate_optional(meta):
    errs = []
    photo = meta.get("photo")
    if photo is not None:
        if not isinstance(photo, str) or not (SITE_FILE.parent / photo).is_file():
            errs.append(f"photo '{photo}': файлу немає в site/ (шлях відносно site/, напр. img/{meta['id']}.jpg)")
    videos = meta.get("videos")
    if videos is not None:
        if not isinstance(videos, list):
            errs.append("videos: список { title, file }")
        else:
            for v in videos:
                # file — локальна копія, url — посилання (Drive, YouTube); потрібне хоча б одне
                if (not isinstance(v, dict) or "title" not in v or not ({"file", "url"} & set(v))
                        or not set(v) <= {"title", "file", "url"} or not all(isinstance(x, str) for x in v.values())):
                    errs.append(f"videos: елемент {v} має бути {{ title, file?, url? }} і містити file або url")
                elif "url" in v and not v["url"].startswith("https://"):
                    errs.append(f"videos: url '{v['url']}' має починатися з https://")
                elif "file" in v and not (ROOT / v["file"]).is_file():
                    WARNINGS.append(f"recipes/{meta['id']}.md: відео '{v['file']}' немає на цьому компʼютері")
    related = meta.get("related")
    if related is not None and (not isinstance(related, list) or not all(isinstance(r, str) for r in related)):
        errs.append("related: список id рецептів")
    form = meta.get("form_cm")
    if form is not None and (not is_num(form) or form <= 0):
        errs.append("form_cm: діаметр форми в см, додатне число")
    # КБЖВ на 100 г готової страви: вага з джерела (cooked_g) або оцінка скрипта (cooked_g_est)
    for key in ("cooked_g", "cooked_g_est"):
        v = meta.get(key)
        if v is not None and (not isinstance(v, int) or v <= 0):
            errs.append(f"{key}: вага готової страви в грамах, ціле додатне число")
    n100 = meta.get("nutrition_per_100g")
    if n100 is not None:
        if not isinstance(n100, dict) or set(n100) != set(NUTRIENT_KEYS):
            errs.append("nutrition_per_100g: має бути { kcal, protein, fat, carbs }")
        elif any(n100[k] is not None and (not is_num(n100[k]) or n100[k] < 0) for k in NUTRIENT_KEYS):
            errs.append("nutrition_per_100g: невідʼємні числа або null")
    nn = meta.get("nutrition_notes")
    if nn is not None and (not isinstance(nn, list) or not all(isinstance(x, str) for x in nn)):
        errs.append("nutrition_notes: список рядків")
    return errs


def to_record(meta, body):
    secs = sections(body)
    rec = dict(meta)
    rec["added"] = str(meta["added"])
    rec["steps"] = parse_steps(secs.get("Кроки", ""))
    stages = parse_stages(secs.get("Кроки", ""))
    if stages:
        rec["stages"] = stages
    rec["tips"] = secs.get("Поради", "")
    rec["notes"] = secs.get("Мої нотатки", "")
    return rec


GUIDE_FIELDS = {"id", "title", "section", "order", "source", "related"}


def load_guides(problems):
    """guides/*.md: довідкові статті (теорія), окремо від рецептів."""
    guides = []
    for path in sorted(GUIDES_DIR.glob("*.md")):
        key = f"guides/{path.name}"
        try:
            meta, body = read_recipe(path)
        except ValueError as e:
            problems[key] = [str(e)]
            continue
        errs = []
        missing = {"id", "title", "section", "order", "source"} - set(meta)
        if missing:
            errs.append(f"бракує полів: {', '.join(sorted(missing))}")
        extra = set(meta) - GUIDE_FIELDS
        if extra:
            errs.append(f"невідомі поля: {', '.join(sorted(extra))}")
        if meta.get("id") != path.stem:
            errs.append(f"id '{meta.get('id')}' не збігається з назвою файлу")
        if not isinstance(meta.get("order"), int):
            errs.append("order: ціле число")
        if not body.strip():
            errs.append("порожній текст")
        if errs:
            problems[key] = errs
            continue
        guides.append({"id": meta["id"], "title": meta["title"], "section": meta["section"], "order": meta["order"],
                       "source": meta["source"], "related": meta.get("related") or [], "body": body.strip()})
    return sorted(guides, key=lambda g: (g["section"], g["order"]))


def main():
    utf8_stdout()
    check_only = "--check" in sys.argv
    files = recipe_files()
    records, problems, seen = [], {}, {}
    for path in files:
        try:
            meta, body = read_recipe(path)
            errs = validate(meta, body, path.stem)
        except ValueError as e:
            errs = [str(e)]
        if errs:
            problems[path.name] = errs
            continue
        key = meta["title"].strip().lower()
        if key in seen:
            problems[path.name] = [f"така сама назва, як у {seen[key]}"]
            continue
        seen[key] = path.name
        records.append(to_record(meta, body))

    guides = load_guides(problems)
    recipe_ids, guide_ids = {r["id"] for r in records}, {g["id"] for g in guides}
    for c in recipe_ids & guide_ids:
        problems[f"guides/{c}.md"] = ["id збігається з id рецепта"]
    ids = recipe_ids | guide_ids
    for item, prefix in [(r, "") for r in records] + [(g, "guides/") for g in guides]:
        missing = [x for x in item.get("related") or [] if x not in ids]
        if missing:
            problems[prefix + item["id"] + ".md"] = [f"related: немає рецептів чи статей {', '.join(missing)}"]

    if problems:
        print(f"Помилки валідації ({len(problems)} з {len(files)} файлів):")
        for name, errs in problems.items():
            print(f"\n  {name if name.startswith('guides/') else 'recipes/' + name}")
            for e in errs:
                print(f"    - {e}")
        print("\nНічого не записано. Виправ і запусти ще раз.")
        sys.exit(1)

    for w in WARNINGS:
        print(f"Увага: {w}")
    records.sort(key=lambda r: r["title"])
    print(f"Валідація пройдена, рецептів: {len(records)}, статей довідника: {len(guides)}.")
    if check_only:
        return

    payload = json.dumps(records, ensure_ascii=False, indent=2)
    (DATA_DIR / "recipes.json").write_text(payload + "\n", encoding="utf-8")
    (DATA_DIR / "guides.json").write_text(json.dumps(guides, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    html = SITE_FILE.read_text(encoding="utf-8")
    if not MARKER_RE.search(html):
        print(f"У {SITE_FILE} немає маркерів <!-- DATA:START --> / <!-- DATA:END -->")
        sys.exit(1)
    inline = json.dumps(records, ensure_ascii=False).replace("</", "<\\/")
    inline_g = json.dumps(guides, ensure_ascii=False).replace("</", "<\\/")
    block = (f'\n<script id="recipes-data" type="application/json">{inline}</script>\n'
             f'<script id="guides-data" type="application/json">{inline_g}</script>\n')
    html = MARKER_RE.sub(lambda m: m.group(1) + block + m.group(3), html, count=1)
    SITE_FILE.write_text(html, encoding="utf-8", newline="\n")
    print("Записано data/recipes.json, data/guides.json і site/index.html")


if __name__ == "__main__":
    main()
