import cloudscraper
import asyncio
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class Product:
    """Информация о товаре"""
    id: str
    name: str
    price: float  # в рублях
    quantity: int
    store_code: str
    image_url: str
    rating: float
    is_adult: bool
    seo_code: str
    
    @property
    def in_stock(self) -> bool:
        return self.quantity > 0
    
    @property
    def url(self) -> str:
        return f"https://magnit.ru/catalog/{self.seo_code}/"

class MagnitAPI:
    """Парсер API Магнита"""
    
    SEARCH_URL = "https://magnit.ru/webgate/v2/goods/search"
    
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
        store_code: str = "764557",
        store_type: str = "express"
    ) -> Optional[Product]:
        """
        Поиск товара по артикулу
        
        Args:
            article: Артикул товара
            store_code: Код магазина (по умолчанию 764557)
            store_type: Тип магазина (express, supermarket, etc.)
        
        Returns:
            Product object или None
        """
        payload = {
            "term": article,
            "storeCode": store_code,
            "storeType": store_type,
            "catalogType": "3",
            "includeAdultGoods": True,
            "pagination": {
                "offset": 0,
                "limit": 36
            },
            "sort": {
                "order": "desc",
                "type": "popularity"
            }
        }
        
        try:
            response = self.scraper.post(
                self.SEARCH_URL,
                json=payload,
                headers=self.headers,
                timeout=15
            )
            
            if response.status_code != 200:
                logger.error(f"Ошибка API: {response.status_code}")
                return None
            
            data = response.json()
            
            # Проверяем что это поиск по артикулу
            if not data.get("isSearchByArticle"):
                logger.warning("Поиск не по артикулу")
                return None
            
            items = data.get("items", [])
            if not items:
                logger.info(f"Товар {article} не найден")
                return None
            
            # Берём первый товар
            item = items[0]
            
            # Извлекаем данные
            product = Product(
                id=item.get("id") or item.get("productId"),
                name=item.get("name", "Без названия"),
                price=item.get("price", 0) / 100,  # Конвертируем копейки в рубли
                quantity=item.get("quantity", 0),
                store_code=item.get("storeCode", store_code),
                image_url=self._get_image_url(item),
                rating=item.get("ratings", {}).get("rating", 0),
                is_adult=item.get("isForAdults", False),
                seo_code=item.get("seoCode", "")
            )
            
            logger.info(f"Найден товар: {product.name} ({product.price}₽, в наличии: {product.quantity})")
            return product
            
        except Exception as e:
            logger.error(f"Ошибка поиска товара {article}: {e}")
            return None
    
    def _get_image_url(self, item: dict) -> str:
        """Извлекает URL картинки товара"""
        gallery = item.get("gallery", [])
        if gallery and len(gallery) > 0:
            return gallery[0].get("url", "")
        return ""
    
    async def search_multiple_stores(
        self, 
        article: str, 
        store_codes: List[str],
        store_type: str = "express"
    ) -> List[Product]:
        """
        Поиск товара в нескольких магазинах
        
        Args:
            article: Артикул товара
            store_codes: Список кодов магазинов
            store_type: Тип магазина
        
        Returns:
            Список найденных товаров
        """
        tasks = [
            self.search_product(article, store_code, store_type)
            for store_code in store_codes
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Фильтруем успешные результаты
        products = []
        for result in results:
            if isinstance(result, Product):
                products.append(result)
            elif isinstance(result, Exception):
                logger.error(f"Ошибка при поиске: {result}")
        
        return products

# Глобальный экземпляр API
magnit_api = MagnitAPI()

async def get_stores_nearby(self, lat: float, lon: float, radius_km: int = 10) -> List[dict]:
    """
    Получение списка магазинов рядом с координатами
    
    Args:
        lat: Широта
        lon: Долгота
        radius_km: Радиус поиска в км
    
    Returns:
        Список магазинов
    """
    # API endpoint для поиска магазинов (предположительный)
    # Если не работает - нужно будет найти реальный через DevTools
    url = "https://magnit.ru/webgate/v2/stores/search"
    
    payload = {
        "lat": lat,
        "lon": lon,
        "radius": radius_km * 1000,  # конвертируем в метры
        "limit": 100
    }
    
    try:
        response = self.scraper.post(url, json=payload, headers=self.headers, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            stores = data.get("stores", [])
            logger.info(f"Найдено {len(stores)} магазинов в радиусе {radius_km} км")
            return stores
        else:
            logger.error(f"Ошибка получения магазинов: {response.status_code}")
            return []
            
    except Exception as e:
        logger.error(f"Ошибка поиска магазинов: {e}")
        return []

async def check_product_in_multiple_stores(
    self, 
    article: str, 
    stores: List[dict]
) -> List[dict]:
    """
    Проверка наличия товара в нескольких магазинах
    
    Args:
        article: Артикул товара
        stores: Список магазинов
    
    Returns:
        Список результатов с ценами и наличием
    """
    results = []
    
    # Проверяем товар в каждом магазине
    for store in stores:
        store_code = store.get("code") or store.get("storeCode")
        if not store_code:
            continue
        
        # Ищем товар в этом магазине
        product = await self.search_product(article, store_code)
        
        if product:
            results.append({
                "store_code": store_code,
                "store_name": store.get("name", "Неизвестно"),
                "store_address": store.get("address", ""),
                "distance": store.get("distance", 0),
                "price": product.price,
                "quantity": product.quantity,
                "in_stock": product.in_stock,
                "url": product.url
            })
        
        # Небольшая задержка чтобы не спамить API
        await asyncio.sleep(0.2)
    
    # Сортируем по цене (только те что в наличии)
    in_stock = [r for r in results if r["in_stock"]]
    in_stock.sort(key=lambda x: x["price"])
    
    # Добавляем те что не в наличии в конец
    not_in_stock = [r for r in results if not r["in_stock"]]
    
    return in_stock + not_in_stock

# Добавляем методы в класс
MagnitAPI.get_stores_nearby = get_stores_nearby
MagnitAPI.check_product_in_multiple_stores = check_product_in_multiple_stores
