import asyncio
import logging
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, FSInputFile
from config import config
from database import init_db, add_to_history
from magnit_api import magnit_api
from report_generator import generate_html_report
import tempfile
import os

logging.basicConfig(level=logging.INFO)
bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()
router = Router()

# Состояния для FSM
class ScanStates(StatesGroup):
    waiting_for_article = State()

# Хранилище последних артикулов пользователей
user_last_article = {}

@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        " <b>Привет! Я бот для проверки товаров в Магните.</b>\n\n"
        "Просто отправь мне <b>артикул товара</b> (цифрами), и я проверю:\n"
        "• Наличие в магазинах\n"
        "• Цену\n"
        "• Рейтинг\n\n"
        "Пример: <code>1199991965</code>\n\n"
        "Используй <b>/check_all</b> для проверки во всех магазинах.",
        parse_mode="HTML"
    )

@router.message(Command("check_all"))
async def cmd_check_all(message: Message):
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
    
    # Запрашиваем геолокацию
    await message.answer(
        "📍 Отправь мне свою геолокацию (кнопка со скрепкой → Геопозиция),\n"
        "чтобы я нашел магазины рядом с тобой.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📍 Отправить геолокацию", request_location=True)]],
            resize_keyboard=True
        )
    )
    
    # Ждем геолокацию
    try:
        location_msg = await bot.wait_for(
            "message",
            filter=lambda m: m.from_user.id == user_id and m.location,
            timeout=60
        )
        
        lat = location_msg.location.latitude
        lon = location_msg.longitude
        
        await message.answer(
            f"🔍 Ищу магазины рядом с тобой...\n"
            f" Координаты: {lat:.4f}, {lon:.4f}",
            reply_markup=ReplyKeyboardRemove()
        )
        
        # Получаем список магазинов
        stores = await magnit_api.get_stores_nearby(lat, lon, radius_km=15)
        
        if not stores:
            await message.answer("❌ Не удалось найти магазины рядом с тобой.")
            return
        
        await message.answer(f"🏪 Найдено {len(stores)} магазинов. Проверяю наличие товара...")
        
        # Проверяем товар во всех магазинах
        results = await magnit_api.check_product_in_multiple_stores(article, stores)
        
        if not results:
            await message.answer("❌ Товар не найден ни в одном магазине.")
            return
        
        # Формируем ответ с топ-10
        top_10 = results[:10]
        
        text = f"📊 <b>Результаты проверки артикула {article}</b>\n\n"
        text += f"🏪 Проверено магазинов: {len(results)}\n"
        text += f"✅ В наличии: {sum(1 for r in results if r['in_stock'])}\n\n"
        
        for i, result in enumerate(top_10, 1):
            if result["in_stock"]:
                text += f"{i}. 🏪 <b>{result['store_name']}</b>\n"
                text += f"   💰 Цена: <b>{result['price']:.2f} ₽</b>\n"
                text += f"   📦 В наличии: {result['quantity']} шт.\n"
                text += f"    Адрес: {result['store_address']}\n"
                if result['distance'] > 0:
                    text += f"   📏 Расстояние: {result['distance']:.1f} км\n"
                text += f"   🔗 <a href='{result['url']}'>Открыть</a>\n\n"
            else:
                text += f"{i}. ❌ {result['store_name']} - нет в наличии\n\n"
        
        await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)
        
    except asyncio.TimeoutError:
        await message.answer(
            " Время вышло. Попробуй еще раз с командой /check_all",
            reply_markup=ReplyKeyboardRemove()
        )
    except Exception as e:
        logger.error(f"Ошибка в /check_all: {e}")
        await message.answer(f"❌ Произошла ошибка: {str(e)}")

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
        f"📊 <b>Статус:</b> {stock_status}\n"
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
        " Используй команду <b>/check_all</b> для проверки во всех магазинах.",
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
