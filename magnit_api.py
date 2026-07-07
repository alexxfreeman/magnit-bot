import cloudscraper
import asyncio
import logging
import math
import re
import json
from typing import List, Optional
from dataclasses import dataclass
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

logger = logging.getLogger(__name__)
geolocator = Nominatim(user_agent="magnit_bot_v1", timeout=10)

# Рабочие комбинации storeType/catalogType для API
# ("express", "3") и ("express", "1") — проверено, что работают
WORKING_PAIRS = [
    ("express", "3"),
    ("express", "1"),
    (1, 1),
    (1, 3),
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
        """Формирует ссылку на товар в конкретном магазине"""
        if self.seo_code and self.store_code and self.store_code != "web":
            return f"https://magnit.ru/product/{self.id}-{self.seo_code}?shopCode={self.store_code}&shopType=1"
        elif self.store_code and self.store_code != "web":
            return f"https://magnit.ru/product/{self.id}?shopCode={self.store_code}&shopType=1"
        elif self.seo_code:
            return f"https://magnit.ru/product/{self.id}-{self.seo_code}"
        else:
            return f"https://magnit.ru/product/{self.id}"


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
        }
        self.html_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9",
        }

    async def search_product(
        self,
        article: str,
        shop_code: str = None,
        store_type=None,
        catalog_type=None
    ) -> Optional[Product]:
        """
        Основной поиск товара.
        1. HTML-парсинг — для получения базовой инфо (название, картинка, seo_code)
        2. Если указан shop_code — API-запрос для получения цены в конкретном магазине
        """
        logger.info(f"🔍 Поиск товара {article} (shop_code={shop_code})")

        # ШАГ 1: HTML-парсинг для базовой информации
        base_product = await self._parse_product_page(article)
        
        if not base_product:
            logger.warning(f"  ❌ Не удалось получить базовую информацию о товаре {article}")
            return None

        # Если shop_code не указан — возвращаем базовую информацию
        if not shop_code:
            logger.info(f"  ✅ Базовая информация получена: {base_product.name}")
            return base_product

        # ШАГ 2: API-запрос для получения цены в конкретном магазине
        logger.info(f"  → Запрашиваю цену в магазине {shop_code} через API")
        api_product = await self._search_via_api(article, shop_code)
        
        if api_product:
            # Объединяем: берём название/картинку из HTML, цену/наличие из API
            base_product.price = api_product.price
            base_product.quantity = api_product.quantity
            base_product.store_code = shop_code
            logger.info(f"  ✅ Цена в магазине {shop_code}: {api_product.price}₽, наличие: {api_product.quantity}")
            return base_product
        
        # Если API не сработал — возвращаем базовую информацию
        logger.warning(f"  ⚠️ API не вернул цену для {shop_code}, использую базовую информацию")
        base_product.store_code = shop_code
        return base_product

    async def search_product_in_store(
        self,
        article: str,
        store_code: str
    ) -> Optional[Product]:
        """
        Быстрый поиск товара в конкретном магазине — ТОЛЬКО API.
        Используется при проверке 50 магазинов по геолокации.
        """
        return await self._search_via_api(article, store_code)

    async def _search_via_api(
        self,
        article: str,
        store_code: str
    ) -> Optional[Product]:
        """Поиск товара через API с перебором рабочих комбинаций"""
        for store_type, catalog_type in WORKING_PAIRS:
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
                    continue

                data = response.json()
                if not data.get("isSearchByArticle"):
                    continue

                items = data.get("items", [])
                if not items:
                    continue

                item = items[0]
                logger.debug(f"✅ API: {store_code} (st={store_type}, ct={catalog_type}): {item.get('name', '')}")

                return Product(
                    id=str(item.get("id") or item.get("productId") or article),
                    name=item.get("name", ""),
                    price=item.get("price", 0) / 100,
                    quantity=item.get("quantity", 0),
                    store_code=item.get("storeCode", store_code),
                    image_url=self._get_image_url(item),
                    rating=item.get("ratings", {}).get("rating", 0) if isinstance(item.get("ratings"), dict) else 0,
                    is_adult=item.get("isForAdults", False),
                    seo_code=item.get("seoCode", ""),
                    catalog_type=str(catalog_type),
                    catalog_type_name="🏪 В магазине"
                )
            except Exception as e:
                logger.debug(f"  ⚠️ API ошибка {store_code} (st={store_type}, ct={catalog_type}): {e}")
                continue

        return None

    async def _parse_product_page(self, article: str) -> Optional[Product]:
        """Парсит HTML страницу товара — только для базовой информации"""
        urls_to_try = [
            f"https://magnit.ru/product/{article}",
            f"https://magnit.ru/product/{article}/",
        ]

        for url in urls_to_try:
            try:
                response = self.scraper.get(url, headers=self.html_headers, timeout=15)
                if response.status_code != 200:
                    continue

                html = response.text

                # Способ 1: __NEXT_DATA__
                match = re.search(
                    r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>',
                    html, re.DOTALL
                )
                if match:
                    try:
                        next_data = json.loads(match.group(1))
                        product = self._extract_from_next_data(next_data, article)
                        if product:
                            return product
                    except json.JSONDecodeError:
                        pass

                # Способ 2: JSON-LD
                match = re.search(
                    r'<script\s+type="application/ld\+json">(.*?)</script>',
                    html, re.DOTALL
                )
                if match:
                    try:
                        ld_data = json.loads(match.group(1))
                        product = self._extract_from_ld_json(ld_data, article)
                        if product:
                            return product
                    except json.JSONDecodeError:
                        pass

                # Способ 3: Meta-теги
                product = self._extract_from_meta_tags(html, article)
                if product:
                    return product

            except Exception as e:
                logger.error(f"  ❌ Ошибка парсинга {url}: {e}")
                continue

        return None

    def _extract_from_next_data(self, data: dict, article: str) -> Optional[Product]:
        try:
            page_props = data.get("props", {}).get("pageProps", {})
            item = (
                page_props.get("product") or
                page_props.get("item") or
                page_props.get("data", {}).get("product")
            )
            if not item:
                item = self._find_product_recursive(page_props)
            if not item or not isinstance(item, dict):
                return None
            return self._product_from_dict(item, article)
        except Exception as e:
            logger.debug(f"  ⚠️ NEXT_DATA ошибка: {e}")
            return None

    def _extract_from_ld_json(self, data: dict, article: str) -> Optional[Product]:
        try:
            if data.get("@type") in ["Product", "product"]:
                name = data.get("name", "")
                image = data.get("image", "")
                if isinstance(image, list) and image:
                    image = image[0]
                return Product(
                    id=article,
                    name=name,
                    price=0,
                    quantity=0,
                    store_code="web",
                    image_url=image if isinstance(image, str) else "",
                    rating=0,
                    is_adult=False,
                    seo_code="",
                )
        except Exception as e:
            logger.debug(f"  ⚠️ JSON-LD ошибка: {e}")
        return None

    def _extract_from_meta_tags(self, html: str, article: str) -> Optional[Product]:
        try:
            title_match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
            image_match = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)

            if title_match:
                name = title_match.group(1)
                # Очищаем название от мусора
                for separator in [' – ', ' - ', ' | ', '—']:
                    if separator in name:
                        name = name.split(separator)[0].strip()
                        break

                image = image_match.group(1) if image_match else ""

                return Product(
                    id=article,
                    name=name,
                    price=0,
                    quantity=0,
                    store_code="web",
                    image_url=image,
                    rating=0,
                    is_adult=False,
                    seo_code="",
                )
        except Exception as e:
            logger.debug(f"⚠️ Meta ошибка: {e}")
        return None

    def _find_product_recursive(self, data, depth=0) -> Optional[dict]:
        if depth > 10:
            return None
        if isinstance(data, dict):
            if "id" in data and "name" in data:
                return data
            for value in data.values():
                result = self._find_product_recursive(value, depth + 1)
                if result:
                    return result
        elif isinstance(data, list):
            for item in data:
                result = self._find_product_recursive(item, depth + 1)
                if result:
                    return result
        return None

    def _product_from_dict(self, item: dict, article: str) -> Optional[Product]:
        try:
            return Product(
                id=str(item.get("id") or item.get("productId") or article),
                name=item.get("name", "Без названия"),
                price=0,  # Цену получим через API
                quantity=0,
                store_code="web",
                image_url=self._get_image_url(item),
                rating=float(item.get("ratings", {}).get("rating", 0) if isinstance(item.get("ratings"), dict) else 0),
                is_adult=bool(item.get("isForAdults", False)),
                seo_code=item.get("seoCode", ""),
            )
        except Exception as e:
            logger.error(f"  ❌ Ошибка создания Product: {e}")
            return None

    def _get_image_url(self, item: dict) -> str:
        gallery = item.get("gallery", [])
        if gallery and isinstance(gallery, list) and len(gallery) > 0:
            first = gallery[0]
            if isinstance(first, dict):
                return first.get("url", "")
            return str(first)
        if "image" in item:
            img = item["image"]
            if isinstance(img, list) and img:
                return img[0] if isinstance(img[0], str) else ""
            if isinstance(img, str):
                return img
        return ""

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
    except (GeocoderTimedOut, GeocoderServiceError):
        pass
    except Exception as e:
        logger.warning(f"⚠️ Ошибка получения адреса: {e}")
    return f"Координаты: {lat:.4f}, {lon:.4f}"


magnit_api = MagnitAPI()
