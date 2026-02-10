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
    # Верх: расширяем ассортимент (не только футболки)
    "tops": [
        "футболка",
        "лонгслив",
        "рубашка",
        "поло",
        "свитшот",
        "худи",
        "толстовка",
        "свитер",
        "водолазка",
        "кардиган",
        "блузка",
        "топ",
    ],
    # Низ: расширяем ассортимент (не только джинсы)
    "bottoms": [
        "джинсы",
        "брюки",
        "чиносы",
        "карго",
        "шорты",
        "юбка",
        # спортивные низы (леггинсы/тайтсы) добавляем только для sport-образов (см. build_queries_for_category)
    ],
    # Верхняя одежда: расширяем
    "outerwear": [
        "куртка",
        "пуховик",
        "пальто",
        "парка",
        "ветровка",
        "плащ",
        "тренч",
        "бомбер",
        "жилет",
    ],
    # Обувь: расширяем
    "footwear": [
        "кроссовки",
        "кеды",
        "ботинки",
        "челси",
        "туфли",
        "лоферы",
        "сапоги",
        "сандалии",
    ],
    "accessories": ["шапка", "шарф", "ремень", "сумка", "рюкзак"]
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
    Учитывает как явные маркеры, так и косвенные признаки пола.
    """
    t = _norm(text)
    
    # Явные маркеры пола
    if "мужск" in t or "мужская" in t or "мужское" in t or "мужские" in t or "для мужчин" in t:
        return "male"
    if "женск" in t or "женская" in t or "женское" in t or "женские" in t or "для женщин" in t:
        return "female"
    
    # Косвенные признаки мужского пола
    male_indicators = [
        "тактическ", "милитар", "армейск", "камуфляж", "военн",
        "слаксы", "чиносы", "классическ" + " брюк", "классическ" + " костюм",
        "галстук", "жилет классическ", "брюки классическ",
    ]
    if any(indicator in t for indicator in male_indicators):
        return "male"
    
    # Косвенные признаки женского пола
    female_indicators = [
        "кимоно", "платье", "юбка", "блузка", "балетки",
        "на каблуке", "каблук", "туфли на", "туфли с каблуком",
        "с рюшами", "с бантами", "ажурн", "декор",
    ]
    if any(indicator in t for indicator in female_indicators):
        return "female"
    
    return "unisex"

def infer_age_group_from_text(text: str) -> str:
    """
    Возвращает: adult/child по простым маркерам в тексте.
    Если не распознано — adult.
    """
    t = _norm(text)
    child_markers = [
        "детск", "для детей", "ребен", "ребён", "мальчик", "девочк", "подрост",
        "малыш", "ясел", "детсад", "садик", "в сад", "в школу", "школьн",
        "kids", "kid", "junior", "teen",
        "рост ", "лет ",
    ]
    if any(m in t for m in child_markers):
        return "child"
    return "adult"

def infer_style_from_text(text: str) -> str:
    """
    Возвращает: casual/sport/office/streetwear/elegant/other
    """
    t = _norm(text)

    sport = ["спорт", "спортивн", "трениров", "фитнес", "fitness", "running", "бег", "зал"]
    office = ["офис", "делов", "классич", "строг", "формал", "official"]
    elegant = ["вечерн", "элегант", "коктейль", "празднич", "нарядн"]
    street = ["street", "стрит", "oversize", "оверсайз", "urban", "гранж"]
    casual = ["повседнев", "casual", "на каждый день", "базов"]

    if any(k in t for k in sport):
        return "sport"
    if any(k in t for k in office):
        return "office"
    if any(k in t for k in elegant):
        return "elegant"
    if any(k in t for k in street):
        return "streetwear"
    if any(k in t for k in casual):
        return "casual"
    return "other"

def _normalize_hint_gender(v):
    return v if v in ("male", "female", "unisex") else None

def _normalize_hint_age(v):
    return v if v in ("adult", "child") else None

def _normalize_hint_season(v):
    return v if v in ("winter", "summer", "spring", "autumn", "all-season") else None

def _normalize_hint_style(v):
    return v if v in ("casual", "sport", "office", "streetwear", "elegant", "other") else None

def get_anchor_features(product_name: str, nm_id: int | None, hints: dict) -> dict:
    """
    Определяет признаки якорного товара с приоритетами:
    1) Подсказки из расширения (hints) - высший приоритет (переопределяют всё)
    2) LLM анализ (если доступен) - средний приоритет
    3) Эвристика по названию - низкий приоритет (fallback)
    
    Для пола: если hints не определили пол, используется LLM результат.
    Если и LLM не определил (или недоступен), используется эвристика по названию.
    """
    features = None

    if enrich_product_name is not None and nm_id is not None:
        try:
            features = enrich_product_name(int(nm_id), product_name)
        except Exception as e:
            print(f"⚠️ LLM enrich failed: {e}")
            features = None

    if not isinstance(features, dict):
        features = {
            "category": guess_category_from_name(product_name),
            "style": infer_style_from_text(product_name),
            "season": infer_season_from_text(product_name),
            "color": "неизвестно",
            "gender": infer_gender_from_text(product_name),
            "age_group": infer_age_group_from_text(product_name),
        }

    # Apply hints (highest priority, но только если они реально определили пол, не unisex)
    hg = _normalize_hint_gender(hints.get("gender"))
    ha = _normalize_hint_age(hints.get("age_group"))
    hs = _normalize_hint_season(hints.get("season"))
    hst = _normalize_hint_style(hints.get("style"))

    # Применяем hints только если они реально определили значение (не unisex для пола)
    if hg and hg != "unisex":
        features["gender"] = hg
    if ha:
        features["age_group"] = ha
    if hs:
        features["season"] = hs
    if hst:
        features["style"] = hst

    # Если hints не определили пол (или вернули unisex), и LLM вернул unisex, пробуем улучшить через эвристику
    current_gender = features.get("gender", "unisex")
    if current_gender == "unisex":
        heuristic_gender = infer_gender_from_text(product_name)
        if heuristic_gender != "unisex":
            features["gender"] = heuristic_gender
            print(f"💡 [GENDER FIX] LLM/hints вернули unisex, эвристика определила: {heuristic_gender} для '{product_name}'")

    # Basic normalization defaults
    if features.get("season") is None:
        features["season"] = "all-season"
    if features.get("gender") is None:
        features["gender"] = "unisex"
    if features.get("age_group") is None:
        features["age_group"] = "adult"
    if features.get("style") is None:
        features["style"] = "other"

    return features

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
    Возвращает одну из: tops/bottoms/outerwear/footwear/accessories/dress
    """
    t = _norm(name)
    
    # Платье — особая категория (занимает и верх, и низ)
    if "плать" in t or "dress" in t:
        return "dress"
    
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

def build_queries_for_category(cat: str, gender: str, season: str = "all-season", style: str = "other") -> list[str]:
    base_terms = list(CATEGORY_QUERIES.get(cat, ["одежда"]))

    # Тонкая настройка ассортимента по стилю/сезону:
    # - лосины/леггинсы/тайтсы только для sport-образов
    if cat == "bottoms":
        if style == "sport":
            base_terms.extend(["леггинсы", "лосины", "тайтсы"])
        # иначе — не добавляем их вообще

    # - сандалии/босоножки только для женского летнего casual
    if cat == "footwear":
        if not (gender == "female" and season == "summer" and style == "casual"):
            base_terms = [t for t in base_terms if t not in ("сандалии",)]

        # зимой усиливаем “тёплую” обувь
        if season == "winter":
            base_terms = ["ботинки", "сапоги", "челси", "кроссовки"] + [t for t in base_terms if t not in ("ботинки", "сапоги", "челси", "кроссовки")]

    # Чтобы не упираться в первый термин, перемешиваем порядок
    terms = list(dict.fromkeys(base_terms))
    random.shuffle(terms)

    # Префиксы для улучшения точности выдачи.
    prefixes = []
    if gender == "male":
        prefixes = ["мужская", "мужские", "для мужчин"]
    elif gender == "female":
        prefixes = ["женская", "женские", "для женщин"]
    else:
        prefixes = [""]

    # Возрастные префиксы подмешиваем в запросы через маркер (обрабатывается в collect_candidates_for_category)
    queries = []
    for term in terms:
        for p in prefixes:
            queries.append(f"{p} {term}".strip())

    return list(dict.fromkeys(queries))

def collect_candidates_for_category(
    cat: str,
    gender: str,
    season: str,
    age_group: str = "adult",
    style: str = "other",
    limit: int = 12,
) -> list:
    """
    Собирает кандидатов для категории через несколько поисковых запросов WB.
    Возвращает список WbSearchCard.
    """
    out = []
    seen = set()

    # ВАЖНО: если пол известен (male/female), не уходим в unisex-запросы,
    # иначе слишком часто прилетает “не тот” пол без явных маркеров в названии.
    queries = build_queries_for_category(cat, gender, season=season, style=style)

    # Возрастной префикс: для детских образов добавляем маркер в запрос,
    # для взрослых — специально НЕ добавляем (чтобы не “ломать” выдачу).
    if age_group == "child":
        child_prefixes = ["детская", "детский", "для детей", "подростковая"]
        expanded = []
        for q in queries:
            for cp in child_prefixes:
                expanded.append(f"{cp} {q}".strip())
        queries = list(dict.fromkeys(expanded))

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
            if not is_candidate_relevant(
                c.name,
                gender,
                age_group,
                season,
                style,
                candidate_category=cat,
            ):
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

    query = str(data["query"]).strip()
    if not query:
        return json_response({"error": "Запрос не может быть пустым"}, 400)

    try:
        # Категорийная версия (без LLM):
        # - определяем категорию якоря по названию
        # - подбираем комплементарные категории (верх/низ/обувь/верхняя одежда)
        # - для каждой категории делаем отдельный поиск WB
        # - собираем 3 капсулы: якорь + по одному товару на категорию

        # Product name + nm_id from extension
        product_name = str(data.get("product_name") or query).strip()
        nm_id = data.get("nm_id")
        try:
            nm_id = int(nm_id) if nm_id is not None else None
        except Exception:
            nm_id = None

        hints = {
            "gender": data.get("gender"),
            "age_group": data.get("age_group"),
            "season": data.get("season"),
            "style": data.get("style"),
        }

        anchor_cards = wb_search_cards(query=product_name, page=1, spp=30)
        if not anchor_cards:
            return json_response({"error": "По вашему запросу ничего не найдено на WB"}, 404)

        # Prefer exact nm_id match for anchor if possible
        anchor_card = None
        if nm_id is not None:
            for c in anchor_cards:
                if int(c.nm_id) == int(nm_id):
                    anchor_card = c
                    break
        if anchor_card is None:
            anchor_card = anchor_cards[0]

        # Anchor features (LLM-first, then fallback)
        anchor_features = get_anchor_features(product_name, nm_id, hints)

        anchor_category = anchor_features.get("category") or guess_category_from_name(anchor_card.name or product_name)
        gender = anchor_features.get("gender") or "unisex"
        age_group = anchor_features.get("age_group") or "adult"
        season = anchor_features.get("season") or "all-season"
        anchor_style = anchor_features.get("style") or "other"

        # Приоритет определения пола:
        # 1. Hints (уже применены в get_anchor_features) - высший приоритет
        # 2. LLM результат (уже в anchor_features) - средний приоритет
        # 3. Название якоря (только если hints и LLM не определили пол или определили как unisex)
        # Если hints определили пол, используем его. Если нет - используем LLM. Если и LLM не определил - проверяем название.
        anchor_name_low = (anchor_card.name or product_name).lower()
        
        # Логирование для отладки определения пола
        hints_gender = hints.get("gender")
        llm_gender = anchor_features.get("gender")
        print(f"🔍 [GENDER DEBUG] Якорь: {anchor_card.name}")
        print(f"   Hints gender: {hints_gender}")
        print(f"   LLM gender: {llm_gender}")
        print(f"   Текущий gender: {gender}")
        
        # Проверяем название только если gender еще unisex (не определен hints или LLM)
        # Используем улучшенную эвристику, которая учитывает косвенные признаки
        if gender == "unisex":
            heuristic_gender = infer_gender_from_text(anchor_card.name or product_name)
            if heuristic_gender != "unisex":
                gender = heuristic_gender
                print(f"   → Определено по названию (эвристика): {gender}")
        
        print(f"   ✅ Финальный gender для капсулы: {gender}")

        # СПЕЦИАЛЬНАЯ ОБРАБОТКА ДЛЯ ПЛАТЬЯ:
        # Платье занимает и верх, и низ, поэтому рекомендуем только верхнюю одежду и обувь
        is_dress = "плать" in anchor_name_low or anchor_category == "dress"
        if is_dress:
            needed_categories = ["outerwear", "footwear"]
        else:
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
                age_group=age_group,
                style=anchor_style,
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
                    # Дополнительная проверка пола: если якорь определённого пола, требуем явный маркер того же пола
                    cand_name_low = (cand.name or "").lower()
                    if gender == "male":
                        if any(m in cand_name_low for m in ["женск", "женская", "женской", "женское", "для женщин", "для девочек"]):
                            continue
                        # Юбка — исключительно женская категория
                        if cat == "bottoms" and ("юбк" in cand_name_low or "skirt" in cand_name_low):
                            continue
                        # Косвенные признаки женского пола
                        if cat == "bottoms":
                            if ("высок" in cand_name_low and "посадк" in cand_name_low) and ("скинни" in cand_name_low or "заужен" in cand_name_low):
                                continue
                        if cat == "footwear":
                            if "каблук" in cand_name_low or "каблуке" in cand_name_low or "heel" in cand_name_low:
                                continue
                        # Требуем явный маркер мужского пола
                        if not any(m in cand_name_low for m in ["мужск", "мужская", "мужские", "мужской", "мужское", "для мужчин"]):
                            continue
                    elif gender == "female":
                        if any(m in cand_name_low for m in ["мужск", "мужская", "мужской", "мужское", "для мужчин", "для мальчиков"]):
                            continue
                        # Требуем явный маркер женского пола
                        if not any(m in cand_name_low for m in ["женск", "женская", "женские", "женской", "женское", "для женщин", "для девочек"]):
                            continue
                    # СТРОГАЯ ФИЛЬТРАЦИЯ ПО СТИЛЮ для элегантных/офисных образов
                    if anchor_style in ("elegant", "office"):
                        # Брюки: отсекаем спортивные/охотничьи/камуфляж/тактические
                        if cat == "bottoms":
                            if any(kw in cand_name_low for kw in ["фитнес", "fitness", "для фитнеса", "трениров", "спорт", "спортив", "охот", "hunting", "для охоты", "камуфляж", "camouflage", "камуфл", "тактическ", "милитар", "армейск", "рабоч", "утилитарн", "спецодежд"]):
                                continue
                        # Верх: отсекаем спортивные/утилитарные
                        if cat == "tops":
                            if any(kw in cand_name_low for kw in ["фитнес", "fitness", "для фитнеса", "трениров", "спорт", "спортив", "рабоч", "утилитарн"]):
                                continue
                        # Верхняя одежда: отсекаем тактические/камуфляж/охотничьи
                        if cat == "outerwear":
                            if any(kw in cand_name_low for kw in ["тактическ", "милитар", "армейск", "камуфляж", "camouflage", "камуфл", "охот", "hunting", "для охоты", "рабоч", "утилитарн", "спецодежд"]):
                                continue
                        # Обувь: отсекаем утилитарную/спортивную
                        if cat == "footwear":
                            if any(kw in cand_name_low for kw in ["резин", "эва", "сапог резин", "резиновые", "утилитарн", "рабоч", "фитнес", "fitness", "для фитнеса", "трениров", "спорт", "спортив"]):
                                continue
                    picked = cand
                    break

                if picked:
                    used_in_capsule.add(picked.nm_id)
                    outfit.append(picked)

            # Фолбэк: если вдруг не хватило категорийных кандидатов,
            # добиваем из других категорий (но НЕ из категории якоря)
            # Для платья не добиваем — оно уже занимает верх и низ
            target_size = 3 if is_dress else 4  # 3 = якорь + 2 рекомендации для платья, 4 = якорь + 3 для остальных
            if len(outfit) < target_size:
                fallback_cats = ["tops", "bottoms", "outerwear", "footwear"]
                for fc in fallback_cats:
                    if len(outfit) >= target_size:
                        break
                    if fc == anchor_category:
                        continue
                    # Для платья добиваем только из outerwear и footwear
                    if is_dress and fc not in ["outerwear", "footwear"]:
                        continue
                    pool = candidates_by_cat.get(fc)
                    if not pool:
                        pool = collect_candidates_for_category(
                            cat=fc,
                            gender=gender,
                            season=season,
                            age_group=age_group,
                            style=anchor_style,
                            limit=6,
                        )
                        candidates_by_cat[fc] = pool
                    for cand in pool:
                        if len(outfit) >= target_size:
                            break
                        if cand.nm_id in used_in_capsule:
                            continue
                        # Дополнительная проверка пола в fallback
                        cand_name_low = (cand.name or "").lower()
                        if gender == "male":
                            if any(m in cand_name_low for m in ["женск", "женская", "женской", "женское", "для женщин", "для девочек"]):
                                continue
                            # Юбка — исключительно женская категория
                            if fc == "bottoms" and ("юбк" in cand_name_low or "skirt" in cand_name_low):
                                continue
                            # Косвенные признаки женского пола
                            if fc == "bottoms":
                                if ("высок" in cand_name_low and "посадк" in cand_name_low) and ("скинни" in cand_name_low or "заужен" in cand_name_low):
                                    continue
                            if fc == "footwear":
                                if "каблук" in cand_name_low or "каблуке" in cand_name_low or "heel" in cand_name_low:
                                    continue
                            # Требуем явный маркер мужского пола
                            if not any(m in cand_name_low for m in ["мужск", "мужская", "мужские", "мужской", "мужское", "для мужчин"]):
                                continue
                        elif gender == "female":
                            if any(m in cand_name_low for m in ["мужск", "мужская", "мужской", "мужское", "для мужчин", "для мальчиков"]):
                                continue
                            # Требуем явный маркер женского пола
                            if not any(m in cand_name_low for m in ["женск", "женская", "женские", "женской", "женское", "для женщин", "для девочек"]):
                                continue
                        # СТРОГАЯ ФИЛЬТРАЦИЯ ПО СТИЛЮ для элегантных/офисных образов (fallback)
                        if anchor_style in ("elegant", "office"):
                            # Брюки: отсекаем спортивные/охотничьи/камуфляж/тактические
                            if fc == "bottoms":
                                if any(kw in cand_name_low for kw in ["фитнес", "fitness", "для фитнеса", "трениров", "спорт", "спортив", "охот", "hunting", "для охоты", "камуфляж", "camouflage", "камуфл", "тактическ", "милитар", "армейск", "рабоч", "утилитарн", "спецодежд"]):
                                    continue
                            # Верх: отсекаем спортивные/утилитарные
                            if fc == "tops":
                                if any(kw in cand_name_low for kw in ["фитнес", "fitness", "для фитнеса", "трениров", "спорт", "спортив", "рабоч", "утилитарн"]):
                                    continue
                            # Верхняя одежда: отсекаем тактические/камуфляж/охотничьи
                            if fc == "outerwear":
                                if any(kw in cand_name_low for kw in ["тактическ", "милитар", "армейск", "камуфляж", "camouflage", "камуфл", "охот", "hunting", "для охоты", "рабоч", "утилитарн", "спецодежд"]):
                                    continue
                            # Обувь: отсекаем утилитарную/спортивную
                            if fc == "footwear":
                                if any(kw in cand_name_low for kw in ["резин", "эва", "сапог резин", "резиновые", "утилитарн", "рабоч", "фитнес", "fitness", "для фитнеса", "трениров", "спорт", "спортив"]):
                                    continue
                        used_in_capsule.add(cand.nm_id)
                        outfit.append(cand)

            capsules.append(
                {
                    "outfit": [_make_item(c) for c in outfit],
                    "anchor_style": anchor_style,
                }
            )

        return json_response(capsules)

    except Exception as e:
        print(f"❌ Ошибка в create_capsule: {e}")
        return json_response({"error": str(e)}, 500)


def is_candidate_relevant(
    name: str,
    anchor_gender: str,
    anchor_age: str,
    anchor_season: str,
    anchor_style: str = "other",
    candidate_category: str | None = None,
) -> bool:
    name_low = name.lower()
    
    # Пол: СТРОГИЙ фильтр — если якорь определённого пола, требуем явный маркер того же пола в названии кандидата.
    # Также используем косвенные признаки пола (характеристики товара).
    if anchor_gender == "male":
        # Мужской якорь: отсекаем всё, что явно женское
        if any(marker in name_low for marker in ["женск", "для женщин", "для девочек", "женская", "женские", "женской", "женское"]):
            return False
        # Категорийный фильтр: юбка — исключительно женская категория
        if candidate_category == "bottoms" and ("юбк" in name_low or "skirt" in name_low):
            return False
        # Косвенные признаки женского пола для мужского якоря (отсекаем):
        # - джинсы: "высокая посадка" + "скинни"/"заужен" = женские
        if candidate_category == "bottoms":
            if ("высок" in name_low and "посадк" in name_low) and ("скинни" in name_low or "заужен" in name_low):
                return False
        # - обувь: "на каблуке" = женские
        if candidate_category == "footwear":
            if "каблук" in name_low or "каблуке" in name_low or "heel" in name_low:
                return False
        # ТРЕБУЕМ явный маркер мужского пола в названии
        has_male_marker = any(marker in name_low for marker in ["мужск", "мужская", "мужские", "мужской", "мужское", "для мужчин"])
        if not has_male_marker:
            return False
    elif anchor_gender == "female":
        # Женский якорь: отсекаем всё, что явно мужское
        if any(marker in name_low for marker in ["мужск", "для мужчин", "для мальчиков", "мужская", "мужские", "мужской", "мужское"]):
            return False
        # ТРЕБУЕМ явный маркер женского пола в названии
        has_female_marker = any(marker in name_low for marker in ["женск", "женская", "женские", "женской", "женское", "для женщин", "для девочек"])
        if not has_female_marker:
            return False
    # Если anchor_gender == "unisex" — разрешаем всё (без требований к маркерам)
    
    # Возраст: якорь задаёт age_group (adult/child).
    child_keywords = [
        "детск", "для детей", "ребен", "ребён", "мальчик", "девочк", "подрост",
        "малыш", "ясел", "детсад", "садик", "в сад", "в школу", "школьн",
        "kids", "junior", "teen",
        "рост ", "лет ",
    ]
    is_child_in_name = any(kw in name_low for kw in child_keywords)
    if anchor_age == "adult" and is_child_in_name:
        return False
    if anchor_age == "child" and not is_child_in_name:
        # Для детских образов стараемся не брать взрослое.
        # (Если понадобится расширить — можно ослабить.)
        return False

    # Обувь: сандалии/босоножки допустимы только для женского летнего casual.
    # Во всех остальных случаях отсекаем.
    if candidate_category == "footwear":
        is_summer_shoes = any(
            kw in name_low
            for kw in [
                "сандал",
                "босонож",
                "шлеп",
                "шлёп",
                "сланц",
                "вьетнамк",
            ]
        )
        if is_summer_shoes:
            if not (anchor_gender == "female" and anchor_season == "summer" and anchor_style == "casual"):
                return False

    # Спортивные лосины/леггинсы — только для sport-образов.
    if candidate_category == "bottoms":
        is_leggings = ("лосин" in name_low) or ("леггин" in name_low) or ("тайт" in name_low) or ("tights" in name_low)
        is_sport_marked = ("спорт" in name_low) or ("спортив" in name_low) or ("трениров" in name_low)
        if (is_leggings or is_sport_marked) and anchor_style != "sport":
            return False
        
        # СТРОГАЯ ФИЛЬТРАЦИЯ ДЛЯ ЭЛЕГАНТНЫХ/ОФИСНЫХ ОБРАЗОВ:
        # Для элегантных и офисных образов отсекаем все неподходящие типы брюк
        if anchor_style in ("elegant", "office"):
            # Спортивные/фитнес брюки
            if any(kw in name_low for kw in ["фитнес", "fitness", "для фитнеса", "трениров", "спорт", "спортив"]):
                return False
            # Охотничьи/утилитарные брюки
            if any(kw in name_low for kw in ["охот", "hunting", "для охоты", "утилитарн", "рабоч", "спецодежд"]):
                return False
            # Камуфляж
            if "камуфляж" in name_low or "camouflage" in name_low or "камуфл" in name_low:
                return False
            # Военные/тактические брюки
            if any(kw in name_low for kw in ["тактическ", "милитар", "армейск", "военн"]):
                return False

    # Доп. защита для обуви: часто детская обувь не содержит "детск",
    # но содержит маленькие размеры. Если якорь adult и категория footwear,
    # отсекаем явные "размер 20-35" / "р. 20-35".
    if anchor_age == "adult" and candidate_category == "footwear":
        import re
        sizes = [int(x) for x in re.findall(r"(?:размер|р\.?)\s*(\d{2})", name_low)]
        if any(20 <= s <= 35 for s in sizes):
            return False

    # Зима + обувь: спортивные кроссовки/раннинг не рекомендуем к зимней верхней одежде
    # (исключение — если товар явно зимний/утеплённый).
    if candidate_category == "footwear" and anchor_season == "winter":
        sport_shoes = any(kw in name_low for kw in ["спортив", "running", "для бега", "трениров", "фитнес"])
        winter_markers = any(kw in name_low for kw in ["зимн", "утепл", "мех", "шерст", "термо"])
        if sport_shoes and not winter_markers:
            return False

    # СТРОГАЯ ФИЛЬТРАЦИЯ ПО СТИЛЮ для элегантных/офисных образов:
    if anchor_style in ("elegant", "office"):
        # Верх (tops): отсекаем спортивные/утилитарные товары
        if candidate_category == "tops":
            if any(kw in name_low for kw in ["фитнес", "fitness", "для фитнеса", "трениров", "спорт", "спортив", "рабоч", "утилитарн"]):
                return False
        
        # Верхняя одежда (outerwear): отсекаем спортивные/тактические/утилитарные товары
        if candidate_category == "outerwear":
            if any(kw in name_low for kw in ["тактическ", "милитар", "армейск", "камуфляж", "camouflage", "камуфл", "охот", "hunting", "для охоты", "рабоч", "утилитарн", "спецодежд"]):
                return False
        
        # Обувь: утилитарная/резиновая/спортивная обувь не подходит
        if candidate_category == "footwear":
            utilitarian_shoes = any(kw in name_low for kw in ["резин", "эва", "сапог резин", "резиновые", "утилитарн", "рабоч", "фитнес", "fitness", "для фитнеса", "трениров", "спорт", "спортив"])
            if utilitarian_shoes:
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