# Wardrobe — Техническая документация

Документ описывает текущее состояние проекта: архитектуру, API, модули и алгоритмы.

---

## 1. Обзор архитектуры

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ Chrome Extension│────▶│ Flask Backend     │────▶│ Wildberries API │
│ (content.js)    │     │ (app.py)          │     │ Search + Images │
└─────────────────┘     └────────┬──────────┘     └─────────────────┘
                                 │
                                 │ опционально
                                 ▼
                        ┌──────────────────┐
                        │ ML (llm_enrich)  │
                        │ GLM-4.5-Air       │
                        └──────────────────┘
```

- **Расширение**: внедряет кнопку на странице товара WB, собирает данные товара и hints (пол, возраст, сезон), отправляет `POST /api/capsule`, отображает капсулы в боковой панели.
- **Backend**: определяет признаки якоря (категория, пол, стиль, сезон), запрашивает WB по комплементарным категориям, фильтрует кандидатов, формирует 3 капсулы.
- **ML**: по запросу обогащает товар атрибутами через LLM (кэш по `nm_id`).

---

## 2. Backend (Flask)

### 2.1 Зависимости

- `Flask`, `flask-cors`, `requests`, `Pillow`
- Опционально: модуль `ML.llm_enrich` (требует `openai`, `python-dotenv` и `.env` с `JWT_TOKEN`)

Запуск из папки `Backend`: `python app.py` (порт 5000, debug).

### 2.2 Эндпоинты

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/` | Проверка: `{"message": "Сервер Wardrobe запущен..."}` |
| GET | `/api/image/<nm_id>` | Изображение товара (webp), прокси с WB basket |
| POST | `/api/capsule` | Построение 3 капсул по якорному товару |

### 2.3 POST /api/capsule

**Тело запроса (JSON):**

| Поле | Тип | Обязательное | Описание |
|------|-----|--------------|----------|
| query | string | да | Поисковый запрос / название товара |
| product_name | string | нет | Уточнённое название (иначе используется query) |
| nm_id | int | нет | ID товара на WB (для точного якоря и LLM) |
| gender | string | нет | Подсказка: male / female / unisex |
| age_group | string | нет | Подсказка: adult / child |
| season | string | нет | Подсказка: winter / summer / spring / autumn / all-season |
| style | string | нет | Подсказка: casual / sport / office / streetwear / elegant / other |

**Ответ (200):** массив из 3 элементов — капсулы.

```json
[
  {
    "outfit": [
      {
        "nm_id": 123,
        "name": "...",
        "brand": "...",
        "price_rub": 5990,
        "feedbacks": 100,
        "rating": 4.8,
        "link": "https://www.wildberries.ru/catalog/123/detail.aspx",
        "image_url": "http://localhost:5000/api/image/123"
      }
    ],
    "anchor_style": "casual"
  }
]
```

В каждой капсуле: первый элемент `outfit` — якорный товар, остальные — рекомендации. Ошибки: 400 (нет query), 404 (ничего не найдено по запросу), 500 (внутренняя ошибка).

### 2.4 Логика формирования капсул (кратко)

1. **Якорь**: поиск по `query`/названию; при наличии `nm_id` выбирается карточка с этим ID.
2. **Признаки якоря** (`get_anchor_features`):
   - Приоритет: hints из запроса → LLM (если доступен) → эвристики по названию.
   - Поля: category, style, season, color, gender, age_group.
3. **Категории для рекомендаций** (`COMPLEMENT`):
   - tops ↔ bottoms, outerwear, footwear
   - bottoms ↔ tops, outerwear, footwear
   - outerwear ↔ tops, bottoms, footwear
   - footwear ↔ tops, bottoms, outerwear
   - dress → только outerwear, footwear
4. **Сбор кандидатов**: для каждой нужной категории строятся запросы с учётом пола, сезона и стиля (`build_queries_for_category`, `collect_candidates_for_category`), затем фильтрация `is_candidate_relevant`.
5. **Три капсулы**: для каждой капсулы из пулов категорий по одному товару выбирается со сдвигом (разнообразие), с повторной проверкой пола и стиля для office/elegant.
6. **Fallback**: если рекомендаций не хватает, дозапрос по другим категориям (для платья — только outerwear/footwear).

### 2.5 Модули Backend

- **wb_client.py**: функция `wb_search_cards(query, page, spp, ...)` → список `WbSearchCard` (nm_id, name, brand, price_rub, link и т.д.). Использует `https://search.wb.ru/exactmatch/ru/common/v18/search`.
- **wb_image_loader.py**: `get_image_bytes(nm_id)` → bytes. Хосты берутся из `basketstate.wbbasket.ru`, путь вида `.../vol.../part.../images/c246x328/1.webp`.

---

## 3. ML (llm_enrich)

- **Файл**: `ML/llm_enrich.py`.
- **Функция**: `enrich_product_name(nm_id: int, product_name: str) -> dict | None`.
- **Конфигурация**: переменная окружения `JWT_TOKEN` загружается из файла `.env` в **корне проекта** (`Warderobe/.env`).
- **API**: OpenAI-совместимый, `base_url="https://corellm.wb.ru/glm-45-air/v1"`, модель `glm-4.5-air`.
- **Выход**: словарь с полями `category`, `style`, `season`, `color`, `gender`, `age_group`. Значения категории: tops, bottoms, footwear, outerwear, accessories; стиля: casual, sport, office, streetwear, elegant, other.
- **Кэш**: по `nm_id` в `ML/llm_cache.json`; при отсутствии или ошибке LLM бэкенд использует эвристики.

Backend импортирует `enrich_product_name` только при успешной загрузке модуля; при исключении или отсутствии токена работает без LLM.

---

## 4. Chrome-расширение (wb_extention)

- **Manifest**: V3, разрешения `activeTab`, `storage`, `host_permissions` для `https://www.wildberries.ru/*` и `http://localhost:5000/*`.
- **Content script**: внедряется на `https://*.wildberries.ru/catalog/*/detail.aspx*`.

**content.js:**

- Определяет товар: название (h1 / data-testid="product-name" / .product-page__header-title) и `nm_id` из пути.
- Эвристика «одежда»: хлебные крошки, JSON-LD BreadcrumbList, ключевые слова в заголовке.
- Кнопка «Подобрать образ» рядом с блоком названия или плавающая.
- Подсказки `getWbHints()`: пол (женщинам/мужчинам/детям + характеристика «Пол»), возраст (детям → child), сезон (характеристика «Сезон»).
- Запрос к `http://localhost:5000/api/capsule` с полями `query`, `nm_id`, `product_name`, `...hints`.
- Отрисовка капсул в боковой панели (правая сторона, на мобильных — нижний лист): карточки с изображением, названием, ценой, ссылкой на WB.
- Сообщения расширения: `getProduct`, `openWardrobePanel` для popup.

**popup.html / popup.js:** проверка, что открыта страница товара WB; кнопка «Подобрать образ» (текущая реализация popup при нажатии открывает главную страницу бэкенда; основной сценарий — кнопка на странице товара).

---

## 5. Frontend (демо)

- Статическая страница `Frontend/index.html`: поле ввода запроса, кнопка «Подобрать образ».
- Вызов `POST http://localhost:5000/api/capsule` с телом `{ "query": "..." }` (без nm_id и hints).
- Отрисовка капсул: заголовок образа, сумма, карточки товаров, кнопки «Нравится», «В корзину», «Поделиться» (Telegram).

Изображения запрашиваются с `http://localhost:5000/api/image/<nm_id>`; backend должен быть запущен.

---

## 6. Конфигурация и окружение

- **.env** (в корне): `JWT_TOKEN=...` — для ML. В репозитории не коммитится (.gitignore).
- **.gitignore**: .env, ML/.env, __pycache__, ML/llm_cache.json, llm_cache.json, IDE/OS/временные файлы.

---

## 7. Алгоритмы и правила (справка)

- **Категория якоря**: по ключевым словам в названии (платье, брюки, футболка, куртка, обувь, аксессуары и т.д.) — `guess_category_from_name`.
- **Пол**: явные маркеры («мужск», «женск») и косвенные (тактика/камуфляж → male; платье, юбка, каблук → female). Для рекомендаций при male/female в названии кандидата требуются соответствующие маркеры.
- **Сезон**: по словам «зимн», «летн», «демисез», «всесезон» и т.д. — `infer_season_from_text`.
- **Стиль**: sport/office/elegant/streetwear/casual/other — по ключевым словам; для office/elegant отсекаются спортивные, тактические, камуфляжные, охотничьи позиции.
- **Платье**: нужные категории — только outerwear и footwear; в капсуле якорь + 2 рекомендации (target_size=3).
- **Дети**: при age_group=child в запросы добавляются префиксы «детская», «для детей» и т.д.; в фильтрации проверяются маркеры детского возраста.

---

## 8. Текущее состояние (кратко)

- Backend: один основной файл `app.py`, два резервных; CORS включён; опциональный LLM; полная фильтрация по полу/сезону/стилю/категории.
- Расширение: кнопка на странице товара, панель с капсулами, передача hints; popup — вспомогательный.
- ML: GLM-4.5-Air, кэш, токен из корневого `.env`.
- Frontend: демо без расширения, запрос только по тексту.
- Тест `Backend/test_api.py`: ожидает старый формат ответа; для актуального API нужно брать `data[0]["outfit"]` и т.д.

Документация актуальна по состоянию проекта на момент написания.
