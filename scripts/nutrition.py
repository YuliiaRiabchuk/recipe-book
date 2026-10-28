"""КБЖВ через USDA FoodData Central.

  python scripts/nutrition.py --all                 перерахувати всі рецепти
  python scripts/nutrition.py <id> [<id> ...]       перерахувати вибрані
  python scripts/nutrition.py confirm "щавель" <fdc_id> [--per шт=60 --per зубчик=5]
  python scripts/nutrition.py ignore "вода"         не рахувати інгредієнт

Ключ API: FDC_API_KEY у .env (https://api.data.gov/signup).
"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from recipe_lib import (
    DATA_DIR, RECIPES_DIR, find_recipe, load_env, read_recipe, recipe_files,
    split_frontmatter, utf8_stdout,
)
import cooking
import usda_local

API = "https://api.nal.usda.gov/fdc/v1"
DATA_TYPES = ["Foundation", "SR Legacy"]
MAP_FILE = DATA_DIR / "ingredients_map.json"
HINTS_FILE = DATA_DIR / "search_hints.json"
UNMATCHED_FILE = DATA_DIR / "unmatched.md"
CACHE_DIR = DATA_DIR / "fdc_cache"

# Не рахуються і на статус не впливають
SKIP_NAMES = {
    "сіль", "морська сіль", "перець", "чорний перець", "перець чорний", "перець чорний мелений",
    "мелений перець", "запашний перець", "лавровий лист", "спеції", "приправа", "приправи",
    "вода", "кориця", "мускатний горіх", "куркума", "паприка", "кмин", "гвоздика", "ванілін",
    "сода", "харчова сода", "розпушувач", "лимонна кислота",
}
# мл = г
WATER_LIKE = {"вода", "молоко", "кефір", "бульйон", "овочевий бульйон", "курячий бульйон",
              "мʼясний бульйон", "ряжанка", "йогурт питний"}
ML_PER = {"мл": 1, "л": 1000, "склянка": 250, "ст.л.": 15, "ч.л.": 5}
US_VOLUME_ML = [  # (шаблон у foodPortions, мл в одиниці)
    (r"\btbsp\b|tablespoon", 14.787),
    (r"\bcup\b", 236.588),
    (r"\btsp\b|teaspoon", 4.929),
    (r"fl oz", 29.574),
    (r"\bml\b", 1.0),
]
NUTRIENT_NUMBERS = {
    "kcal": ["208", "957", "958"],
    "protein": ["203"],
    "fat": ["204"],
    "carbs": ["205", "205.2"],
}
NOTE_PREFIX = "> КБЖВ частковий:"


class FdcError(Exception):
    pass


def norm(name):
    return re.sub(r"\s+", " ", name.strip().lower().replace("'", "ʼ").replace("’", "ʼ"))


def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8") or "null") or default
    return default


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# ---------- API ----------

LOCAL = "local"  # замість ключа: працюємо з локальною копією USDA (scripts/usda_local.py)


def api_key():
    if usda_local.available():
        return LOCAL
    load_env()
    key = os.environ.get("FDC_API_KEY", "").strip()
    if not key:
        print("FDC_API_KEY не задано. Безкоштовний ключ: https://api.data.gov/signup\n"
              "Впиши його в .env рядком FDC_API_KEY=... і запусти ще раз.")
        sys.exit(2)
    if key == "DEMO_KEY":
        print("DEMO_KEY має жорсткий ліміт і для обробки рецептів не використовується. "
              "Отримай власний ключ: https://api.data.gov/signup")
        sys.exit(2)
    return key


def cached(name, fetch):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / name
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    data = fetch()
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def request(url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise FdcError("API відхилив ключ (403). Перевір FDC_API_KEY у .env.") from None
        if e.code == 429:
            raise FdcError("Перевищено ліміт запитів FDC (429). Спробуй пізніше.") from None
        raise FdcError(f"FDC відповів {e.code}: {e.reason}") from None
    except urllib.error.URLError as e:
        raise FdcError(f"Немає зʼєднання з FDC: {e.reason}") from None


def search(query, key):
    if key == LOCAL:
        return usda_local.search(query, 3)
    h = hashlib.sha1(query.lower().encode()).hexdigest()[:16]
    return cached(f"search_{h}.json", lambda: request(
        f"{API}/foods/search?api_key={key}",
        {"query": query, "dataType": DATA_TYPES, "pageSize": 3},
    )).get("foods", [])[:3]


def food(fdc_id, key):
    if key == LOCAL:
        try:
            return usda_local.food(fdc_id)
        except KeyError as e:
            raise FdcError(str(e)) from None
    return cached(f"food_{fdc_id}.json", lambda: request(f"{API}/food/{int(fdc_id)}?api_key={key}"))


def per_100g(food_data):
    """{kcal, protein, fat, carbs} на 100 г з деталей продукту."""
    by_num = {}
    for n in food_data.get("foodNutrients", []):
        num = str((n.get("nutrient") or {}).get("number") or n.get("nutrientNumber") or "")
        amount = n.get("amount", n.get("value"))
        if num and amount is not None and num not in by_num:
            by_num[num] = float(amount)
    out = {}
    for key, nums in NUTRIENT_NUMBERS.items():
        out[key] = next((by_num[n] for n in nums if n in by_num), None)
    return out


def portions(food_data):
    """[(текст опису, грам на одиницю)] з foodPortions."""
    out = []
    for p in food_data.get("foodPortions", []) or []:
        grams, amount = p.get("gramWeight"), p.get("amount") or 1
        if not grams:
            continue
        text = " ".join(str(x) for x in [
            (p.get("measureUnit") or {}).get("name", ""), p.get("modifier", ""), p.get("portionDescription", ""),
        ] if x).lower()
        out.append((text, grams / amount))
    return out


def density_from_portions(food_data):
    for pattern, ml in US_VOLUME_ML:
        for text, grams in portions(food_data):
            if re.search(pattern, text):
                return round(grams / ml, 3)
    return None


def piece_from_portions(food_data):
    for word in ("medium", "whole", "large", "small", "clove", "piece", "slice"):
        for text, grams in portions(food_data):
            if re.search(rf"\b{word}\b", text) and not re.search(r"cup|tbsp|tsp|oz|ml", text):
                return round(grams, 1)
    return None


# ---------- розрахунок ----------

def to_grams(ing, entry, food_data):
    """Повертає (грами, None) або (None, причина)."""
    qty, unit, name = ing["qty"], ing["unit"], norm(ing["name"])
    grams_per = entry.get("grams_per") or {}
    if unit == "г":
        return qty, None
    if unit == "кг":
        return qty * 1000, None
    if grams_per.get(unit):
        return qty * grams_per[unit], None
    if unit in ML_PER:
        ml = qty * ML_PER[unit]
        if name in WATER_LIKE:
            return ml, None
        density = entry.get("g_per_ml") or density_from_portions(food_data)
        if density:
            return ml * density, None
        return None, f"невідома густина для «{unit}»"
    if unit == "шт":
        g = piece_from_portions(food_data)
        if g:
            return qty * g, None
    return None, f"невідома вага одиниці «{unit}» (додай --per {unit}=<г> у confirm)"


def is_skipped(ing, mapping):
    name = norm(ing["name"])
    if ing["qty"] is None or "за смаком" in (ing.get("note") or "").lower():
        return True
    if name in SKIP_NAMES or (mapping.get(name) or {}).get("ignore"):
        return True
    return False


WEIGHT_ONLY_UNITS = {"г": 1, "кг": 1000, "мл": 1, "л": 1000, "склянка": 250}


def rounded(totals, div):
    out = {k: round(v / div, 1) for k, v in totals.items()}
    out["kcal"] = int(round(totals["kcal"] / div))
    return out


def compute(meta, mapping, key, pending):
    """→ (на порцію, статус, чого бракує, на 100 г, оцінена вага готової страви або None, поправки)."""
    rows, missing = [], []
    zero = dict.fromkeys(NUTRIENT_NUMBERS, 0.0)
    for ing in meta["ingredients"]:
        name = norm(ing["name"])
        if is_skipped(ing, mapping):
            # вода, сіль тощо: калорій немає, але в супах і кашах вони дають вагу готової страви
            if ing["qty"] is not None and ing["unit"] in WEIGHT_ONLY_UNITS:
                rows.append({"name": ing["name"], "note": ing.get("note") or "", "desc": "water" if name == "вода" else name,
                             "grams": ing["qty"] * WEIGHT_ONLY_UNITS[ing["unit"]], "values": zero})
            continue
        entry = mapping.get(name)
        if not entry:
            pending.setdefault(name, set()).add(meta["id"])
            missing.append(f"{ing['name']} (немає у словнику)")
            continue
        food_data = food(entry["fdc_id"], key)
        grams, reason = to_grams(ing, entry, food_data)
        if grams is None:
            missing.append(f"{ing['name']} ({reason})")
            continue
        values = per_100g(food_data)
        # share: яка частка інгредієнта — цей продукт (закваска 100 % = половина борошна, решта вода)
        share = entry.get("share") or 1
        values = {k: (v * share if v is not None else None) for k, v in values.items()}
        if any(v is None for v in values.values()):
            gaps = ", ".join(k for k, v in values.items() if v is None)
            missing.append(f"{ing['name']} (у USDA немає: {gaps})")
            continue
        rows.append({"name": ing["name"], "note": ing.get("note") or "", "desc": food_data.get("description", ""),
                     "grams": grams, "values": values})

    if not any(r["values"] is not zero for r in rows):
        return {k: None for k in NUTRIENT_NUMBERS}, "немає", missing, {k: None for k in NUTRIENT_NUMBERS}, None, []
    totals, weight_est, notes = cooking.adjust(meta, rows)
    weight = meta.get("cooked_g") or weight_est
    per = rounded(totals, meta["servings"])
    per100 = rounded(totals, weight / 100) if weight else {k: None for k in NUTRIENT_NUMBERS}
    return per, ("частковий" if missing else "повний"), missing, per100, (None if meta.get("cooked_g") else weight_est), notes


def yaml_num(v):
    return "null" if v is None else str(v)


def set_line(fm, key, line, after):
    """Замінює рядок `key: ...` або вставляє його після рядка `after: ...`; line=None прибирає."""
    pat = re.compile(rf"^{key}:.*\n?", re.M)
    if line is None:
        return pat.sub("", fm)
    if pat.search(fm):
        return pat.sub(line + "\n", fm, count=1).rstrip("\n")
    return re.sub(rf"^({after}:.*)$", lambda m: m.group(1) + "\n" + line, fm, count=1, flags=re.M)


def write_back(path, per, status, missing, per100=None, weight_est=None, notes=()):
    text = path.read_text(encoding="utf-8")
    fm, body = split_frontmatter(text)
    nut = "nutrition_per_serving: { " + ", ".join(f"{k}: {yaml_num(per[k])}" for k in NUTRIENT_NUMBERS) + " }"
    fm = re.sub(r"^nutrition_per_serving:.*$", nut, fm, count=1, flags=re.M)
    fm = re.sub(r"^nutrition_status:.*$", f"nutrition_status: {status}", fm, count=1, flags=re.M)
    has100 = per100 and per100.get("kcal") is not None
    fm = set_line(fm, "nutrition_per_100g", ("nutrition_per_100g: { " + ", ".join(
        f"{k}: {yaml_num(per100[k])}" for k in NUTRIENT_NUMBERS) + " }") if has100 else None, "nutrition_per_serving")
    fm = set_line(fm, "cooked_g_est", f"cooked_g_est: {weight_est}" if has100 and weight_est else None, "nutrition_per_100g")
    fm = set_line(fm, "nutrition_notes", ("nutrition_notes: [" + ", ".join(json.dumps(n, ensure_ascii=False) for n in notes) + "]")
                  if has100 and notes else None, "nutrition_status")

    lines = [l for l in body.rstrip("\n").split("\n") if not l.startswith(NOTE_PREFIX)]
    body = "\n".join(lines).rstrip("\n") + "\n"
    if status == "частковий":
        note = f"{NOTE_PREFIX} не пораховано {'; '.join(missing)}."
        if re.search(r"^## Мої нотатки\s*$", body, re.M):
            body = body.rstrip("\n") + "\n" + note + "\n"
        else:
            body += f"\n## Мої нотатки\n{note}\n"
    path.write_text(f"---\n{fm}\n---\n{body}", encoding="utf-8", newline="\n")


# ---------- unmatched.md ----------

def read_unmatched():
    if not UNMATCHED_FILE.exists():
        return {}
    blocks = {}
    for chunk in re.split(r"^## ", UNMATCHED_FILE.read_text(encoding="utf-8"), flags=re.M)[1:]:
        name, _, rest = chunk.partition("\n")
        blocks[norm(name)] = rest.strip()
    return blocks


def write_unmatched(blocks):
    if not blocks:
        UNMATCHED_FILE.write_text("# Інгредієнти, що чекають підтвердження\n\nПорожньо.\n", encoding="utf-8")
        return
    out = ["# Інгредієнти, що чекають підтвердження", "",
           "Обери варіант і підтверди: `python scripts/nutrition.py confirm \"назва\" <fdc_id>`. "
           "Для одиниць шт/зубчик/пучок додай вагу: `--per шт=60`. "
           "Не рахувати: `python scripts/nutrition.py ignore \"назва\"`.", ""]
    for name in sorted(blocks):
        out += [f"## {name}", blocks[name], ""]
    UNMATCHED_FILE.write_text("\n".join(out), encoding="utf-8")


def candidates_block(name, recipes, key, hints):
    query = hints.get(name)
    lines = [f"Рецепти: {', '.join(sorted(recipes))}"]
    if not query:
        lines.append(f"Немає англійського запиту. Додай у data/search_hints.json: \"{name}\": \"...\" і перерахуй.")
        return "\n".join(lines)
    lines.append(f"Запит у FDC: `{query}`")
    foods = search(query, key)
    if not foods:
        lines.append("Нічого не знайдено. Зміни запит у data/search_hints.json.")
    for i, f in enumerate(foods, 1):
        kcal = next((n.get("value") for n in f.get("foodNutrients", [])
                     if str(n.get("nutrientNumber")) in ("208", "957", "958")), None)
        kcal_s = f" — {round(kcal)} ккал/100 г" if kcal is not None else ""
        lines.append(f"{i}. `{f['fdcId']}` {f['description']} ({f.get('dataType')}){kcal_s}")
    return "\n".join(lines)


# ---------- команди ----------

def cmd_compute(refs, compute_all):
    key = api_key()
    mapping = load_json(MAP_FILE, {})
    hints = {norm(k): v for k, v in load_json(HINTS_FILE, {}).items()}
    paths = recipe_files() if compute_all else []
    for ref in refs:
        p = find_recipe(ref)
        if not p:
            print(f"Рецепт '{ref}' не знайдено в {RECIPES_DIR}")
            sys.exit(1)
        paths.append(p)
    if not paths:
        print("Вкажи id рецепта або --all")
        sys.exit(1)

    pending, summary = {}, []
    try:
        for path in paths:
            meta, _ = read_recipe(path)
            per, status, missing, per100, weight_est, notes = compute(meta, mapping, key, pending)
            write_back(path, per, status, missing, per100, weight_est, notes)
            summary.append((path.stem, status, per100, missing))
        blocks = read_unmatched()
        for name in list(blocks):
            if name in mapping:
                del blocks[name]
        for name, recipes in pending.items():
            blocks[name] = candidates_block(name, recipes, key, hints)
        write_unmatched(blocks)
    except FdcError as e:
        print(f"Помилка FDC: {e}")
        sys.exit(3)

    for stem, status, per, missing in summary:
        nut = "—" if per["kcal"] is None else f"на 100 г: {per['kcal']} ккал, Б {per['protein']}, Ж {per['fat']}, В {per['carbs']}"
        print(f"{stem}: {status} ({nut})")
        for m in missing:
            print(f"   · {m}")
    print(f"Чекають підтвердження в data/unmatched.md: {len(read_unmatched())}")


def cmd_confirm(name, fdc_id, per_args):
    key = api_key()
    name = norm(name)
    try:
        food_data = food(fdc_id, key)
    except FdcError as e:
        print(f"Помилка FDC: {e}")
        sys.exit(3)
    if food_data.get("dataType") not in DATA_TYPES:
        print(f"{fdc_id} має тип {food_data.get('dataType')}; дозволено тільки {', '.join(DATA_TYPES)}")
        sys.exit(1)
    density = density_from_portions(food_data)
    grams_per = {"шт": piece_from_portions(food_data),
                 "ст.л.": round(density * 14.787, 1) if density else None,
                 "ч.л.": round(density * 4.929, 1) if density else None}
    for item in per_args or []:
        unit, _, grams = item.partition("=")
        try:
            grams_per[unit.strip()] = float(grams)
        except ValueError:
            print(f"--per {item}: формат одиниця=грами, наприклад шт=60")
            sys.exit(1)
    mapping = load_json(MAP_FILE, {})
    mapping[name] = {"fdc_id": int(fdc_id), "fdc_name": food_data.get("description"),
                     "grams_per": grams_per, "g_per_ml": density}
    save_json(MAP_FILE, mapping)
    blocks = read_unmatched()
    blocks.pop(name, None)
    write_unmatched(blocks)
    print(f"{name} → {food_data.get('description')} ({fdc_id}); grams_per={grams_per}, g_per_ml={density}")


def cmd_ignore(name):
    name = norm(name)
    mapping = load_json(MAP_FILE, {})
    mapping[name] = {"ignore": True}
    save_json(MAP_FILE, mapping)
    blocks = read_unmatched()
    blocks.pop(name, None)
    write_unmatched(blocks)
    print(f"{name}: більше не рахується")


def main():
    utf8_stdout()
    argv = sys.argv[1:]
    if argv and argv[0] == "confirm":
        p = argparse.ArgumentParser(prog="nutrition.py confirm")
        p.add_argument("name")
        p.add_argument("fdc_id", type=int)
        p.add_argument("--per", action="append", help="одиниця=грами, напр. шт=60")
        a = p.parse_args(argv[1:])
        cmd_confirm(a.name, a.fdc_id, a.per)
    elif argv and argv[0] == "ignore":
        if len(argv) != 2:
            print('Формат: nutrition.py ignore "назва"')
            sys.exit(1)
        cmd_ignore(argv[1])
    else:
        p = argparse.ArgumentParser(prog="nutrition.py")
        p.add_argument("recipes", nargs="*")
        p.add_argument("--all", action="store_true")
        a = p.parse_args(argv)
        cmd_compute(a.recipes, a.all)


if __name__ == "__main__":
    main()
