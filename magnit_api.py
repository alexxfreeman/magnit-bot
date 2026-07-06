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