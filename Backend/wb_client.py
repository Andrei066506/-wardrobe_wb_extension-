from __future__ import annotations

import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
import requests

WB_SEARCH_URL = "https://search.wb.ru/exactmatch/ru/common/v18/search"

@dataclass
class WbSearchCard:
    nm_id: int
    name: str
    brand: Optional[str]
    brand_id: Optional[int]
    supplier: Optional[str]
    supplier_id: Optional[int]
    rating: Optional[float]
    feedbacks: Optional[int]
    price_rub: Optional[float]
    price_basic_rub: Optional[float]
    pics: Optional[int]
    link: str

def _money_from_cents(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value) / 100.0
    except (TypeError, ValueError):
        return None

def wb_search_cards(
    query: str,
    page: int = 1,   # номер страницы
    spp: int = 15,   # глубина поиска, т.е. сколько предметов вернуть
    dest: int = -1257786,
    sort: str = "popular",
    lang: str = "ru",
    curr: str = "rub",
    app_type: int = 1,
    timeout: float = 20.0,
    max_retries: int = 3,
) -> List[WbSearchCard]:
    session = requests.Session()
    # добавляем заголовки, чтобы выглядело как запрос в броузера
    session.headers.update({
        "Authorization": "Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJpYXQiOjE3Njg3NTU1NTYsInVzZXIiOiIxNTg2MDM4ODkiLCJzaGFyZF9rZXkiOiIyMyIsImNsaWVudF9pZCI6IndiIiwic2Vzc2lvbl9pZCI6ImE5YWJkYWU1NjJhYzQ2Njk5ZTA0Y2RkOTI2M2U1MWFjIiwicGhvbmUiOiJJY3loT3NJQXMwTVU4Y1JaWjMycXZnPT0iLCJ2YWxpZGF0aW9uX2tleSI6IjU4NzA2M2FiZTg1NDJhMjlkOGQ2ZjcwZWMzMjFkYjg5MDEwNTQ1OWY0ZjViZmQ2MmI5MWRhNzcyNGIyOTNhYzQiLCJ1c2VyX3JlZ2lzdHJhdGlvbl9kdCI6MTcyMTkwMzI5NCwidmVyc2lvbiI6Mn0.fIynT-3J6cpXeVneGQlEmHALfW4MJ59C9e0LQEqwv18RpmUbMRwqtzg_3WDSjB9KI53xrn5zqbJKUGpi7wTIAV5DAknNYl0pRjrj4NvBDqHYOl_0VPi8bV7BkyabKw-40BJSVi3uI3J6zEkjpIWiNPBJbz6xZCBp8uiIxY-B__6BTHfenvRl1VL5MZvGjm2r3tEeXYPxWn68KLKqmiyzKH0ddYsyrsg10fOzuFLderhFZ04-BsubJN8cP1rC64N4jUlbgmuBiUlXpCqLQvOkjGlOL7I8k21nOsF5wcBNDF7ZGIWEiY5sIl2lZkomu_Boopu0bvdTA2DCzC3AEWYLUQ",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.7499.110 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    })

    params = {
        "ab_testid": "new_benefit_sort",
        "appType": app_type,
        "curr": curr,
        "dest": dest,
        "inheritFilters": "false",
        "lang": lang,
        "page": page,
        "query": query,
        "resultset": "catalog",
        "sort": sort,
        "spp": spp,
        "suppressSpellcheck": "false",
    }

    last_err: Optional[Exception] = None
    for attempt in range(1, max_retries + 1):
        try:
            r = session.get(WB_SEARCH_URL, params=params, timeout=timeout)
            if r.status_code == 429:
                time.sleep(0.6 * attempt)
                continue
            r.raise_for_status()
            data = r.json()
            products = data.get("products", []) or []

            cards: List[WbSearchCard] = []
            for p in products:
                nm_id = p.get("id")
                if nm_id is None:
                    continue
                sizes = p.get("sizes") or []
                price = (sizes[0].get("price") if sizes else {}) or {}
                card = WbSearchCard(
                    nm_id=int(nm_id),
                    name=str(p.get("name") or ""),
                    brand=p.get("brand"),
                    brand_id=p.get("brandId"),
                    supplier=p.get("supplier"),
                    supplier_id=p.get("supplierId"),
                    rating=p.get("rating"),
                    feedbacks=p.get("feedbacks"),
                    price_rub=_money_from_cents(price.get("product")),
                    price_basic_rub=_money_from_cents(price.get("basic")),
                    pics=p.get("pics"),
                    link=f"https://www.wildberries.ru/catalog/{int(nm_id)}/detail.aspx",
                )
                cards.append(card)
            return cards
        except Exception as e:
            last_err = e
            time.sleep(0.4 * attempt)
    raise RuntimeError(f"WB search failed after {max_retries} retries: {last_err}")

if __name__ == "__main__":
    q = "джинсы"
    cards = wb_search_cards(q, page=1, spp=30)
    for c in cards[:1]:
        print(asdict(c))
