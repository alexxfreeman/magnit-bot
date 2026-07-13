import asyncio
import logging
import math
import re
from typing import List, Optional, Dict
from dataclasses import dataclass
from playwright.async_api import async_playwright
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
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9",
        }

    async def init_browser(self):
        """Инициализация браузера (вызывается один раз при старте)"""
        if self.browser is None:
            playwright = await async_playwright().start()
            self.browser = await playwright.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--disable-gpu'
                ]
            )
            logger.info("✅ Браузер инициализирован")

    async def search_product(self, article: str, shop_code: str = None) -> Optional[Product]:
        """Поиск товара через браузер"""
        await self.init_browser()
        
        logger.info(f"🔍 Поиск товара {article} (shop_code={shop_code})")

        # Формируем URL
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
            
            # Загружаем страницу и ждём
            await page.goto(url, wait_until='networkidle', timeout=15000)
            
            # Ждём загрузки контента (максимум 5 секунд)
            try:
                await page.wait_for_selector('.product-card, [data-testid="product"], .product-info', timeout=5000)
            except:
                pass  # Продолжаем даже если селектор не найден
            
            # Извлекаем данные
            product = await self._extract_product_data(page, article, shop_code)
            
            await context.close()
            
            if product:
                logger.info(f"✅ Найдено: {product.name[:50]}... ({product.price}₽)")
            
            return product
            
        except Exception as e:
            logger.error(f"❌ Ошибка при парсинге {article}: {e}")
            return None

    async def _extract_product_data(self, page, article: str, shop_code: str = None) -> Optional[Product]:
        """Извлекает данные о товаре из страницы"""
        try:
            # Пробуем извлечь данные из JSON-LD (schema.org)
            json_ld = await page.evaluate('''() => {
                const script = document.querySelector('script[type="application/ld+json"]');
                if (script) {
                    try {
                        return JSON.parse(script.textContent);
                    } catch(e) {
                        return null;
                    }
                }
                return null;
            }''')
            
            if json_ld:
                name = json_ld.get('name', '')
                offers = json_ld.get('offers', {})
                price = 0
                if isinstance(offers, dict):
                    price = float(offers.get('price', 0))
                elif isinstance(offers, list) and offers:
                    price = float(offers[0].get('price', 0))
                
                image = json_ld.get('image', '')
                if isinstance(image, list) and image:
                    image = image[0]
                
                return Product(
                    id=article,
                    name=name,
                    price=price,
                    quantity=1 if price > 0 else 0,
                    store_code=shop_code or "web",
                    image_url=image if isinstance(image, str) else "",
                    rating=float(json_ld.get('aggregateRating', {}).get('ratingValue', 0) or 0),
                    is_adult=False,
                    seo_code=""
                )
            
            # Fallback: извлекаем из meta-тегов
            meta_title = await page.evaluate('''() => {
                const meta = document.querySelector('meta[property="og:title"]');
                return meta ? meta.content : '';
            }''')
            
            meta_image = await page.evaluate('''() => {
                const meta = document.querySelector('meta[property="og:image"]');
                return meta ? meta.content : '';
            }''')
            
            # Ищем цену в тексте страницы
            price_text = await page.evaluate('''() => {
                const priceElements = document.querySelectorAll('[class*="price"], [data-testid*="price"]');
                for (const el of priceElements) {
                    const text = el.textContent;
                    const match = text.match(/([\\d\\s]+)\\s*₽/);
                    if (match) {
                        return match[1].replace(/\\s/g, '');
                    }
                }
                return '0';
            }''')
            
            try:
                price = float(price_text.replace(' ', '').replace(',', '.'))
            except:
                price = 0
            
            # Очищаем название
            name = meta_title
            for sep in [' – ', ' - ', ' | ', '—']:
                if sep in name:
                    name = name.split(sep)[0].strip()
                    break
            
            return Product(
                id=article,
                name=name,
                price=price,
                quantity=1 if price > 0 else 0,
                store_code=shop_code or "web",
                image_url=meta_image,
                rating=0,
                is_adult=False,
                seo_code=""
            )
            
        except Exception as e:
            logger.error(f"❌ Ошибка извлечения данных: {e}")
            return None

    async def search_product_in_store(self, article: str, store_code: str) -> Optional[Product]:
        """Поиск товара в конкретном магазине"""
        return await self.search_product(article, shop_code=store_code)

    def calculate_bounding_box(self, lat: float, lon: float, radius_km: float) -> dict:
        lat_delta = radius_km / 111.0
        lon_delta = radius_km / (111.0 * math.cos(math.radians(lat)))
        return {
            "leftTopPoint": {"latitude": lat + lat_delta, "longitude": lon - lon_delta},
            "rightBottomPoint": {"latitude": lat - lat_delta, "longitude": lon + lon_delta}
        }

    async def get_stores_nearby(self, lat: float, lon: float, radius_km: float = 10) -> List[dict]:
        """Получение списка магазинов рядом (через API, так как это быстро)"""
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
        
        import cloudscraper
        scraper = cloudscraper.create_scraper()
        
        try:
            resp = scraper.post(self.STORES_URL, json=payload, headers=self.headers, timeout=15)
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
        logger.warning(f"️ Ошибка адреса: {e}")
    return f"Координаты: {lat:.4f}, {lon:.4f}"


magnit_api = MagnitAPI()
