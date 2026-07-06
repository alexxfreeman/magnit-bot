import asyncio
import logging
import re
import aiosqlite
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)

from config import config
from database import init_db, add_to_history
from magnit_api import magnit_api, get_address_from_coordinates

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()
router = Router()

class ScanStates(StatesGroup):
    waiting_for_location = State()

user_last_article = {}


def extract_article_from_text(text: str) -> Optional[str]:
    text = text.strip()
    
    if text.isdigit() and len(text) >= 10:
        return text
    
    patterns = [
        r'(?:product|catalog|goods)[/\w-]*(\d{10,})',
        r'magnit\.ru[/\w-]*(\d{10,})',
        r'(\d{10,})'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            article = match.group(1)
            if article.isdigit():
                return article
    
    return None


@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 <b>Привет! Я бот для проверки товаров в Магните.</b>\n\n"
        "Отправь мне <b>артикул товара</b> или <b>ссылку</b> из приложения Магнит,\n"
        "и я проверю наличие и цену.\n\n"
        "Примеры:\n"
        "• Артикул: <code>1199991965</code>\n"
        "• Ссылка из приложения Магнит",
        parse_mode="HTML"
    )


@router.message(Command("check_all"))
async def cmd_check_all(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    if user_id not in user_last_article:
        await message.answer(
            "❌ Сначала отправь мне артикул товара для проверки.\n\n"
            "Пример: <code>1199991965</code>",
            parse_mode="HTML"
        )
        return
    
    article = user_last_article[user_id]
    await state.update_data(article=article)
    
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=" Отправить геолокацию", request_location=True)]],
        resize_keyboard=True
    )
    
    await message.answer(
        "📍 Отправь мне свою геолокацию (нажми на кнопку ниже),\n"
        "чтобы я нашел магазины рядом с тобой.\n\n"
        "Или отправь /cancel чтобы отменить.",
        reply_markup=kb
    )
    
    await state.set_state(ScanStates.waiting_for_location)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено.", reply_markup=ReplyKeyboardRemove())


@router.message(ScanStates.waiting_for_location, F.location)
async def process_location(message: Message, state: FSMContext):
    lat = message.location.latitude
    lon = message.location.longitude
    
    data = await state.get_data()
    article = data.get("article")
    
    await message.answer(
        f"🔍 Ищу магазины рядом с тобой...\n"
        f"📍 Координаты: {lat:.4f}, {lon:.4f}\n"
        f"📦 Артикул: {article}",
        reply_markup=ReplyKeyboardRemove()
    )
    
    await state.clear()
    
    # Получаем магазины (радиус 15 км)
    stores = await magnit_api.get_stores_nearby(lat, lon, radius_km=15)
    
    if not stores:
        await message.answer("❌ Не удалось найти магазины рядом с тобой.")
        return
    
    # Ограничиваем 50 магазинами
    stores_to_check = stores[:50]
    
    await message.answer(f"🏪 Найдено {len(stores)} магазинов. Проверяю наличие товара в первых {len(stores_to_check)}...")
    
    results = []
    checked_count = 0
    
    for i, store in enumerate(stores_to_check, 1):
        store_code = store["code"]
        
        try:
            product = await magnit_api.search_product(article, store_code)
            checked_count += 1
            
            if product:
                # Получаем адрес только для товаров в наличии (экономим время)
                address = ""
                if product.in_stock:
                    address = get_address_from_coordinates(
                        store["latitude"], store["longitude"]
                    )
                
                results.append({
                    "store_code": store_code,
                    "store_name": f"Магнит #{store_code}",
                    "store_address": address if address else f"~{store['distance']:.1f} км от вас",
                    "distance": store["distance"],
                    "price": product.price,
                    "quantity": product.quantity,
                    "in_stock": product.in_stock,
                    "url": product.url,
                    "storeType": store.get("storeType", "MM")
                })
        except Exception as e:
            logger.error(f"Ошибка проверки магазина {store_code}: {e}")
            continue
        
        if i % 10 == 0:
            await message.answer(f"⏳ Проверено {i}/{len(stores_to_check)} магазинов...")
        
        await asyncio.sleep(0.15)
    
    if not results:
        await message.answer("❌ Товар не найден ни в одном магазине.")
        return
    
    # Сортируем
    in_stock = sorted([r for r in results if r["in_stock"]], key=lambda x: x["price"])
    not_in_stock = [r for r in results if not r["in_stock"]]
    sorted_results = in_stock + not_in_stock
    
    top_10 = sorted_results[:10]
    
    # Формируем ответ
    text = f"📊 <b>Результаты проверки артикула {article}</b>\n\n"
    text += f"🏪 Запрошено магазинов: {len(stores_to_check)}\n"
    text += f"🔍 Проверено (товар найден): {checked_count}\n"
    text += f"✅ В наличии в <b>{len(in_stock)}</b> магазинах из {checked_count}\n\n"
    
    if len(in_stock) > 0:
        text += f"<b>Топ-{min(10, len(in_stock))} по цене:</b>\n\n"
    
    for i, result in enumerate(top_10, 1):
        if result["in_stock"]:
            text += f"{i}. 🏪 <b>{result['store_name']}</b>\n"
            text += f"   💰 Цена: <b>{result['price']:.2f} ₽</b>\n"
            text += f"   📦 В наличии: {result['quantity']} шт.\n"
            text += f"   📍 {result['store_address']}\n"
            text += f"   📏 Расстояние: {result['distance']:.1f} км\n"
            text += f"   🔗 <a href='{result['url']}'>Открыть в Магните</a>\n\n"
        else:
            text += f"{i}. ❌ <b>{result['store_name']}</b> - нет в наличии\n"
            text += f"   📏 {result['distance']:.1f} км\n\n"
    
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Новый поиск", callback_data="new_search")],
            [InlineKeyboardButton(text="📊 Проверить другой товар", callback_data="check_all_other")]
        ]
    )
    
    await message.answer("💡 Что хотите сделать дальше?", reply_markup=keyboard)


@router.message(ScanStates.waiting_for_location, F.text == "/cancel")
async def cancel_location(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Отменено.", reply_markup=ReplyKeyboardRemove())


@router.message(ScanStates.waiting_for_location, F.text)
async def wrong_input_during_location(message: Message):
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
    raw_text = message.text.strip()
    
    article = extract_article_from_text(raw_text)
    
    if not article:
        await message.answer(
            "❌ Не удалось найти артикул. Отправьте:\n"
            "• Артикул: <code>1199991965</code>\n"
            "• Или ссылку из приложения Магнит",
            parse_mode="HTML"
        )
        return
    
    user_last_article[message.from_user.id] = article
    
    await message.answer("🔍 Ищу товар в базе Магнита...")
    
    product = await magnit_api.search_product(article)
    
    if not product:
        await message.answer(
            f"❌ Товар с артикулом <code>{article}</code> не найден.\n\n"
            "Возможно, товар недоступен в вашем регионе или снят с продажи.",
            parse_mode="HTML"
        )
        return
    
    stock_status = "✅ В наличии" if product.in_stock else "❌ Нет в наличии"
    
    text = (
        f"📦 <b>{product.name}</b>\n\n"
        f"💰 <b>Цена:</b> {product.price:.2f} ₽\n"
        f"📊 <b>Статус:</b> {stock_status}\n"
        f"📦 <b>Количество:</b> {product.quantity} шт.\n"
        f"⭐ <b>Рейтинг:</b> {product.rating}/5\n"
        f"🏪 <b>Магазин:</b> {product.store_code}\n\n"
        f"🔗 <a href='{product.url}'>Открыть в Магните</a>"
    )
    
    if product.image_url:
        await message.answer_photo(
            photo=product.image_url,
            caption=text,
            parse_mode="HTML"
        )
    else:
        await message.answer(text, parse_mode="HTML")
    
    await add_to_history(
        user_id=message.from_user.id,
        article=article,
        title=product.name,
        price=f"{product.price:.2f}",
        in_stock=product.in_stock
    )
    
    # Две разные кнопки с разной логикой
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=" Проверить во всех магазинах", callback_data="check_all")],
            [InlineKeyboardButton(text=" Новый поиск", callback_data="new_search")]
        ]
    )
    
    await message.answer(
        "💡 Что хотите сделать дальше?",
        reply_markup=keyboard
    )

@router.callback_query(F.data == "new_search")
async def callback_new_search(callback_query: CallbackQuery):
    await callback_query.message.answer(
        "🔍 Отправьте артикул товара или ссылку:",
        reply_markup=ReplyKeyboardRemove()
    )
    await callback_query.answer()


@router.callback_query(F.data == "check_all")
async def callback_check_all(callback_query: CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    
    if user_id not in user_last_article:
        await callback_query.message.answer("❌ Сначала найдите товар.")
        await callback_query.answer()
        return
    
    article = user_last_article[user_id]
    await state.update_data(article=article)
    
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Отправить геолокацию", request_location=True)]],
        resize_keyboard=True
    )
    
    await callback_query.message.answer(
        "📍 Отправь геолокацию для проверки во всех магазинах:",
        reply_markup=kb
    )
    await state.set_state(ScanStates.waiting_for_location)
    await callback_query.answer()


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
