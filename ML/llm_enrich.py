import os
import json
from openai import OpenAI
from dotenv import load_dotenv

# === Путь к кэшу ===
CACHE_PATH = os.path.join(os.path.dirname(__file__), "llm_cache.json")

# === Загрузка кэша ===
if os.path.exists(CACHE_PATH):
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            LLM_CACHE = json.load(f)
        print(f"✅ Загружено {len(LLM_CACHE)} записей из кэша: {CACHE_PATH}")
    except Exception as e:
        print(f"⚠️ Ошибка при загрузке кэша: {e}")
        LLM_CACHE = {}
else:
    LLM_CACHE = {}
    print("ℹ️ Кэш не найден — будет создан при первом обогащении.")

def save_cache():
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(LLM_CACHE, f, ensure_ascii=False, indent=2)
        print(f"💾 Кэш сохранён ({len(LLM_CACHE)} записей)")
    except Exception as e:
        print(f"❌ Ошибка при сохранении кэша: {e}")

# === Загрузка токена ===
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
dotenv_path = os.path.join(project_root, '.env')
load_dotenv(dotenv_path, encoding='utf-8-sig')

JWT_TOKEN = os.getenv("JWT_TOKEN")
if not JWT_TOKEN:
    raise EnvironmentError("JWT_TOKEN не найден в .env")

# === Клиент LLM (GLM-4.5-Air) ===
client = OpenAI(
    api_key=JWT_TOKEN,
    base_url="https://corellm.wb.ru/glm-45-air/v1"
)

# === ПРАВИЛЬНЫЙ промт: анализ ОДНОГО товара ===
ATTR_PROMPT_TEMPLATE = """Ты — эксперт по моде. Проанализируй название товара и верни ТОЛЬКО один JSON-объект с полями: "category", "style", "season", "color", "gender".

ПРАВИЛА ОПРЕДЕЛЕНИЯ ПОЛА:
- Явные маркеры: "мужск", "мужская", "женск", "женская" → используй их напрямую.
- КОСВЕННЫЕ ПРИЗНАКИ МУЖСКОГО ПОЛА:
  * Тактические товары: "тактическ", "милитар", "армейск", "камуфляж" → "male"
  * Мужские стили: "классическ" (для классических брюк/костюмов), "слаксы", "чиносы" (часто мужские)
  * Мужские категории: "галстук", "жилет классический", "брюки классические"
- КОСВЕННЫЕ ПРИЗНАКИ ЖЕНСКОГО ПОЛА:
  * Женские стили: "кимоно", "платье", "юбка", "блузка", "туфли на каблуке", "балетки"
  * Декоративные элементы: "с рюшами", "с бантами", "ажурн"
- Если явных маркеров нет, но есть косвенные признаки → используй их.
- Только если НИ явных, НИ косвенных признаков нет → "unisex".

ПРАВИЛА ВОЗРАСТА:
- Обрати внимание на слова: "для детей", "детский", "ребёнок", "мальчик", "девочка", "подросток", "рост 98–152", "1–7 лет" и т.п. → тогда "age_group": "child".
Если возраст не указан или товар для взрослых — "age_group": "adult".

ФОРМАТ:
- Никаких списков, массивов, пояснений, комментариев, слов "Ответ:", "```", markdown.
- Только чистый JSON: {{...}}
- category: "tops", "bottoms", "footwear", "outerwear", "accessories"
- style: "casual", "sport", "office", "streetwear", "elegant", "other"
- season: "spring", "summer", "autumn", "winter", "all-season"
- color: цвет на русском, или "неизвестно"
- gender: "male", "female", "unisex"
- age_group: "adult" или "child"

Пример:
{{"category": "bottoms", "style": "casual", "season": "spring", "color": "синий", "gender": "male", "age_group": "adult"}}

Название товара: «{product_name}»
"""


def parse_llm_response(text: str) -> dict | None:
    """Парсит ответ LLM как ОДИН JSON-объект."""
    try:
        # Найти первый объект {...}
        start = text.find('{')
        end = text.find('}', start) + 1
        if start == -1 or end == 0:
            # Попробуем найти самый длинный блок
            start = text.find('{')
            end = text.rfind('}') + 1
            if start == -1 or end <= start:
                print(f"[PARSE] Не найдены фигурные скобки. Текст: {repr(text)}")
                return None
        json_str = text[start:end]
        data = json.loads(json_str)

        # Проверка обязательных полей
        required = {"category", "style", "season", "color", "gender", "age_group"}
        if not required.issubset(data.keys()):
            missing = required - set(data.keys())
            print(f"[PARSE] Не хватает полей: {missing}. Получено: {data}")
            return None

        # Валидация значений (опционально, но полезно)
        if data["gender"] not in ("male", "female", "unisex"):
            data["gender"] = "unisex"

        return data

    except json.JSONDecodeError as e:
        print(f"[PARSE JSON ERROR] {e} | Текст: {repr(text)}")
        return None
    except Exception as e:
        print(f"[PARSE UNKNOWN ERROR] {e} | Текст: {repr(text)}")
        return None


def enrich_product_name(nm_id: int, product_name: str) -> dict | None:
    nm_id_str = str(nm_id)

    # Кэш
    if nm_id_str in LLM_CACHE:
        return LLM_CACHE[nm_id_str]["features"]

    # Защита от 429
    if getattr(enrich_product_name, "rate_limited", False):
        print("🛑 LLM временно недоступен (429). Пропускаем.")
        return None

    try:
        prompt = ATTR_PROMPT_TEMPLATE.format(product_name=product_name.strip())
        response = client.chat.completions.create(
            messages=[
                {"role": "user", "content": prompt}
            ],
            model="glm-4.5-air",
            temperature=0.0,
            max_tokens=200,
            stream=False
        )
        llm_output = response.choices[0].message.content
        print(f"[LLM RAW] {repr(llm_output)}")  # ← ВРЕМЕННО для отладки

        result = parse_llm_response(llm_output)

        if result:
            LLM_CACHE[nm_id_str] = {"name": product_name, "features": result}
            save_cache()
            return result
        else:
            print(f"[LLM PARSE FAILED] Не удалось распарсить ответ для: {product_name}")
            return None

    except Exception as e:
        error_str = str(e)
        if "429" in error_str:
            print("🛑 Достигнут лимит запросов к LLM. Блокировка на сессию.")
            enrich_product_name.rate_limited = True
            return None
        else:
            print(f"[LLM CALL ERROR] {e}")
            return None