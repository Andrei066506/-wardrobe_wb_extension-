import requests

try:
    response = requests.post(
        "http://localhost:5000/api/capsule",
        json={"query": "джинсы"}
    )
    response.raise_for_status()  # вызовет исключение, если статус не 2xx
    data = response.json()
    
    print(f"✅ Получено {len(data)} карточек\n")
    for i, item in enumerate(data):
        role = "🔹 Основной" if i == 0 else f"🔸 Рекомендация {i}"
        print(f"{role}: {item['name']}")
        print(f"    Бренд: {item['brand'] or '—'}")
        print(f"    Цена: {item['price_rub']} ₽")
        print(f"    Ссылка: {item['link']}")
        print(f"    Картинка: {item['image_url']}\n")

except Exception as e:
    print("❌ Ошибка:", e)