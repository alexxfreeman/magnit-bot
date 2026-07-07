import cloudscraper
import asyncio
import logging
import math
from typing import List, Dict, Optional
from dataclasses import dataclass
from geopy.distance import geodesic
from geopy.geocoders import Nominatim

logger = logging.getLogger(__name__)
geolocator = Nominatim(user_agent="magnit_bot_v1")

CATALOG_TYPE_NAMES = {
    "1": "🏪 В магазине",
    "2": "🚚 Доставка",
    "3": "📦 Самовывоз"
}

# Магазины из разных регионов РФ
FALLBACK_STORES = [
    "760001", "494318", "219282",  # Москва
    "764574", "764729",  # СПб
    "764557", "388291", "703750", "764548", "764683",  # Ярославль
    "764602", "760004",  # Юг
    "947604", "760078",  # Урал
    "764657", "720146",  # Сибирь
    "937695", "388641", "760151", "453594", "764525",  # Другие регионы
]


@dataclass
class Product:
    id: str
    name: str
    price: float
    quantity: int
    store_code: str
    image_url: str
    rating: float
    is_adult: bool
    seo_code: str
    catalog_type: str = "1"
    catalog_type_name: str = "🏪 В магазине"

    @property
    def in_stock(self) -> bool:
        return self.quantity > 0

    @property
    def url(self) -> str:
        return f"https://magnit.ru/catalog/?q={self.id}"


class MagnitAPI:
    SEARCH_URL = "https://magnit.ru/webgate/v2/goods/search"
    STORES_URL = "https://magnit.ru/webgate/v1/stores-facade/search"

    def __init__(self):
        self.scraper = cloudscraper.create_scraper()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://magnit.ru",
            "Referer": "https://magnit.ru/"
        }

    async def search_product(
        self,
        article: str,
        shop_code: str = None,
        store_type: str = "express",
        catalog_type: str = None
    ) -> Optional[Product]:
        """
        Поиск товара.
        Стратегия:
        1. Если shop_code и catalog_type указаны - пробуем их первым
        2. Перебираем fallback магазины с catalogType=1 (основной)
        3. Если не нашли - пробуем catalogType=2 и 3
        """
        # Шаг 1: Пробуем конкретный магазин и каталог из ссылки
        if shop_code and catalog_type:
            logger.info(f"Пробую магазин {shop_code} с catalogType={catalog_type}")
            product = await self._try_search(article, shop_code, store_type, catalog_type)
            if product:
                return product

        # Шаг 2: Перебираем fallback магазины с catalogType=1
        codes_to_try = []
        if shop_code and shop_code not in codes_to_try:
            codes_to_try.append(shop_code)
        codes_to_try.extend(FALLBACK_STORES)

        # Убираем дубликаты
        seen = set()
        unique_codes = []
        for code in codes_to_try:
            if code not in seen:
                seen.add(code)
                unique_codes.append(code)
        codes_to_try = unique_codes

        # Пробуем основной каталог (1)
        logger.info(f"Перебираю {len(codes_to_try)} магазинов с catalogType=1")
        for code in codes_to_try:
            product = await self._try_search(article, code, store_type, "1")
            if product:
                return product
            await asyncio.sleep(0.1)  # Небольшая задержка

        # Шаг 3: Если не нашли - пробуем другие каталоги
        if catalog_type != "2":
            logger.info("Пробую catalogType=2")
            for code in codes_to_try[:5]:  # Только первые 5 магазинов
                product = await self._try_search(article, code, store_type, "2")
                if product:
                    return product
                await asyncio.sleep(0.1)

        if catalog_type != "3":
            logger.info("Пробую catalogType=3")
            for code in codes_to_try[:5]:  # Только первые 5 магазинов
                product = await self._try_search(article, code, store_type, "3")
                if product:
                    return product
                await asyncio.sleep(0.1)

        logger.info(f"❌ Товар {article} не найден")
        return None

    async def _try_search(
        self,
        article: str,
        store_code: str,
        store_type: str,
        catalog_type: str
    ) -> Optional[Product]:
        """Попытка найти товар в конкретном магазине с конкретным каталогом"""
        payload = {
            "term": article,
            "storeCode": store_code,
            "storeType": store_type,
            "catalogType": catalog_type,
            "includeAdultGoods": True,
            "pagination": {"offset": 0, "limit": 36},
            "sort": {"order": "desc", "type": "popularity"}
        }

        try:
            response = self.scraper.post(
                self.SEARCH_URL, json=payload, headers=self.headers, timeout=10
            )

            if response.status_code != 200:
                logger.debug(f"HTTP {response.status_code} для {store_code}/{catalog_type}")
                return None

            data = response.json()
            if not data.get("isSearchByArticle"):
                return None

            items = data.get("items", [])
            if not items:
                return None

            item = items[0]
            logger.info(f"✅ Найден в {store_code} (cat={catalog_type}): {item.get('name', '')}")

            return Product(
                id=item.get("id") or item.get("productId"),
                name=item.get("name", "Без названия"),
                price=item.get("price", 0) / 100,
                quantity=item.get("quantity", 0),
                store_code=item.get("storeCode", store_code),
                image_url=self._get_image_url(item),
                rating=item.get("ratings", {}).get("rating", 0),
                is_adult=item.get("isForAdults", False),
                seo_code=item.get("seoCode", ""),
                catalog_type=catalog_type,
                catalog_type_name=CATALOG_TYPE_NAMES.get(catalog_type, f"Каталог {catalog_type}")
            )
        except Exception as e:
            logger.error(f"Ошибка {store_code}/{catalog_type}: {e}")
            return None

    def _get_image_url(self, item: dict) -> str:
        gallery = item.get("gallery", [])
        return gallery[0].get("url", "") if gallery else ""

    def calculate_bounding_box(self, lat: float, lon: float, radius_km: float) -> dict:
        lat_delta = radius_km / 111.0
        lon_delta = radius_km / (111.0 * math.cos(math.radians(lat)))
        return {
            "leftTopPoint": {"latitude": lat + lat_delta, "longitude": lon - lon_delta},
            "rightBottomPoint": {"latitude": lat - lat_delta, "longitude": lon + lon_delta}
        }

    async def get_stores_nearby(self, lat: float, lon: float, radius_km: float = 10) -> List[dict]:
        bbox = self.calculate_bounding_box(lat, lon, radius_km)
        payload = {
            "filters": {
                "geo": {
                    "typeName": "box",
                    "leftTopPoint": bbox["leftTopPoint"],
                    "rightBottomPoint": bbox["rightBottomPoint"]
                },
                "storeTypeListV2": ["MM", "GM", "DG", "MO", "ME", "MC", "DARKSTORE", "MM_MINI", "ZARYAD"]
            }
        }

        try:
            response = self.scraper.post(
                self.STORES_URL, json=payload, headers=self.headers, timeout=15
            )
            if response.status_code != 200:
                return []

            data = response.json()
            stores_raw = data.get("items", {}).get("items", [])
            stores = []

            for store in stores_raw:
                if not store.get("isActive", False):
                    continue
                coords = store.get("coordinates", {})
                store_lat = coords.get("latitude", 0)
                store_lon = coords.get("longitude", 0)
                distance = geodesic((lat, lon), (store_lat, store_lon)).km
                store_code = store.get("externalId", {}).get("storeCode", "")

                stores.append({
                    "code": store_code,
                    "name": f"Магнит #{store_code}",
                    "address": "",
                    "latitude": store_lat,
                    "longitude": store_lon,
                    "distance": distance,
                    "storeType": store.get("storeTypeV2", "MM")
                })

            stores.sort(key=lambda x: x["distance"])
            logger.info(f"Найдено {len(stores)} магазинов в радиусе {radius_km} км")
            return stores
        except Exception as e:
            logger.error(f"Ошибка поиска магазинов: {e}")
            return []


def get_address_from_coordinates(lat: float, lon: float) -> str:
    try:
        location = geolocator.reverse(f"{lat}, {lon}", language="ru", timeout=5)
        if location and location.address:
            return ", ".join(location.address.split(",")[0:3])
    except Exception as e:
        logger.error(f"Ошибка получения адреса: {e}")
    return f"Координаты: {lat:.4f}, {lon:.4f}"


magnit_api = MagnitAPI()
