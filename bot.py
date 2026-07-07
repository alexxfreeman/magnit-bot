import asyncio
import logging
import re
from typing import Optional, Tuple
from urllib.parse import urlparse, parse_qs

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
from database import (
    init_db, add_to_history,
    get_user_stats, get_recent_logs, get_user_details, get_all_users
)
from magnit_api import magnit_api, get_address_from_coordinates
from middlewares import LoggingMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()
router = Router()

# ВАШ Telegram ID (узнать у @userinfobot)
ADMIN_ID = 516400446  # ← ЗАМЕНИТЕ НА СВОЙ ID


class ScanStates(StatesGroup):
    waiting_for_location = State()


user_last_article = {}


def extract_article_from_text(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    text = text.strip()
    shop_code = None
    catalog_type = None

    try:
        parsed = urlparse(text if '://' in text else f'https://{text}')
        params = parse_qs(parsed.query)
        if 'shopCode' in params: shop_code = params['shopCode'][0]
        if 'catalogType' in params: catalog_type = params['catalogType'][0]
        
        path_parts = parsed.path.strip('/').split('/')
        for part in path_parts:
            if part.isdigit() and len(part) >= 10:
                return part, shop_code, catalog_type
    except Exception:
        pass

    if text.isdigit() and len(text) >= 10:
        return text, None, None

    patterns = [
        r'(?:product|catalog|goods)[/\w-]*(\d{10,})',
        r'magnit\.ru[/\w-]*(\d{10,})',
        r'(\d{10,})'
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match and match.group(1).isdigit():
            return match.group(1), shop_code, catalog_type

    return None, None, None


# === КОМАНДЫ ===

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
            "❌ Сначала отправь мне артикул товара.\n"
            "Пример: <code>1199991965</code>",
            parse_mode="HTML"
        )
        return
    await state.update_data(article=user_last_article[user_id])
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Отправить геолокацию", request_location=True)]],
        resize_keyboard=True
    )
    await message.answer(
        "📍 Отправь геолокацию, чтобы я нашёл магазины рядом.\n"
        "Или /cancel чтобы отменить.",
        reply_markup=kb
    )
    await state.set_state(ScanStates.waiting_for_location)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено.", reply_markup=ReplyKeyboardRemove())


# === ОБРАБОТКА ГЕОЛОКАЦИИ ===

@router.message(ScanStates.waiting_for_location, F.location)
async def process_location(message: Message, state: FSMContext):
    lat = message.location.latitude
    lon = message.location.longitude
    data = await state.get_data()
    article = data.get("article")
    await state.clear()

    await message.answer(
        f"🔍 Ищу магазины рядом...\n"
        f"📍 Координаты: {lat:.4f}, {lon:.4f}\n"
        f"📦 Артикул: {article}",
        reply_markup=ReplyKeyboardRemove()
    )

    stores = await magnit_api.get_stores_nearby(lat, lon, radius_km=15)
    if not stores:
        await message.answer("❌ Не удалось найти магазины рядом с тобой.")
        return

    stores_to_check = stores[:50]
    # Текст теперь ТОЧНО совпадает с реальностью
    await message.answer(f"🏪 Найдено {len(stores)} магазинов. Проверяю наличие в {len(stores_to_check)} магазинах...")

    results = []
    checked_count = 0

    for i, store in enumerate(stores_to_check, 1):
        store_code = store["code"]
        try:
            # Теперь search_product проверяет ТОЛЬКО этот магазин
            product = await magnit_api.search_product(
    article, 
    shop_code=store_code,
    store_type=1,
    catalog_type=1
)
            checked_count += 1
            if product:
                address = ""
                if product.in_stock:
                    address = get_address_from_coordinates(store["latitude"], store["longitude"])
                results.append({
                    "store_code": store_code,
                    "store_name": f"Магнит #{store_code}",
                    "store_address": address if address else f"~{store['distance']:.1f} км",
                    "distance": store["distance"],
                    "price": product.price,
                    "quantity": product.quantity,
                    "in_stock": product.in_stock,
                    "url": product.url,
                })
        except Exception as e:
            logger.error(f"Ошибка магазина {store_code}: {e}")
            continue

        if i % 10 == 0:
            await message.answer(f"⏳ Проверено {i}/{len(stores_to_check)} магазинов...")
        await asyncio.sleep(0.1)  # Задержка только для защиты от бана, не для скорости

    if not results:
        await message.answer(" Товар не найден ни в одном магазине.")
        return

    in_stock = sorted([r for r in results if r["in_stock"]], key=lambda x: x["price"])
    not_in_stock = [r for r in results if not r["in_stock"]]
    sorted_results = in_stock + not_in_stock
    top_10 = sorted_results[:10]

    text = f"📊 <b>Результаты проверки артикула {article}</b>\n\n"
    text += f"🏪 Запрошено магазинов: {len(stores_to_check)}\n"
    text += f"🔍 Успешно проверено: {checked_count}\n"
    text += f"✅ В наличии в <b>{len(in_stock)}</b> магазинах\n\n"

    if in_stock:
        text += f"<b>Топ-{min(10, len(in_stock))} по цене:</b>\n\n"

    for i, result in enumerate(top_10, 1):
        if result["in_stock"]:
            text += f"{i}.  <b>{result['store_name']}</b>\n"
            text += f"   💰 Цена: <b>{result['price']:.2f} ₽</b>\n"
            text += f"   📦 В наличии: {result['quantity']} шт.\n"
            text += f"    {result['store_address']}\n"
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


@router.message(ScanStates.waiting_for_location, F.text)
async def wrong_input_during_location(message: Message):
    if message.text == "/cancel":
        return
    await message.answer(
        "⚠️ Пожалуйста, отправь геолокацию через кнопку ниже.\nИли /cancel чтобы отменить.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📍 Отправить геолокацию", request_location=True)]],
            resize_keyboard=True
        )
    )


# === ОБЫЧНЫЙ ПОИСК ТОВАРА ===

@router.message(F.text)
async def handle_article(message: Message):
    raw_text = message.text.strip()
    article, shop_code, catalog_type = extract_article_from_text(raw_text)

    if not article:
        await message.answer(
            "❌ Не удалось найти артикул. Отправьте:\n"
            "• Артикул: <code>1199991965</code>\n"
            "• Или ссылку из приложения Магнит",
            parse_mode="HTML"
        )
        return

    user_last_article[message.from_user.id] = article

    info_text = f" Ищу товар {article}"
    if shop_code:
        info_text += f" (магазин {shop_code})"
    info_text += "..."
    await message.answer(info_text)

   # Преобразуем в числа, если они есть
shop_code_int = int(shop_code) if shop_code and shop_code.isdigit() else None
catalog_type_int = int(catalog_type) if catalog_type and catalog_type.isdigit() else 1

product = await magnit_api.search_product(
    article,
    shop_code=shop_code,
    store_type=1,  # Фиксируем на 1 (магазин)
    catalog_type=catalog_type_int
)

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
        f"📋 <b>Каталог:</b> {product.catalog_type_name}\n"
        f"📊 <b>Статус:</b> {stock_status}\n"
        f"📦 <b>Количество:</b> {product.quantity} шт.\n"
        f"⭐ <b>Рейтинг:</b> {product.rating}/5\n\n"
        f"🔗 <a href='{product.url}'>Открыть в Магните</a>"
    )

    if product.image_url:
        await message.answer_photo(photo=product.image_url, caption=text, parse_mode="HTML")
    else:
        await message.answer(text, parse_mode="HTML")

    await add_to_history(
        user_id=message.from_user.id,
        article=article,
        title=product.name,
        price=f"{product.price:.2f}",
        in_stock=product.in_stock
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Проверить во всех магазинах", callback_data="check_all")],
            [InlineKeyboardButton(text="🔍 Новый поиск", callback_data="new_search")]
        ]
    )
    await message.answer("💡 Что хотите сделать дальше?", reply_markup=keyboard)


# === CALLBACK ОБРАБОТЧИКИ ===

@router.callback_query(F.data == "new_search")
async def callback_new_search(callback_query: CallbackQuery):
    await callback_query.message.answer("🔍 Отправьте артикул товара или ссылку:")
    await callback_query.answer()


@router.callback_query(F.data == "check_all")
async def callback_check_all(callback_query: CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    if user_id not in user_last_article:
        await callback_query.message.answer("❌ Сначала найдите товар.")
        await callback_query.answer()
        return
    await state.update_data(article=user_last_article[user_id])
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


@router.callback_query(F.data == "check_all_other")
async def callback_check_all_other(callback_query: CallbackQuery):
    await callback_query.message.answer(
        "🔍 Отправьте новый артикул, а затем нажмите «Проверить во всех магазинах»"
    )
    await callback_query.answer()


# === АДМИНСКИЕ КОМАНДЫ ===

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != ADMIN_ID: return
    stats = await get_user_stats()
    text = (
        f" <b>Статистика бота</b>\n\n"
        f"👥 Всего пользователей: <b>{stats['total_users']}</b>\n"
        f"🟢 Активных за 24ч: <b>{stats['active_24h']}</b>\n"
        f"🔍 Всего поисков: <b>{stats['total_searches']}</b>\n\n"
        f"<b>🏆 Топ-10 пользователей:</b>\n"
    )
    for i, user in enumerate(stats['top_users'], 1):
        username = f"@{user['username']}" if user['username'] else user['first_name']
        text += f"{i}. {username} — {user['searches']} поисков\n"
    await message.answer(text, parse_mode="HTML")


@router.message(Command("logs"))
async def cmd_logs(message: Message):
    if message.from_user.id != ADMIN_ID: return
    logs = await get_recent_logs(limit=20)
    if not logs:
        await message.answer("📭 Логов пока нет.")
        return
    text = " <b>Последние действия:</b>\n\n"
    for log in logs[:15]:
        username = f"@{log['username']}" if log['username'] else log['first_name']
        timestamp = log['timestamp'][:16]
        text += f"[{timestamp}] <b>{log['action']}</b> {username} (ID: {log['user_id']})\n"
        if log['details']:
            text += f"   └ {log['details'][:50]}\n"
    await message.answer(text, parse_mode="HTML")


@router.message(Command("user"))
async def cmd_user(message: Message):
    if message.from_user.id != ADMIN_ID: return
    try:
        user_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.answer("❌ Использование: <code>/user ID</code>", parse_mode="HTML")
        return
    user_data = await get_user_details(user_id)
    if not user_data:
        await message.answer(f"❌ Пользователь {user_id} не найден.")
        return
    user = user_data['user']
    username = f"@{user['username']}" if user['username'] else 'нет'
    text = (
        f" <b>Информация о пользователе</b>\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Имя: {user['first_name']} {user['last_name'] or ''}\n"
        f" Username: {username}\n"
        f"📅 Первый раз: {user['created_at'][:16]}\n"
        f" Последний раз: {user['last_seen'][:16] if user['last_seen'] else 'никогда'}\n\n"
    )
    if user_data['history']:
        text += "<b>🔍 Последние поиски:</b>\n"
        for item in user_data['history'][:5]:
            text += f"• {item['article']} — {item['title'][:30]} ({item['price']}₽)\n"
        text += "\n"
    if user_data['logs']:
        text += "<b>📋 Последние действия:</b>\n"
        for log in user_data['logs'][:5]:
            text += f"• [{log['timestamp'][:16]}] {log['action']}: {log['details'][:30]}\n"
    await message.answer(text, parse_mode="HTML")


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if message.from_user.id != ADMIN_ID: return
    broadcast_text = message.text.replace('/broadcast', '', 1).strip()
    if not broadcast_text:
        await message.answer("❌ Использование: <code>/broadcast ТЕКСТ</code>", parse_mode="HTML")
        return
    await message.answer("📨 Начинаю рассылку...")
    users = await get_all_users()
    sent = failed = 0
    for user_id in users:
        try:
            await bot.send_message(user_id, broadcast_text)
            sent += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            failed += 1
            logger.error(f"Не удалось отправить {user_id}: {e}")
    await message.answer(f"✅ Рассылка завершена!\n📨 Отправлено: {sent}\n❌ Ошибок: {failed}")


# === ЗАПУСК ===

async def main():
    await init_db()
    dp.message.middleware(LoggingMiddleware())
    dp.callback_query.middleware(LoggingMiddleware())
    dp.include_router(router)
    logging.info("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен.")
