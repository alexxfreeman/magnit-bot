import cloudscraper
import asyncio
import logging
import math
from typing import List, Optional
from dataclasses import dataclass
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

logger = logging.getLogger(__name__)
geolocator = Nominatim(user_agent="magnit_bot_v1", timeout=10)

FALLBACK_STORES = [
    "760001", "494318", "219282",
    "764574", "764729",
    "764557", "388291", "703750", "764548", "764683",
    "764602", "760004",
    "947604", "760078",
    "764657", "720146",
    "937695", "388641", "760151", "453594", "764525",
    "323593",
]

VALID_SERVICE_PAIRS = [
    (1, 1),
    (1, 3),
    (2, 2),
    (3, 3),
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
        self.scraper = cloudscraper.create_scraper(browser='chrome')
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Content-Type": "application/json",
            "Origin": "https://magnit.ru",
            "Referer": "https://magnit.ru/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin"
        }

    async def search_product(
        self,
        article: str,
        shop_code: str = None,
        store_type = None,
        catalog_type = None
    ) -> Optional[Product]:
        logger.info(f"🔍 Поиск товара {article} (shop_code={shop_code}, store_type={store_type}, catalog_type={catalog_type})")
        
        # Шаг 1: Пробуем с shopCode (если указан)
        if shop_code:
            logger.info(f"  → Шаг 1: Пробую с shopCode={shop_code}")
            
            # Пробуем переданные значения
            if store_type is not None and catalog_type is not None:
                try:
                    st_num = int(store_type)
                    ct_num = int(catalog_type)
                    logger.info(f"    → Пробую {shop_code} с storeType={st_num}, catalogType={ct_num}")
                    product = await self._try_search(article, shop_code, st_num, ct_num)
                    if product:
                        return product
                except (ValueError, TypeError):
                    pass
            
            # Перебираем все комбинации
            for st, ct in VALID_SERVICE_PAIRS:
                logger.info(f"    → Пробую {shop_code} с storeType={st}, catalogType={ct}")
                product = await self._try_search(article, shop_code, st, ct)
                if product:
                    return product
            
            logger.warning(f"  ⚠️ Не нашёл в магазине {shop_code}, пробую без shopCode...")
        
        # Шаг 2: Пробуем БЕЗ shopCode — перебираем fallback-магазины
        logger.info(f"  → Шаг 2: Перебираю {len(FALLBACK_STORES)} fallback-магазинов")
        codes_to_try = list(dict.fromkeys(FALLBACK_STORES))
        
        for code in codes_to_try:
            for st, ct in VALID_SERVICE_PAIRS:
                product = await self._try_search(article, code, st, ct)
                if product:
                    return product
            await asyncio.sleep(0.1)
        
        # Шаг 3: Пробуем БЕЗ shopCode вообще (если API поддерживает)
        logger.info(f"  → Шаг 3: Пробую поиск БЕЗ shopCode")
        for st, ct in VALID_SERVICE_PAIRS:
            product = await self._try_search_without_store(article, st, ct)
            if product:
                return product
        
        logger.warning(f"  ❌ Товар {article} не найден нигде")
        return None

    async def _try_search(
        self,
        article: str,
        store_code: str,
        store_type,
        catalog_type
    ) -> Optional[Product]:
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
                logger.debug(f"    ⚠️ HTTP {response.status_code} от {store_code}")
                return None

            data = response.json()
            if not data.get("isSearchByArticle"):
                return None

            items = data.get("items", [])
            if not items:
                return None

            item = items[0]
            logger.info(f"✅ Найден в {store_code} (storeType={store_type}, catalogType={catalog_type}): {item.get('name', '')}")

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
                catalog_type=str(catalog_type),
                catalog_type_name="🏪 В магазине"
            )
        except Exception as e:
            logger.error(f"    ❌ Ошибка {store_code}: {e}")
            return None

    async def _try_search_without_store(
        self,
        article: str,
        store_type,
        catalog_type
    ) -> Optional[Product]:
        """Поиск БЕЗ shopCode — только по артикулу"""
        payload = {
            "term": article,
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
                return None

            data = response.json()
            if not data.get("isSearchByArticle"):
                return None

            items = data.get("items", [])
            if not items:
                return None

            item = items[0]
            logger.info(f"✅ Найден БЕЗ shopCode (storeType={store_type}, catalogType={catalog_type}): {item.get('name', '')}")

            return Product(
                id=item.get("id") or item.get("productId"),
                name=item.get("name", "Без названия"),
                price=item.get("price", 0) / 100,
                quantity=item.get("quantity", 0),
                store_code=item.get("storeCode", "unknown"),
                image_url=self._get_image_url(item),
                rating=item.get("ratings", {}).get("rating", 0),
                is_adult=item.get("isForAdults", False),
                seo_code=item.get("seoCode", ""),
                catalog_type=str(catalog_type),
                catalog_type_name="🏪 В магазине"
            )
        except Exception as e:
            logger.error(f"    ❌ Ошибка поиска без shopCode: {e}")
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
        location = geolocator.reverse(f"{lat}, {lon}", language="ru", exactly_one=True)
        if location and location.address:
            return ", ".join(location.address.split(",")[0:3])
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        logger.warning(f"⏱️ Таймаут получения адреса для ({lat:.4f}, {lon:.4f})")
    except Exception as e:
        logger.warning(f"⚠️ Ошибка получения адреса: {e}")
    return f"Координаты: {lat:.4f}, {lon:.4f}"


magnit_api = MagnitAPI()
