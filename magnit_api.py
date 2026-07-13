import asyncio
import logging
import math
import re
import json
from typing import List, Optional
from dataclasses import dataclass
from playwright.async_api import async_playwright
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
import cloudscraper

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
        if self.seo_code and self.store_code and self.store_code != "web":
            return f"https://magnit.ru/product/{self.id}-{self.seo_code}?shopCode={self.store_code}&shopType=1"
        elif self.store_code and self.store_code != "web":
            return f"https://magnit.ru/product/{self.id}?shopCode={self.store_code}&shopType=1"
        elif self.seo_code:
            return f"https://magnit.ru/product/{self.id}-{self.seo_code}"
        return f"https://magnit.ru/product/{self.id}"

class MagnitAPI:
    STORES_URL = "https://magnit.ru/webgate/v1/stores-facade/search"
    browser = None

    def __init__(self):
        self.scraper = cloudscraper.create_scraper(browser='chrome')
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    async def init_browser(self):
        if self.browser is None:
            playwright = await async_playwright().start()
            self.browser = await playwright.chromium.launch(
                headless=True,
                proxy={
                    "server": "http://81.177.180.246:8000",
                    "username": "nbsYBT",
                    "password": "v6pvCe"
                },
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
            )
            logger.info("✅ Браузер Chromium запущен через российский прокси")

    async def search_product(self, article: str, shop_code: str = None) -> Optional[Product]:
        await self.init_browser()
        logger.info(f" Поиск товара {article} (shop_code={shop_code})")
        
        if shop_code:
            url = f"https://magnit.ru/product/{article}?shopCode={shop_code}&shopType=1"
        else:
            url = f"https://magnit.ru/product/{article}"

        try:
            context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent=self.headers["User-Agent"]
            )
            page = await context.new_page()
            await page.goto(url, wait_until='domcontentloaded', timeout=20000)
            
            # Сохраняем HTML для диагностики
            html = await page.content()
            with open('/root/magnit-bot/debug_page.html', 'w', encoding='utf-8') as f:
                f.write(html)
            logger.info(f" HTML сохранён в debug_page.html (длина: {len(html)})")
            
            # Проверяем, есть ли признаки QRATOR/капчи
            if 'qrator' in html.lower() or 'challenge' in html.lower():
                logger.warning("⚠️ Обнаружена защита QRATOR на странице")
            # Ждем появления цены или данных
            try:
                await page.wait_for_selector('[class*="Price"], [data-testid*="price"]', timeout=5000)
            except:
                pass

            # Извлекаем данные из __NEXT_DATA__ (там точная цена для магазина)
            next_data = await page.evaluate('''() => {
                const el = document.getElementById('__NEXT_DATA__');
                return el ? JSON.parse(el.textContent) : null;
            }''')

            product = None
            if next_data:
                product = self._parse_next_data(next_data, article, shop_code)
            
            if not product:
                # Fallback на meta-теги
                product = await self._parse_meta_fallback(page, article, shop_code)

            await context.close()
            if product:
                logger.info(f"✅ Найдено: {product.name[:40]}... ({product.price}₽)")
            return product

        except Exception as e:
            logger.error(f"❌ Ошибка Playwright для {article}: {e}")
            return None

    def _parse_next_data(self, data: dict, article: str, shop_code: str = None) -> Optional[Product]:
        try:
            pp = data.get("props", {}).get("pageProps", {})
            item = pp.get("product") or pp.get("item") or self._find_recursive(pp)
            if not item or not isinstance(item, dict):
                return None

            price = self._extract_price(item)
            name = item.get("name", "")
            for sep in [' – ', ' - ', ' | ', '—']:
                if sep in name: name = name.split(sep)[0].strip(); break

            image_url = self._get_image_url(item)
            quantity = item.get("quantity", 0)
            if isinstance(quantity, dict): quantity = quantity.get("value", 0)

            return Product(
                id=article, name=name, price=price, quantity=int(quantity) if quantity else 0,
                store_code=shop_code or "web", image_url=image_url, rating=0, is_adult=False, seo_code=item.get("seoCode", "")
            )
        except Exception as e:
            logger.debug(f"⚠️ Ошибка парсинга NEXT_DATA: {e}")
            return None

    async def _parse_meta_fallback(self, page, article: str, shop_code: str = None) -> Optional[Product]:
        try:
            title = await page.evaluate('''() => document.querySelector('meta[property="og:title"]')?.content || ''''')
            image = await page.evaluate('''() => document.querySelector('meta[property="og:image"]')?.content || ''''')
            if not title: return None
            
            name = title
            for sep in [' – ', ' - ', ' | ', '—']:
                if sep in name: name = name.split(sep)[0].strip(); break
                
            return Product(id=article, name=name, price=0, quantity=0, store_code=shop_code or "web", image_url=image, rating=0, is_adult=False, seo_code="")
        except:
            return None

    def _find_recursive(self, data, depth=0):
        if depth > 10: return None
        if isinstance(data, dict):
            if "id" in data and "name" in data: return data
            for v in data.values():
                r = self._find_recursive(v, depth + 1)
                if r: return r
        elif isinstance(data, list):
            for i in data:
                r = self._find_recursive(i, depth + 1)
                if r: return r
        return None

    def _extract_price(self, item: dict) -> float:
        price = item.get("price")
        if price:
            if isinstance(price, (int, float)): return price / 100 if price > 100000 else price
            if isinstance(price, str):
                try: return float(price.replace(",", ".")) / 100 if float(price.replace(",", ".")) > 100000 else float(price.replace(",", "."))
                except: pass
        return self._find_price_recursive(item)

    def _find_price_recursive(self, data, depth=0) -> float:
        if depth > 8: return 0
        if isinstance(data, dict):
            for key in ["price", "shopPrice", "currentPrice", "value", "amount"]:
                if key in data:
                    val = data[key]
                    if isinstance(val, (int, float)) and val > 0: return val / 100 if val > 100000 else val
            for v in data.values():
                r = self._find_price_recursive(v, depth + 1)
                if r: return r
        elif isinstance(data, list):
            for i in data:
                r = self._find_price_recursive(i, depth + 1)
                if r: return r
        return 0

    def _get_image_url(self, item: dict) -> str:
        gal = item.get("gallery", [])
        if gal and isinstance(gal, list) and len(gal) > 0:
            f = gal[0]
            if isinstance(f, dict): return f.get("url", "")
            return str(f)
        if "image" in item:
            img = item["image"]
            if isinstance(img, list) and img: return img[0] if isinstance(img[0], str) else ""
            if isinstance(img, str): return img
        return ""

    async def search_product_in_store(self, article: str, store_code: str) -> Optional[Product]:
        return await self.search_product(article, shop_code=store_code)

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
                "geo": {"typeName": "box", "leftTopPoint": bbox["leftTopPoint"], "rightBottomPoint": bbox["rightBottomPoint"]},
                "storeTypeListV2": ["MM", "GM", "DG", "MO", "ME", "MC", "DARKSTORE", "MM_MINI", "ZARYAD"]
            }
        }
        try:
            loop = asyncio.get_event_loop()
            resp = await loop.run_in_executor(None, lambda: self.scraper.post(self.STORES_URL, json=payload, headers=self.headers, timeout=15))
            if resp.status_code != 200: return []
            data = resp.json()
            raw = data.get("items", {}).get("items", [])
            stores = []
            for s in raw:
                if not s.get("isActive"): continue
                c = s.get("coordinates", {})
                slat, slon = c.get("latitude", 0), c.get("longitude", 0)
                dist = geodesic((lat, lon), (slat, slon)).km
                code = s.get("externalId", {}).get("storeCode", "")
                stores.append({"code": code, "name": f"Магнит #{code}", "latitude": slat, "longitude": slon, "distance": dist, "storeType": s.get("storeTypeV2", "MM")})
            stores.sort(key=lambda x: x["distance"])
            logger.info(f"Найдено {len(stores)} магазинов в радиусе {radius_km} км")
            return stores
        except Exception as e:
            logger.error(f"Ошибка поиска магазинов: {e}")
            return []

def get_address_from_coordinates(lat: float, lon: float) -> str:
    try:
        loc = geolocator.reverse(f"{lat}, {lon}", language="ru", exactly_one=True)
        if loc and loc.address: return ", ".join(loc.address.split(",")[0:3])
    except (GeocoderTimedOut, GeocoderServiceError): pass
    except Exception as e: logger.warning(f"⚠️ Ошибка адреса: {e}")
    return f"Координаты: {lat:.4f}, {lon:.4f}"

magnit_api = MagnitAPI()
