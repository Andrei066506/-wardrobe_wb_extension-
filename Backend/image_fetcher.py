import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

IMAGE_CACHE_DIR = "images"
os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)

def get_image_path(nm_id: int) -> str:
    return os.path.join(IMAGE_CACHE_DIR, f"{nm_id}.jpg")

def download_image_with_selenium(nm_id: int) -> bool:
    img_path = get_image_path(nm_id)
    if os.path.exists(img_path):
        print(f"🖼️ Картинка уже в кэше: {nm_id}")
        return True

    product_url = f"https://www.wildberries.ru/catalog/{nm_id}/detail.aspx"
    debug_screenshot = os.path.join(IMAGE_CACHE_DIR, f"debug_{nm_id}.png")

    chrome_options = Options()
    # Используем новый headless режим (более стабильный)
    #chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.7499.110 Safari/537.36"
    )

    service = Service(ChromeDriverManager().install())
    driver = None

    try:
        driver = webdriver.Chrome(service=service, options=chrome_options)
        print(f"🌐 Открываем: {product_url}")
        driver.get(product_url)

        # Делаем скриншот для отладки
        driver.save_screenshot(debug_screenshot)
        print(f"📸 Скриншот сохранён: {debug_screenshot}")

        # Ждём до 30 секунд
        wait = WebDriverWait(driver, 30)
        img_element = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "img.photo-zoom__preview"))
        )

        img_url = img_element.get_attribute("src")
        if not img_url or "wbstatic.net" not in img_url:
            print(f"❌ Некорректный src: {img_url}")
            return False

        print(f"📥 Картинка найдена: {img_url}")

        import requests
        resp = requests.get(img_url, headers={"Referer": product_url}, timeout=15)
        if resp.status_code == 200:
            with open(img_path, "wb") as f:
                f.write(resp.content)
            print(f"✅ Успешно сохранено: {img_path}")
            # Удаляем debug-скриншот, если всё OK
            if os.path.exists(debug_screenshot):
                os.remove(debug_screenshot)
            return True
        else:
            print(f"❌ Ошибка HTTP {resp.status_code} при загрузке изображения")
            return False

    except Exception as e:
        print(f"💥 Ошибка при загрузке {nm_id}: {e}")
        if driver and os.path.exists(debug_screenshot):
            print(f"🔎 Посмотрите скриншот: {debug_screenshot}")
        return False
    finally:
        if driver:
            driver.quit()