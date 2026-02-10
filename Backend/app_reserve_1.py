# Резервный №1
# Snapshot of backend logic as of 2026-01-27.
#
# This file is intentionally a verbatim copy of app.py at the moment
# the user approved the capsule composition rules (gender/season/category).
#
# To restore: replace Backend/app.py with this file's contents.

# ML-зависимости
import os
import sys
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Импорты
from flask import Flask, request, send_file, Response
from wb_client import wb_search_cards
from wb_image_loader import get_image_bytes
import io
import random
from flask_cors import CORS
# LLM is optional; backend must work without it
try:
    from ML.llm_enrich import enrich_product_name  # type: ignore
except Exception:
    enrich_product_name = None


# Правила совместимости и запросы
COMPLEMENT = {
    "bottoms": ["tops", "outerwear", "footwear"],
    "tops": ["bottoms", "outerwear", "footwear"],
    "outerwear": ["tops", "bottoms", "footwear"],
    # Для обуви нам обычно нужны верх + низ + верхняя одежда
    "footwear": ["tops", "bottoms", "outerwear"],
    "accessories": ["tops", "bottoms"]
}

CATEGORY_QUERIES = {
    "tops": ["футболка", "рубашка", "толстовка"],
    "bottoms": ["джинсы", "брюки"],
    "outerwear": ["куртка", "пальто", "ветровка"],
    "footwear": ["кроссовки", "ботинки", "туфли"],
    "accessories": ["шапка", "шарф"]
}

GENDER_PREFIX = {
    "male": "мужская",
    "female": "женская",
    "unisex": ""
}

# Создание приложения
app = Flask(__name__)
CORS(app)

def json_response(data, status=200):
    """Универсальный ответ с поддержкой кириллицы"""
    return Response(
        json.dumps(data, ensure_ascii=False, indent=2),
        status=status,
        mimetype='application/json; charset=utf-8'
    )

def _make_item(c):
    return {
        "nm_id": c.nm_id,
        "name": c.name,
        "brand": c.brand,
        "price_rub": c.price_rub,
        "feedbacks": c.feedbacks,
        "rating": c.rating,
        "link": c.link,
        "image_url": f"http://localhost:5000/api/image/{c.nm_id}",
    }

def _short_query(q: str, max_words: int = 4) -> str:
    parts = [p for p in (q or "").replace("\n", " ").split(" ") if p.strip()]
    return " ".join(parts[:max_words]).strip()

def _collect_cards(query: str, max_cards: int = 60):
    """
    Возвращает (anchor_card, other_cards) даже если исходный запрос узкий.
    Дозапрашивает WB по нескольким более широким запросам и дедуплицирует по nm_id.
    """
    primary = wb_search_cards(query=query, page=1, spp=30)
    if not primary:
        return None, []

    anchor = primary[0]
    seen = {anchor.nm_id}
    other = []

    for c in primary[1:]:
        if c.nm_id in seen:
            continue
        seen.add(c.nm_id)
        other.append(c)
        if len(other) >= max_cards:
            return anchor, other

    extra_queries = []
    sq = _short_query(query, max_words=4)
    if sq and sq.lower() != query.lower():
        extra_queries.append(sq)
    if anchor.brand:
        extra_queries.append(str(anchor.brand))

    # Базовые “расширители”, чтобы всегда хватало доп. товаров
    extra_queries.extend(["джинсы", "брюки", "кроссовки", "ботинки", "футболка", "рубашка"])

    for q in extra_queries:
        try:
            cards = wb_search_cards(query=q, page=1, spp=30)
        except Exception as e:
            print(f"⚠️ WB search failed for '{q}': {e}")
            continue

        for c in cards:
            if c.nm_id in seen:
                continue
            seen.add(c.nm_id)
            other.append(c)
            if len(other) >= max_cards:
                return anchor, other

    return anchor, other

def _norm(s: str) -> str:
    return (s or "").replace("\n", " ").strip().lower()

def infer_gender_from_text(text: str) -> str:
    """
    Возвращает: male/female/unisex по простым маркерам в тексте.
    """
    t = _norm(text)
    if "мужск" in t or "мужская" in t or "мужское" in t or "мужские" in t:
        return "male"
    if "женск" in t or "женская" in t or "женское" in t or "женские" in t:
        return "female"
    return "unisex"

def infer_season_from_text(text: str) -> str:
    """
    Возвращает: winter/summer/spring/autumn/all-season по маркерам в тексте.
    Если сезон не найден — all-season (multyseasonal).
    """
    t = _norm(text)

    # Явные диапазоны
    if "весна-лет" in t or "весна / лет" in t or "весна–лет" in t:
        return "summer"
    if "осень-зим" in t or "осень / зим" in t or "осень–зим" in t:
        return "winter"
    if "весна-осен" in t or "осень-весн" in t or "весна / осен" in t or "осень / весн" in t:
        return "all-season"

    # Демисезон обычно = межсезонье
    if "демисез" in t:
        return "all-season"

    # Круглогодичное/всесезон
    if "круглогод" in t or "всесезон" in t or "all-season" in t:
        return "all-season"

    # Сезонные маркеры
    if "зимн" in t or "пухов" in t or "утепл" in t or "на мех" in t or "мех" in t:
        return "winter"
    if "летн" in t or "лето" in t:
        return "summer"
    if "весенн" in t:
        return "spring"
    if "осенн" in t:
        return "autumn"

    return "all-season"

def guess_category_from_name(name: str) -> str:
    """
    Простая эвристика определения категории якорного товара по названию.
    Возвращает одну из: tops/bottoms/outerwear/footwear/accessories
    """
    t = _norm(name)
    keywords = {
        "bottoms": ["брюк", "джинс", "штаны", "леггин", "юбк", "шорт", "карго", "банан"],
        "tops": ["футболк", "рубашк", "свитшот", "худи", "толстовк", "лонгслив", "топ", "блуз", "свитер", "джемпер"],
        "outerwear": ["куртк", "пальт", "пухов", "плащ", "ветровк", "жилет", "бомбер", "парка", "шуб"],
        "footwear": ["кроссов", "ботин", "туфл", "сапог", "кед", "лофер", "слип", "сандал", "шлеп", "тапк"],
        "accessories": ["шапк", "шарф", "ремень", "перчат", "сумк", "рюкзак", "очк", "зонт"],
    }

    best_cat = "tops"
    best_score = 0
    for cat, words in keywords.items():
        score = sum(1 for w in words if w in t)
        if score > best_score:
            best_score = score
            best_cat = cat
    return best_cat

def build_queries_for_category(cat: str, gender: str) -> list[str]:
    base_terms = CATEGORY_QUERIES.get(cat, ["одежда"])
    prefix = GENDER_PREFIX.get(gender, "") or ""
    queries = []
    for term in base_terms:
        queries.append(f"{prefix} {term}".strip())
    # убираем дубли, сохраняем порядок
    return list(dict.fromkeys(queries))

def collect_candidates_for_category(
    cat: str,
    gender: str,
    season: str,
    age_group: str = "adult",
    limit: int = 12,
) -> list:
    """
    Собирает кандидатов для категории через несколько поисковых запросов WB.
    Возвращает список WbSearchCard.
    """
    out = []
    seen = set()

    # 1) сначала с гендерным префиксом (если он есть)
    queries = build_queries_for_category(cat, gender)
    # 2) затем fallback без префикса (unisex), если не хватает
    if gender != "unisex":
        queries.extend(build_queries_for_category(cat, "unisex"))
        queries = list(dict.fromkeys(queries))

    for q in queries:
        if len(out) >= limit:
            break
        try:
            cards = wb_search_cards(query=q, page=1, spp=30)
        except Exception as e:
            print(f"⚠️ WB search failed for '{q}': {e}")
            continue

        for c in cards:
            if len(out) >= limit:
                break
            if c.nm_id in seen:
                continue
            seen.add(c.nm_id)
            if not is_candidate_relevant(c.name, gender, age_group, season):
                continue
            out.append(c)

    return out

# Эндпоинт: изображение товара
@app.route("/api/image/<int:nm_id>")
def get_image(nm_id):
    try:
        img_bytes = get_image_bytes(nm_id)
        if not img_bytes:
            return json_response({"error": "Изображение не найдено"}, 404)
        return send_file(
            io.BytesIO(img_bytes),
            mimetype="image/webp",
            as_attachment=False,
            download_name=f"{nm_id}.webp"
        )
    except Exception as e:
        print(f"❌ Ошибка при загрузке изображения {nm_id}: {e}")
        return json_response({"error": "Не удалось загрузить изображение"}, 500)

# Эндпоинт: создание капсулы
@app.route("/api/capsule", methods=["POST"])
def create_capsule():
    data = request.get_json()
    if not data or "query" not in data:
        return json_response({"error": "Требуется поле 'query'"}, 400)

    query = data["query"].strip()
    if not query:
        return json_response({"error": "Запрос не может быть пустым"}, 400)

    try:
        # Категорийная версия (без LLM):
        # - определяем категорию якоря по названию
        # - подбираем комплементарные категории (верх/низ/обувь/верхняя одежда)
        # - для каждой категории делаем отдельный поиск WB
        # - собираем 3 капсулы: якорь + по одному товару на категорию

        expected = parse_user_query(query)
        expected_gender = expected.get("expected_gender", "unisex")

        anchor_cards = wb_search_cards(query=query, page=1, spp=12)
        if not anchor_cards:
            return json_response({"error": "По вашему запросу ничего не найдено на WB"}, 404)

        anchor_card = anchor_cards[0]
        anchor_category = guess_category_from_name(anchor_card.name or query)
        # Если в исходном запросе пол не распознан, пытаемся взять его из названия якорного товара
        gender = expected_gender if expected_gender != "unisex" else infer_gender_from_text(anchor_card.name or query)
        # Сезон берём по якорному товару. Если не указан — all-season (multyseasonal).
        season = infer_season_from_text(anchor_card.name or query)

        needed_categories = COMPLEMENT.get(anchor_category)
        if not needed_categories:
            # дефолтный образ (3 дополнения): верх + низ + обувь/верхняя одежда (в зависимости от якоря)
            needed_categories = ["tops", "bottoms", "footwear", "outerwear"]

        # В рекомендациях не должно быть той же категории, что и якорь
        needed_categories = [c for c in needed_categories if c != anchor_category]
        # Нам нужно ровно 3 доп. элемента в капсуле
        needed_categories = needed_categories[:3]

        candidates_by_cat = {}
        for cat in needed_categories:
            candidates_by_cat[cat] = collect_candidates_for_category(
                cat=cat,
                gender=gender,
                season=season,
                age_group="adult",
                limit=12,
            )

        capsules = []
        for i in range(3):
            outfit = [anchor_card]
            used_in_capsule = {anchor_card.nm_id}

            for cat in needed_categories:
                pool = candidates_by_cat.get(cat) or []
                if not pool:
                    continue

                picked = None
                for shift in range(len(pool)):
                    cand = pool[(i + shift) % len(pool)]
                    if cand.nm_id in used_in_capsule:
                        continue
                    picked = cand
                    break

                if picked:
                    used_in_capsule.add(picked.nm_id)
                    outfit.append(picked)

            # Фолбэк: если вдруг не хватило категорийных кандидатов,
            # добиваем из других категорий (но НЕ из категории якоря)
            if len(outfit) < 4:
                fallback_cats = ["tops", "bottoms", "outerwear", "footwear"]
                for fc in fallback_cats:
                    if len(outfit) >= 4:
                        break
                    if fc == anchor_category:
                        continue
                    pool = candidates_by_cat.get(fc)
                    if not pool:
                        pool = collect_candidates_for_category(
                            cat=fc,
                            gender=gender,
                            season=season,
                            age_group="adult",
                            limit=6,
                        )
                        candidates_by_cat[fc] = pool
                    for cand in pool:
                        if len(outfit) >= 4:
                            break
                        if cand.nm_id in used_in_capsule:
                            continue
                        used_in_capsule.add(cand.nm_id)
                        outfit.append(cand)

            capsules.append(
                {
                    "outfit": [_make_item(c) for c in outfit],
                    "anchor_style": "other",
                }
            )

        return json_response(capsules)

    except Exception as e:
        print(f"❌ Ошибка в create_capsule: {e}")
        return json_response({"error": str(e)}, 500)


def is_candidate_relevant(name: str, anchor_gender: str, anchor_age: str, anchor_season: str) -> bool:
    name_low = name.lower()
    
    if anchor_gender == "male" and ("женская" in name_low or "для девочек" in name_low):
        return False
    if anchor_gender == "female" and ("мужская" in name_low or "для мальчиков" in name_low):
        return False
    
    child_keywords = ["детский", "детская", "для детей", "мальчик", "девочка", "подросток", "рост ", "лет "]
    is_child_in_name = any(kw in name_low for kw in child_keywords)
    if anchor_age == "adult" and is_child_in_name:
        return False

    # СЕЗОННОСТЬ (строже, чем было):
    # - зимой отсекаем явное лето/весна-лето
    # - летом отсекаем явную зиму/утепление
    # - в межсезонье (spring/autumn) отсекаем явное лето и явную зиму
    if anchor_season and anchor_season != "all-season":
        has_winter = ("зимн" in name_low) or ("утепл" in name_low) or ("пухов" in name_low) or ("мех" in name_low) or ("осень-зим" in name_low) or ("осень–зим" in name_low)
        has_summer = ("летн" in name_low) or ("лето" in name_low) or ("весна-лет" in name_low) or ("весна–лет" in name_low)
        has_all = ("демисез" in name_low) or ("круглогод" in name_low) or ("всесезон" in name_low) or ("весна-осен" in name_low) or ("осень-весн" in name_low)

        if anchor_season == "winter":
            # если товар явно летний и не всесезонный — не берём
            if has_summer and not (has_winter or has_all):
                return False
        elif anchor_season == "summer":
            if has_winter and not (has_summer or has_all):
                return False
        elif anchor_season in ("spring", "autumn"):
            if (has_winter or has_summer) and not has_all:
                return False
        
    return True


def parse_user_query(query: str) -> dict:
    query_lower = query.lower()
    
    expected_gender = "unisex"
    if "мужск" in query_lower or "мужская" in query_lower or "мужское" in query_lower:
        expected_gender = "male"
    elif "женск" in query_lower or "женская" in query_lower or "женское" in query_lower:
        expected_gender = "female"

    expected_season = "all-season"
    if "зимн" in query_lower:
        expected_season = "winter"
    elif "летн" in query_lower:
        expected_season = "summer"
    elif "весенн" in query_lower or "весенние" in query_lower:
        expected_season = "spring"
    elif "осенн" in query_lower or "осенние" in query_lower:
        expected_season = "autumn"

    return {
        "expected_gender": expected_gender,
        "expected_season": expected_season,
    }

# Главная страница
@app.route("/")
def hello():
    return json_response({"message": "Сервер Wardrobe запущен. Используйте POST /api/capsule"})

# Запуск
if __name__ == "__main__":
    app.run(debug=True, port=5000)

