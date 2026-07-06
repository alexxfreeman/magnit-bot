import asyncio
import logging
from magnit_api import get_address_from_coordinates
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, 
    FSInputFile, 
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    ReplyKeyboardRemove
)
from config import config
from database import init_db, add_to_history
from magnit_api import magnit_api
import tempfile
import os

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()
router = Router()

# --- Состояния для FSM ---
class ScanStates(StatesGroup):
    waiting_for_location = State()  # Ожидаем геолокацию

# Хранилище последних артикулов пользователей
user_last_article = {}

# --- Список магазинов по умолчанию (если API магазинов не работает) ---
# Замените на реальные коды магазинов вашего города
DEFAULT_STORES = [
    {"code": "764557", "name": "Магнит", "address": "ул. Комсомольская, д 5"},
    {"code": "764558", "name": "Магнит", "address": "ул. Ленина, д 10"},
    {"code": "764559", "name": "Магнит", "address": "пр. Октября, д 15"},
    {"code": "764560", "name": "Магнит", "address": "ул. Мира, д 22"},
    {"code": "764561", "name": "Магнит", "address": "ул. Советская, д 8"},
    {"code": "764562", "name": "Магнит", "address": "ул. Кирова, д 3"},
    {"code": "764563", "name": "Магнит", "address": "пр. Авиаторов, д 12"},
    {"code": "764564", "name": "Магнит", "address": "ул. Волкова, д 7"},
    {"code": "764565", "name": "Магнит", "address": "ул. Чкалова, д 18"},
    {"code": "764566", "name": "Магнит", "address": "ул. Республиканская, д 2"},
    {"code": "764567", "name": "Магнит", "address": "ул. Свободы, д 14"},
    {"code": "764568", "name": "Магнит", "address": "пр. Толбухина, д 9"},
]


@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 <b>Привет! Я бот для проверки товаров в Магните.</b>\n\n"
        "Просто отправь мне <b>артикул товара</b> (цифрами), и я проверю:\n"
        "• Наличие в магазинах\n"
        "• Цену\n"
        "• Рейтинг\n\n"
        "Пример: <code>1199991965</code>\n\n"
        "Используй <b>/check_all</b> для проверки во всех магазинах.",
        parse_mode="HTML"
    )


@router.message(Command("check_all"))
async def cmd_check_all(message: Message, state: FSMContext):
    """Проверка товара во всех магазинах города"""
    user_id = message.from_user.id
    
    # Проверяем, есть ли последний артикул
    if user_id not in user_last_article:
        await message.answer(
            "❌ Сначала отправь мне артикул товара для проверки.\n\n"
            "Пример: <code>1199991965</code>",
            parse_mode="HTML"
        )
        return
    
    article = user_last_article[user_id]
    
    # Сохраняем артикул в состояние
    await state.update_data(article=article)
    
    # Просим геолокацию
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Отправить геолокацию", request_location=True)]],
        resize_keyboard=True
    )
    
    await message.answer(
        "📍 Отправь мне свою геолокацию (нажми на кнопку ниже),\n"
        "чтобы я нашел магазины рядом с тобой.\n\n"
        "Или отправь /cancel чтобы отменить.",
        reply_markup=kb
    )
    
    # Переходим в состояние ожидания геолокации
    await state.set_state(ScanStates.waiting_for_location)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Отмена текущего действия"""
    await state.clear()
    await message.answer(
        "❌ Действие отменено.",
        reply_markup=ReplyKeyboardRemove()
    )


@router.message(ScanStates.waiting_for_location, F.location)
async def process_location(message: Message, state: FSMContext):
    """Обработка полученной геолокации"""
    lat = message.location.latitude
    lon = message.location.longitude
    
    # Получаем артикул из состояния
    data = await state.get_data()
    article = data.get("article")
    
    # Убираем клавиатуру
    await message.answer(
        f"🔍 Ищу магазины рядом с тобой...\n"
        f"📍 Координаты: {lat:.4f}, {lon:.4f}\n"
        f"📦 Артикул: {article}",
        reply_markup=ReplyKeyboardRemove()
    )
    
    # Очищаем состояние
    await state.clear()
    
    # Получаем магазины через API (радиус 10 км)
    stores = await magnit_api.get_stores_nearby(lat, lon, radius_km=10)
    
    if not stores:
        await message.answer("❌ Не удалось найти магазины рядом с тобой.")
        return
    
    await message.answer(f"🏪 Найдено {len(stores)} магазинов. Проверяю наличие товара...")
    
    # Проверяем товар в каждом магазине (максимум 30 магазинов)
    results = []
    stores_to_check = stores[:30]  # Ограничиваем чтобы не спамить API
    
    for i, store in enumerate(stores_to_check, 1):
        store_code = store["code"]
        
        try:
            product = await magnit_api.search_product(article, store_code)
            
            if product:
                # Получаем адрес через геокодер
                address = get_address_from_coordinates(
                    store["latitude"], 
                    store["longitude"]
                )
                
                results.append({
                    "store_code": store_code,
                    "store_name": f"Магнит #{store_code}",
                    "store_address": address,
                    "distance": store["distance"],
                    "price": product.price,
                    "quantity": product.quantity,
                    "in_stock": product.in_stock,
                    "url": product.url
                })
        except Exception as e:
            logger.error(f"Ошибка проверки магазина {store_code}: {e}")
            continue
        
        # Обновляем прогресс каждые 5 магазинов
        if i % 5 == 0:
            await message.answer(f"⏳ Проверено {i}/{len(stores_to_check)} магазинов...")
        
        # Задержка чтобы не спамить API
        await asyncio.sleep(0.3)
    
    if not results:
        await message.answer("❌ Товар не найден ни в одном магазине.")
        return
    
    # Сортируем: сначала в наличии по цене, потом без наличия
    in_stock = sorted([r for r in results if r["in_stock"]], key=lambda x: x["price"])
    not_in_stock = [r for r in results if not r["in_stock"]]
    sorted_results = in_stock + not_in_stock
    
    # Берем топ-10
    top_10 = sorted_results[:10]
    
    # Формируем ответ
    text = f"📊 <b>Результаты проверки артикула {article}</b>\n\n"
    text += f"🏪 Проверено магазинов: {len(results)}\n"
    text += f"✅ В наличии: {len(in_stock)}\n\n"
    
    for i, result in enumerate(top_10, 1):
        if result["in_stock"]:
            text += f"{i}. 🏪 <b>{result['store_name']}</b>\n"
            text += f"   💰 Цена: <b>{result['price']:.2f} ₽</b>\n"
            text += f"   📦 В наличии: {result['quantity']} шт.\n"
            text += f"   📍 {result['store_address']}\n"
            text += f"   📏 Расстояние: {result['distance']:.1f} км\n"
            text += f"   🔗 <a href='{result['url']}'>Открыть</a>\n\n"
        else:
            text += f"{i}. ❌ <b>{result['store_name']}</b> - нет в наличии\n"
            text += f"    📍 {result['store_address']}\n"
            text += f"    📏 {result['distance']:.1f} км\n\n"
    
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


@router.message(ScanStates.waiting_for_location, F.text == "/cancel")
async def cancel_location(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "❌ Отменено.",
        reply_markup=ReplyKeyboardRemove()
    )


@router.message(ScanStates.waiting_for_location, F.text)
async def wrong_input_during_location(message: Message):
    """Если пользователь отправил текст вместо геолокации"""
    await message.answer(
        "⚠️ Пожалуйста, отправь геолокацию через кнопку ниже.\n"
        "Или /cancel чтобы отменить.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📍 Отправить геолокацию", request_location=True)]],
            resize_keyboard=True
        )
    )


@router.message(F.text)
async def handle_article(message: Message):
    """Обработка артикула"""
    article = message.text.strip()
    
    # Простая валидация
    if not article.isdigit():
        await message.answer("❌ Пожалуйста, отправьте артикул, состоящий только из цифр.")
        return
    
    # Сохраняем артикул для пользователя
    user_last_article[message.from_user.id] = article
    
    await message.answer("🔍 Ищу товар в базе Магнита...")
    
    # Ищем товар
    product = await magnit_api.search_product(article)
    
    if not product:
        await message.answer(
            f"❌ Товар с артикулом <code>{article}</code> не найден.",
            parse_mode="HTML"
        )
        return
    
    # Формируем ответ
    stock_status = "✅ В наличии" if product.in_stock else "❌ Нет в наличии"
    
    text = (
        f"📦 <b>{product.name}</b>\n\n"
        f"💰 <b>Цена:</b> {product.price:.2f} ₽\n"
        f" <b>Статус:</b> {stock_status}\n"
        f"📦 <b>Количество:</b> {product.quantity} шт.\n"
        f"⭐ <b>Рейтинг:</b> {product.rating}/5\n"
        f"🏪 <b>Магазин:</b> {product.store_code}\n\n"
        f"🔗 <a href='{product.url}'>Открыть на сайте</a>"
    )
    
    # Отправляем с картинкой (если есть)
    if product.image_url:
        await message.answer_photo(
            photo=product.image_url,
            caption=text,
            parse_mode="HTML"
        )
    else:
        await message.answer(text, parse_mode="HTML")
    
    # Сохраняем в историю
    await add_to_history(
        user_id=message.from_user.id,
        article=article,
        title=product.name,
        price=f"{product.price:.2f}",
        in_stock=product.in_stock
    )
    
    # Предложение проверить в других магазинах
    await message.answer(
        "💡 Используй команду <b>/check_all</b> для проверки во всех магазинах.",
        parse_mode="HTML"
    )


async def main():
    await init_db()
    dp.include_router(router)
    logging.info("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен.")
