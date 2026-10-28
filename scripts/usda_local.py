"""Локальна копія USDA FoodData Central (Foundation + SR Legacy) замість API.

Сирі CSV лежать у data/fdc_cache/usda/ (не комітяться). Звідти один раз збирається
компактний індекс data/fdc_cache/usda/index.json: на продукт — назва, тип, КБЖВ на 100 г
і порції (ложка, чашка, штука) у грамах.

  python scripts/usda_local.py build            зібрати індекс із CSV
  python scripts/usda_local.py search "sour cream"   знайти продукт за англійськими словами
"""
import csv
import json
import re
import sys
from pathlib import Path

from recipe_lib import DATA_DIR, utf8_stdout

USDA_DIR = DATA_DIR / "fdc_cache" / "usda"
INDEX = USDA_DIR / "index.json"
KEEP_TYPES = {"foundation_food": "Foundation", "sr_legacy_food": "SR Legacy"}
# nutrient_id з CSV → номер нутрієнта, який використовує nutrition.py
NUTRIENTS = {"1008": "208", "2047": "957", "2048": "958", "1003": "203", "1004": "204", "1005": "205", "1050": "205.2"}

_cache = None


def _dataset_dirs():
    return [p.parent for p in USDA_DIR.glob("*/*/food.csv")]


def build():
    csv.field_size_limit(10 ** 8)
    foods = {}
    for d in _dataset_dirs():
        units = {r["id"]: r["name"] for r in csv.DictReader(open(d / "measure_unit.csv", encoding="utf-8"))}
        with open(d / "food.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["data_type"] in KEEP_TYPES:
                    foods[r["fdc_id"]] = {"description": r["description"], "dataType": KEEP_TYPES[r["data_type"]],
                                          "foodNutrients": [], "foodPortions": []}
        with open(d / "food_nutrient.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                food = foods.get(r["fdc_id"])
                nbr = NUTRIENTS.get(r["nutrient_id"])
                if food is not None and nbr and r["amount"] not in ("", None):
                    food["foodNutrients"].append({"nutrient": {"number": nbr}, "amount": float(r["amount"])})
        with open(d / "food_portion.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                food = foods.get(r["fdc_id"])
                if food is None or not r["gram_weight"]:
                    continue
                unit = units.get(r["measure_unit_id"], "")
                food["foodPortions"].append({
                    "gramWeight": float(r["gram_weight"]), "amount": float(r["amount"] or 1) or 1,
                    "modifier": r["modifier"], "portionDescription": r["portion_description"],
                    "measureUnit": {"name": "" if unit == "undetermined" else unit},
                })
    INDEX.write_text(json.dumps(foods, ensure_ascii=False), encoding="utf-8")
    print(f"Індекс: {len(foods)} продуктів → {INDEX.relative_to(DATA_DIR.parent).as_posix()}")


def available():
    return INDEX.exists()


def foods():
    global _cache
    if _cache is None:
        _cache = json.loads(INDEX.read_text(encoding="utf-8"))
    return _cache


def food(fdc_id):
    f = foods().get(str(int(fdc_id)))
    if f is None:
        raise KeyError(f"fdc_id {fdc_id} немає в локальній базі USDA")
    return f


def search(query, limit=3):
    """Ранжування за збігом слів запиту з назвою; сирі продукти й Foundation вище."""
    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 1]
    scored = []
    for fid, f in foods().items():
        desc = f["description"].lower()
        tokens = re.findall(r"[a-z0-9]+", desc)
        hit = sum(1 for w in words if any(t.startswith(w) for t in tokens))
        if not hit:
            continue
        score = hit / len(words) - 0.01 * len(tokens)
        if desc.startswith(words[0]):
            score += 0.3
        if "raw" in tokens:
            score += 0.05
        if f["dataType"] == "Foundation":
            score += 0.02
        scored.append((score, fid, f))
    scored.sort(key=lambda x: -x[0])
    out = []
    for _, fid, f in scored[:limit]:
        kcal = next((n["amount"] for n in f["foodNutrients"] if n["nutrient"]["number"] in ("208", "957", "958")), None)
        out.append({"fdcId": int(fid), "description": f["description"], "dataType": f["dataType"],
                    "foodNutrients": [{"nutrientNumber": "208", "value": kcal}] if kcal is not None else []})
    return out


if __name__ == "__main__":
    utf8_stdout()
    if len(sys.argv) >= 2 and sys.argv[1] == "build":
        build()
    elif len(sys.argv) == 3 and sys.argv[1] == "show":
        f = food(sys.argv[2])
        print(f"{sys.argv[2]}  {f['dataType']}  {f['description']}")
        for n in f["foodNutrients"]:
            print(f"   nutrient {n['nutrient']['number']}: {n['amount']}")
        for p in f["foodPortions"]:
            print(f"   portion: {p['amount']} {p['measureUnit']['name']} {p['modifier']} {p['portionDescription']} = {p['gramWeight']} г")
    elif len(sys.argv) >= 3 and sys.argv[1] == "search":
        for f in search(" ".join(sys.argv[2:]), 8):
            kcal = f["foodNutrients"][0]["value"] if f["foodNutrients"] else "?"
            print(f"{f['fdcId']:>8}  {f['dataType']:<10}  {kcal!s:>6} ккал  {f['description']}")
    else:
        print(__doc__)
