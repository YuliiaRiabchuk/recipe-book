"""Поправки на готування для КБЖВ і вага готової страви.

КБЖВ страви = Σ (сира вага × значення на 100 г / 100) з поправками, де готування реально змінює
калорійність, а не лише вагу:
  - олія для смаження: рахується лише вбрана частина — 8 г на 100 г обсмаженої їжі,
    12 г — у паніровці чи тісті (сирники, оладки, котлети), але не більше, ніж олії в рецепті;
  - жирне мʼясо (фарш, свинина, бекон), що смажиться чи запікається: жир ×0,8 (стікає);
  - розсіл і маринад, які не їдять (підрозділ «мариновані»): цукор, мед, оцет, олія ×0,25.
Білки й вуглеводи при нагріванні вважаємо незмінними.

Вага готової страви (для «на 100 г»): поле cooked_g з джерела, інакше оцінка —
сира вага × коефіцієнт виходу:
  - крупи сухі ×2,8 (рис) / ×3 (гречка, кіноа, булгур, пшоно, перловка) / кускус ×2,5,
    паста й локшина ×2,3, бобові сухі ×2,5 — вода на варіння, якщо вона є в рецепті, входить сюди;
  - мʼясо ×0,72, птиця ×0,75, фарш ×0,75, риба ×0,82, морепродукти ×0,85 (у готових стравах);
  - овочі: запікання/смаження ×0,85, варіння й тушкування ×0,95, сирі ×1;
  - випічка й запечені десерти: усе тісто/маса ×0,9;
  - супи: рідина ×0,9;
  - решта рідини в гарячих стравах ×0,7 (частково випаровується);
  - холодні страви, салати, без випікання: ×1.
Джерела: USDA Table of Cooking Yields for Meat and Poultry; Bognár 2002 (BFE-R-02-03);
огляд поглинання жиру при смаженні, Grasas y Aceites. Коефіцієнти середні — результат є оцінкою.
"""
import re

GRAIN_YIELD = [
    (r"\brice\b", 2.8), (r"buckwheat", 3.0), (r"quinoa", 3.0), (r"bulgur", 3.0), (r"millet", 3.0),
    (r"barley", 3.0), (r"couscous", 2.5),
    (r"pasta|spaghetti|macaroni|noodles", 2.3),
    (r"(lentils|beans|chickpeas|peas).*(mature seeds|dry)|(mature seeds|dry).*(lentils|beans|chickpeas|peas)", 2.5),
]
DRY_HINT = re.compile(r"\b(dry|uncooked|raw|mature seeds)\b")
COOKED_HINT = re.compile(r"\b(cooked|boiled|canned|roasted, cooked|prepared)\b")
MEAT = [(r"\bground\b", 0.75), (r"chicken|turkey|duck|poultry", 0.75),
        (r"beef|pork|veal|lamb|rabbit|liver", 0.72),
        (r"shrimp|squid|mussels|seafood|octopus|scallop|crab", 0.85),
        (r"fish|salmon|cod|tilapia|herring|mackerel|tuna, fresh|pike|carp|trout|pollock|hake|perch|catfish", 0.82)]
FATTY_MEAT = re.compile(r"\bground\b|pork|bacon|sausage")
OIL = re.compile(r"\boil\b|shortening|lard|butter")
VEG = re.compile(r"vegetable|squash|pumpkin|carrot|onion|cabbage|broccoli|cauliflower|pepper|tomato|potato|"
                 r"zucchini|eggplant|beet|spinach|mushroom|celery|leek|garlic|bean, snap|peas, green|corn, sweet|asparagus")
LIQUID = re.compile(r"^(water|beverages|milk|cream|broth|soup|stock)|\bbroth\b|\bstock\b|milk, |^cream, ")
FRYING_NOTE = re.compile(r"смаж|сковор|змаст|для форми|обсмаж", re.I)
BRINE_DROP = re.compile(r"sugar|honey|vinegar|\boil\b|syrup")


def method(meta):
    """'raw' | 'baked' | 'soup' | 'cooked'."""
    tags, cat = set(meta.get("tags") or []), meta.get("category")
    cook = (meta.get("time") or {}).get("cook") or 0
    if "без-випікання" in tags or cat in ("салати",) or (cat in ("закуски", "соуси", "напої") and not cook):
        return "raw"
    if cat == "супи":
        return "soup"
    if cat in ("випічка", "десерти") and ("в-духовці" in tags or cook):
        return "baked"
    if cook or tags & {"в-духовці", "на-сковороді", "гриль", "мультиварка"}:
        return "cooked"
    return "raw"


def adjust(meta, rows):
    """rows: [{name, note, desc, grams, values}] → (totals, cooked_weight_est, notes)."""
    m = method(meta)
    fried = m in ("cooked", "baked")
    battered = bool(re.search(r"сирник|оладк|котлет|деруни|млинц|налисник|паніров", meta.get("title", "").lower()))
    marinade = meta.get("subcategory") == "мариновані"
    totals = {"kcal": 0.0, "protein": 0.0, "fat": 0.0, "carbs": 0.0}
    notes, weight = [], 0.0

    # «тверде», що смажиться: усе, крім жирів і рідин (вода приходить рядком без нутрієнтів)
    solids = sum(r["grams"] for r in rows if not OIL.search(r["desc"].lower()) and not LIQUID.search(r["desc"].lower()))
    grain_absorb = 0.0
    for r in rows:
        d = r["desc"].lower()
        for pat, f in GRAIN_YIELD:
            if re.search(pat, d) and DRY_HINT.search(d) and not COOKED_HINT.search(d) and m != "raw":
                grain_absorb += r["grams"] * (f - 1)
                break

    for r in rows:
        d, g, v = r["desc"].lower(), r["grams"], dict(r["values"])
        factor_nutr = 1.0
        # олія для смаження: лише вбрана частина (вершкове масло зазвичай іде в тісто, його не чіпаємо)
        is_oil = bool(OIL.search(d)) and "butter" not in d
        frying = is_oil and fried and (FRYING_NOTE.search(r["note"] or "") or
                                       ("на-сковороді" in (meta.get("tags") or []) and m == "cooked"))
        if frying:
            absorbed = min(g, solids * (0.12 if battered else 0.08))
            if absorbed < g:
                notes.append(f"олія для смаження: враховано {round(absorbed)} г із {round(g)} г")
            factor_nutr = absorbed / g if g else 1.0
            g_weight = absorbed
        # маринад, який не їдять
        elif marinade and BRINE_DROP.search(d):
            factor_nutr = 0.25
            g_weight = g * 0.25
            notes.append(f"{r['name']}: у розсолі, враховано 25 %")
        else:
            g_weight = g
        for k in totals:
            totals[k] += v[k] * g / 100 * factor_nutr
        # жир, що стікає з жирного мʼяса
        if FATTY_MEAT.search(d) and m in ("cooked", "baked") and "raw" in d:
            drip = v["fat"] * g / 100 * 0.2
            totals["fat"] -= drip
            totals["kcal"] -= drip * 9
            notes.append(f"{r['name']}: −20 % жиру (стікає)")
        weight += yield_weight(d, g_weight, m)

    # вода на варіння круп/пасти: замінюється на воду, яку вони вбирають
    water = sum(r["grams"] for r in rows if r["desc"].lower().startswith("water"))
    if grain_absorb:
        weight += grain_absorb - min(water, grain_absorb) * (0.7 if m == "cooked" else 0.9)
    return totals, round(weight), sorted(set(notes))


def yield_weight(d, g, m):
    if m == "raw":
        return g
    if m == "baked":
        return g * 0.9
    if LIQUID.search(d):
        return g * (0.9 if m == "soup" else 0.7)
    for pat, f in MEAT:
        if re.search(pat, d) and "raw" in d:
            return g * f
    for pat, f in GRAIN_YIELD:
        if re.search(pat, d) and DRY_HINT.search(d) and not COOKED_HINT.search(d):
            return g  # набрану воду додає adjust() через grain_absorb
    if VEG.search(d) and "raw" in d:
        return g * (0.95 if m == "soup" else 0.85)
    return g
