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

# Только рабочие комбинации API
API_PAIRS = [
    ("express", "3"),
    ("express", "1"),
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
        if self.seo_code and self.store_code and self.store_code != "web":
            return f"https://magnit.ru/product/{self.id}-{self.seo_code}?shopCode={self.store_code}&shopType=1"
        elif self.store_code and self.store_code != "web":
            return f"https://magnit.ru/product/{self.id}?shopCode={self.store_code}&shopType=1"
        elif self.seo_code:
            return f"https://magnit.ru/product/{self.id}-{self.seo_code}"
        return f"https://magnit.ru/product/{self.id}"


class MagnitAPI:
    SEARCH_URL = "https://magnit.ru/webgate/v2/goods/search"
    STORES_URL = "https://magnit.ru/webgate/v1/stores-facade/search"

    def __init__(self):
        self.scraper = cloudscraper.create_scraper(browser='chrome')
        self.api_headers = {
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

    async def search_product(self, article: str, shop_code: str = None) -> Optional[Product]:
        """Основной поиск: HTML для карточки + API для цены"""
        logger.info(f"🔍 Поиск товара {article} (shop_code={shop_code})")

        base_product = await self._parse_product_page(article)
        if not base_product:
            logger.warning(f"  ❌ Не удалось получить карточку товара {article}")
            return None

        if not shop_code:
            return base_product

        api_product = await self._search_via_api(article, shop_code)
        if api_product:
            base_product.price = api_product.price
            base_product.quantity = api_product.quantity
            base_product.store_code = shop_code
            logger.info(f"  ✅ Цена в магазине {shop_code}: {api_product.price}₽, наличие: {api_product.quantity}")
            return base_product

        logger.warning(f"  ⚠️ API не вернул цену для {shop_code}")
        base_product.store_code = shop_code
        return base_product

    async def search_product_in_store(self, article: str, store_code: str) -> Optional[Product]:
        """ТОЛЬКО API для проверки в конкретном магазине"""
        return await self._search_via_api(article, store_code)

    async def _search_via_api(self, article: str, store_code: str) -> Optional[Product]:
        """Поиск товара через API"""
        for store_type, catalog_type in API_PAIRS:
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
                    self.SEARCH_URL, json=payload, headers=self.api_headers, timeout=5
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
                logger.info(f"✅ API: {store_code} (st={store_type}, ct={catalog_type}): {item.get('name', '')}")

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
                logger.debug(f"⚠️ API ошибка {store_code}: {e}")
                continue

        return None

    async def _parse_product_page(self, article: str) -> Optional[Product]:
        """Парсит HTML ТОЛЬКО для получения названия, картинки и seo_code"""
        urls = [f"https://magnit.ru/product/{article}", f"https://magnit.ru/product/{article}/"]
        for url in urls:
            try:
                resp = self.scraper.get(url, headers=self.html_headers, timeout=10)
                if resp.status_code != 200:
                    continue
                html = resp.text

                match = re.search(
                    r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>',
                    html, re.DOTALL
                )
                if match:
                    try:
                        data = json.loads(match.group(1))
                        pp = data.get("props", {}).get("pageProps", {})
                        item = pp.get("product") or pp.get("item") or self._find_recursive(pp)
                        if item and isinstance(item, dict):
                            return self._product_from_dict(item, article)
                    except Exception:
                        pass

                title_match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
                img_match = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
                if title_match:
                    name = title_match.group(1)
                    for sep in [' – ', ' - ', ' | ', '—']:
                        if sep in name:
                            name = name.split(sep)[0].strip()
                            break
                    return Product(
                        id=article, name=name, price=0, quantity=0, store_code="web",
                        image_url=img_match.group(1) if img_match else "",
                        rating=0, is_adult=False, seo_code=""
                    )
            except Exception:
                continue
        return None

    def _find_recursive(self, data, d=0):
        if d > 5:
            return None
        if isinstance(data, dict):
            if "id" in data and "name" in data:
                return data
            for v in data.values():
                r = self._find_recursive(v, d + 1)
                if r:
                    return r
        elif isinstance(data, list):
            for i in data:
                r = self._find_recursive(i, d + 1)
                if r:
                    return r
        return None

    def _product_from_dict(self, item: dict, article: str) -> Optional[Product]:
        try:
            return Product(
                id=str(item.get("id") or item.get("productId") or article),
                name=item.get("name", "Без названия"),
                price=0, quantity=0, store_code="web",
                image_url=self._get_image_url(item),
                rating=float(item.get("ratings", {}).get("rating", 0) if isinstance(item.get("ratings"), dict) else 0),
                is_adult=bool(item.get("isForAdults", False)),
                seo_code=item.get("seoCode", "")
            )
        except Exception:
            return None

    def _get_image_url(self, item: dict) -> str:
        gal = item.get("gallery", [])
        if gal and isinstance(gal, list) and len(gal) > 0:
            f = gal[0]
            if isinstance(f, dict):
                return f.get("url", "")
            return str(f)
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
            resp = self.scraper.post(self.STORES_URL, json=payload, headers=self.api_headers, timeout=15)
            if resp.status_code != 200:
                return []
            data = resp.json()
            raw = data.get("items", {}).get("items", [])
            stores = []
            for s in raw:
                if not s.get("isActive"):
                    continue
                c = s.get("coordinates", {})
                slat, slon = c.get("latitude", 0), c.get("longitude", 0)
                dist = geodesic((lat, lon), (slat, slon)).km
                code = s.get("externalId", {}).get("storeCode", "")
                stores.append({
                    "code": code,
                    "name": f"Магнит #{code}",
                    "latitude": slat,
                    "longitude": slon,
                    "distance": dist,
                    "storeType": s.get("storeTypeV2", "MM")
                })
            stores.sort(key=lambda x: x["distance"])
            logger.info(f"Найдено {len(stores)} магазинов в радиусе {radius_km} км")
            return stores
        except Exception as e:
            logger.error(f"Ошибка поиска магазинов: {e}")
            return []


def get_address_from_coordinates(lat: float, lon: float) -> str:
    try:
        loc = geolocator.reverse(f"{lat}, {lon}", language="ru", exactly_one=True)
        if loc and loc.address:
            return ", ".join(loc.address.split(",")[0:3])
    except (GeocoderTimedOut, GeocoderServiceError):
        pass
    except Exception as e:
        logger.warning(f"⚠️ Ошибка адреса: {e}")
    return f"Координаты: {lat:.4f}, {lon:.4f}"


magnit_api = MagnitAPI()
