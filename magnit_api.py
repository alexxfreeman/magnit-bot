import cloudscraper
import asyncio
import logging
import math
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from geopy.distance import geodesic
from geopy.geocoders import Nominatim

logger = logging.getLogger(__name__)

geolocator = Nominatim(user_agent="magnit_bot_v1")


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
    store_type: str = "express"
    
    @property
    def in_stock(self) -> bool:
        return self.quantity > 0
    
    @property
    def url(self) -> str:
        # Универсальная ссылка на поиск по артикулу — работает для любого города
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
        store_code: str = "764557",
        store_type: str = "express"
    ) -> Optional[Product]:
        payload = {
            "term": article,
            "storeCode": store_code,
            "storeType": store_type,
            "catalogType": "3",
            "includeAdultGoods": True,
            "pagination": {"offset": 0, "limit": 36},
            "sort": {"order": "desc", "type": "popularity"}
        }
        
        try:
            response = self.scraper.post(
                self.SEARCH_URL, json=payload, headers=self.headers, timeout=15
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
                store_type=store_type
            )
        except Exception as e:
            logger.error(f"Ошибка поиска товара {article}: {e}")
            return None
    
    def _get_image_url(self, item: dict) -> str:
        gallery = item.get("gallery", [])
        return gallery[0].get("url", "") if gallery else ""
    
      
        results = {}
        for type_name, store_type in types.items():
            product = await self.search_product(article, store_code, store_type)
            results[type_name] = product
        
        return results
    
    def calculate_bounding_box(self, lat: float, lon: float, radius_km: float) -> dict:
        lat_delta = radius_km / 111.0
        lon_delta = radius_km / (111.0 * math.cos(math.radians(lat)))
        
        return {
            "leftTopPoint": {
                "latitude": lat + lat_delta,
                "longitude": lon - lon_delta
            },
            "rightBottomPoint": {
                "latitude": lat - lat_delta,
                "longitude": lon + lon_delta
            }
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
            
            if response.status_code == 200:
                data = response.json()
                stores_raw = data.get("items", {}).get("items", [])
                
                stores = []
                for store in stores_raw:
                    if not store.get("isActive", False):
                        continue
                    
                    store_coords = store.get("coordinates", {})
                    store_lat = store_coords.get("latitude", 0)
                    store_lon = store_coords.get("longitude", 0)
                    
                    distance = geodesic((lat, lon), (store_lat, store_lon)).km
                    
                    store_code = store.get("externalId", {}).get("storeCode", "")
                    store_type = store.get("storeTypeV2", "MM")
                    
                    stores.append({
                        "code": store_code,
                        "name": f"Магнит #{store_code}",
                        "address": "",
                        "latitude": store_lat,
                        "longitude": store_lon,
                        "distance": distance,
                        "storeType": store_type
                    })
                
                stores.sort(key=lambda x: x["distance"])
                logger.info(f"Найдено {len(stores)} магазинов в радиусе {radius_km} км")
                return stores
            else:
                logger.error(f"Ошибка получения магазинов: {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"Ошибка поиска магазинов: {e}")
            return []


def get_address_from_coordinates(lat: float, lon: float) -> str:
    try:
        location = geolocator.reverse(f"{lat}, {lon}", language="ru", timeout=5)
        if location and location.address:
            address = location.address.split(",")[0:3]
            return ", ".join(address)
    except Exception as e:
        logger.error(f"Ошибка получения адреса: {e}")
    return f"Координаты: {lat:.4f}, {lon:.4f}"


magnit_api = MagnitAPI()
