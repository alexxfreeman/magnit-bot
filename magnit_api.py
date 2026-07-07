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
        else:
            return f"https://magnit.ru/product/{self.id}"


class MagnitAPI:
    STORES_URL = "https://magnit.ru/webgate/v1/stores-facade/search"

    def __init__(self):
        self.scraper = cloudscraper.create_scraper(browser='chrome')
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
        }

    async def search_product(
        self,
        article: str,
        shop_code: str = None,
        store_type=None,
        catalog_type=None
    ) -> Optional[Product]:
        """Поиск товара через HTML-парсинг"""
        logger.info(f"🔍 Поиск товара {article} (shop_code={shop_code})")

        # Парсим HTML страницу товара
        product = await self._parse_product_page(article, shop_code)
        if product:
            return product

        logger.warning(f"  ❌ Товар {article} не найден")
        return None

    async def search_product_in_store(
        self,
        article: str,
        store_code: str
    ) -> Optional[Product]:
        """Поиск товара в конкретном магазине через HTML-парсинг"""
        return await self._parse_product_page(article, store_code)

    async def _parse_product_page(self, article: str, shop_code: str = None) -> Optional[Product]:
        """Парсит HTML страницу товара"""
        # Формируем URL с shopCode если указан
        if shop_code:
            urls_to_try = [
                f"https://magnit.ru/product/{article}?shopCode={shop_code}&shopType=1",
                f"https://magnit.ru/product/{article}/?shopCode={shop_code}&shopType=1",
            ]
        else:
            urls_to_try = [
                f"https://magnit.ru/product/{article}",
                f"https://magnit.ru/product/{article}/",
            ]

        for url in urls_to_try:
            try:
                response = self.scraper.get(url, headers=self.headers, timeout=15)
                if response.status_code != 200:
                    logger.debug(f"  ⚠️ HTTP {response.status_code} для {url}")
                    continue

                html = response.text

                # Способ 1: JSON в теге <script id="__NEXT_DATA__">
                match = re.search(
                    r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>',
                    html,
                    re.DOTALL
                )
                if match:
                    try:
                        next_data = json.loads(match.group(1))
                        product = self._extract_from_next_data(next_data, article, shop_code)
                        if product:
                            logger.info(f"✅ Найден через __NEXT_DATA__: {product.name}")
                            return product
                    except json.JSONDecodeError:
                        pass

                # Способ 2: JSON в window.__INITIAL_STATE__
                match = re.search(r'window\.__[A-Z_]+__\s*=\s*({.*?});', html, re.DOTALL)
                if match:
                    try:
                        data = json.loads(match.group(1))
                        product = self._extract_from_initial_state(data, article, shop_code)
                        if product:
                            logger.info(f"✅ Найден через window state: {product.name}")
                            return product
                    except json.JSONDecodeError:
                        pass

                # Способ 3: JSON-LD (schema.org)
                match = re.search(
                    r'<script\s+type="application/ld\+json">(.*?)</script>',
                    html,
                    re.DOTALL
                )
                if match:
                    try:
                        ld_data = json.loads(match.group(1))
                        product = self._extract_from_ld_json(ld_data, article, shop_code)
                        if product:
                            logger.info(f"✅ Найден через JSON-LD: {product.name}")
                            return product
                    except json.JSONDecodeError:
                        pass

                # Способ 4: Meta-теги (последний шанс)
                product = self._extract_from_meta_tags(html, article, shop_code)
                if product:
                    logger.info(f"✅ Найден через meta-теги: {product.name}")
                    return product

            except Exception as e:
                logger.error(f"  ❌ Ошибка парсинга {url}: {e}")
                continue

        return None

    def _extract_from_next_data(self, data: dict, article: str, shop_code: str = None) -> Optional[Product]:
        """Извлекает товар из __NEXT_DATA__"""
        try:
            page_props = data.get("props", {}).get("pageProps", {})
            item = (
                page_props.get("product") or
                page_props.get("item") or
                page_props.get("data", {}).get("product") or
                page_props.get("initialState", {}).get("product", {}).get("current")
            )
            if not item:
                item = self._find_product_recursive(page_props)
            if not item or not isinstance(item, dict):
                return None
            return self._product_from_dict(item, article, shop_code)
        except Exception as e:
            logger.debug(f"  ⚠️ Ошибка извлечения из NEXT_DATA: {e}")
            return None

    def _extract_from_initial_state(self, data: dict, article: str, shop_code: str = None) -> Optional[Product]:
        """Извлекает товар из window.__INITIAL_STATE__"""
        try:
            item = self._find_product_recursive(data)
            if item:
                return self._product_from_dict(item, article, shop_code)
        except Exception as e:
            logger.debug(f"  ⚠️ Ошибка извлечения из initial state: {e}")
        return None

    def _extract_from_ld_json(self, data: dict, article: str, shop_code: str = None) -> Optional[Product]:
        """Извлекает товар из JSON-LD (schema.org)"""
        try:
            if data.get("@type") in ["Product", "product"]:
                name = data.get("name", "")
                offers = data.get("offers", {})
                price = 0
                if isinstance(offers, dict):
                    price = float(offers.get("price", 0))
                elif isinstance(offers, list) and offers:
                    price = float(offers[0].get("price", 0))

                image = data.get("image", "")
                if isinstance(image, list) and image:
                    image = image[0]

                return Product(
                    id=article,
                    name=name,
                    price=price,
                    quantity=1 if price > 0 else 0,
                    store_code=shop_code or "web",
                    image_url=image,
                    rating=float(data.get("aggregateRating", {}).get("ratingValue", 0) or 0),
                    is_adult=False,
                    seo_code="",
                )
        except Exception as e:
            logger.debug(f"  ⚠️ Ошибка извлечения из JSON-LD: {e}")
        return None

    def _extract_from_meta_tags(self, html: str, article: str, shop_code: str = None) -> Optional[Product]:
        """Извлекает данные из meta-тегов"""
        try:
            title_match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
            image_match = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
            price_match = re.search(r'"price"\s*:\s*"?([\d.]+)"?', html)

            if title_match:
                name = title_match.group(1)
                # Очищаем название от мусора
                for separator in [' – ', ' - ', ' | ', '—', ' – купить']:
                    if separator in name:
                        name = name.split(separator)[0].strip()
                        break

                image = image_match.group(1) if image_match else ""
                price = float(price_match.group(1)) if price_match else 0

                return Product(
                    id=article,
                    name=name,
                    price=price,
                    quantity=1 if price > 0 else 0,
                    store_code=shop_code or "web",
                    image_url=image,
                    rating=0,
                    is_adult=False,
                    seo_code="",
                )
        except Exception as e:
            logger.debug(f"⚠️ Ошибка извлечения из meta: {e}")
        return None

    def _find_product_recursive(self, data, depth=0) -> Optional[dict]:
        """Рекурсивно ищет объект товара в структуре данных"""
        if depth > 10:
            return None
        if isinstance(data, dict):
            if "id" in data and "name" in data and "price" in data:
                return data
            if "productId" in data and "name" in data:
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

    def _product_from_dict(self, item: dict, article: str, shop_code: str = None) -> Optional[Product]:
        """Создаёт Product из словаря"""
        try:
            price_raw = item.get("price", 0)
            if isinstance(price_raw, str):
                price_raw = float(price_raw.replace(",", "."))
            if price_raw > 100000:
                price_raw = price_raw / 100

            return Product(
                id=str(item.get("id") or item.get("productId") or article),
                name=item.get("name", "Без названия"),
                price=float(price_raw),
                quantity=int(item.get("quantity", 0) or 0),
                store_code=shop_code or str(item.get("storeCode", "web")),
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
