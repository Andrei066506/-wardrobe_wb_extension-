import json
from io import BytesIO

import requests
from PIL import Image  # pip install pillow

# --- Исправленный код от коллег ---

def fetch_image_hosts_sync() -> list[dict]:
    """Синхронно загружает актуальный список хостов через API."""
    url = "https://basketstate.wbbasket.ru/v1/list/short?mediabasket"
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        hosts = []
        for host_name, host_info in r.json()['projects']['mediabasket']['hosts'].items():
            host_vol = host_name.split('-')[1].split('.')[0]
            hosts.append({
                'min': host_info['min_vol'],
                'max': host_info['max_vol'],
                'host_vol': host_vol
            })
        hosts.sort(key=lambda x: x['min'])
        return hosts
    except Exception as e:
        print(f"❌ Failed to load image hosts: {e}")
        return []

class ImageDAO:
    """
    DAO для работы с изображениями из карточек товара.
    """

    def __init__(self, image_hosts: list[dict]):
        self.__image_hosts = image_hosts

    def get_first_image(self, nm_id: int, images_size: str = "c246x328", image_format: str = "webp") -> bytes:
        """Возвращает первое изображение для заданного nm_id."""
        result = self.__load_and_save_image([nm_id, 1, images_size, image_format])
        return result.get("image", b"")

    def __load_and_save_image(self, to_download_images: list) -> dict[str, any]:
        """
        Принимает [nm_id, image_num, image_size, image_format],
        формирует ссылку и загружает картинку синхронно через requests.
        """
        nm_id, image_num, image_size, image_format = to_download_images
        image_url = self.__get_image_hostname(nm_id) + (
            f"/vol{nm_id // 100000}/"
            f"part{nm_id // 1000}/{nm_id}"
            f"/images/{image_size}/{image_num}.{image_format}"
        )
        try:
            response = requests.get(image_url, timeout=0.7)
        except Exception as e:
            print(f"❌ HTTP error for {image_url}: {e}")
            return {}
        if response.status_code != 200:
            print(f"❌ Status code {response.status_code} for {image_url}")
            return {}
        return {"NmId": nm_id, "PicsNum": image_num, "image": response.content}

    def __get_image_hostname(self, nm_id: int) -> str:
        """Возвращает имя хоста на основе НМ карточки товара."""
        vol = nm_id // 100000
        if not self.__image_hosts:
            return ''
        left, right = 0, len(self.__image_hosts) - 1
        while left <= right:
            mid = (left + right) // 2
            host = self.__image_hosts[mid]
            if host['min'] <= vol <= host['max']:
                return f"http://basket-{host['host_vol']}.wbbasket.ru"
            elif vol < host['min']:
                right = mid - 1
            else:
                left = mid + 1
        return ''

# --- Инициализация ---
hosts = fetch_image_hosts_sync()
image_dao = ImageDAO(hosts)

# --- Функция для удобства ---
def get_image_bytes(nm_id: int) -> bytes:
    """Получает байты изображения по nm_id."""
    return image_dao.get_first_image(nm_id)