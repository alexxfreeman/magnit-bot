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
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN, ADMIN_ID
from database import (
    init_db, add_to_history,
    get_user_stats, get_recent_logs, get_user_details, get_all_users
)
from magnit_api import magnit_api, get_address_from_coordinates
from middlewares import LoggingMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Чистая инициализация бота без прокси
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()
router = Router()

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
        for part in parsed.path.strip('/').split('/'):
            if part.isdigit() and len(part) >= 10: return part, shop_code, catalog_type
    except: pass
    if text.isdigit() and len(text) >= 10: return text, None, None
    for p in [r'(?:product|catalog|goods)[/\w-]*(\d{10,})', r'magnit\.ru[/\w-]*(\d{10,})', r'(\d{10,})']:
        m = re.search(p, text)
        if m and m.group(1).isdigit(): return m.group(1), shop_code, catalog_type
    return None, None, None

@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("👋 <b>Привет! Я бот для проверки товаров в Магните.</b>\n\nОтправь мне <b>артикул товара</b> или <b>ссылку</b> из приложения Магнит, и я проверю наличие и цену.\n\nПримеры:\n• Артикул: <code>1199991965</code>\n• Ссылка из приложения Магнит")

@router.message(Command("check_all"))
async def cmd_check_all(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in user_last_article:
        await message.answer("❌ Сначала отправь мне артикул товара.")
        return
    await state.update_data(article=user_last_article[user_id])
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Отправить геолокацию", request_location=True)]], resize_keyboard=True)
    await message.answer("📍 Отправь геолокацию, чтобы я нашёл магазины рядом.\nИли /cancel чтобы отменить.", reply_markup=kb)
    await state.set_state(ScanStates.waiting_for_location)

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено.", reply_markup=ReplyKeyboardRemove())

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != ADMIN_ID: return
    stats = await get_user_stats()
    text = f"📊 <b>Статистика бота</b>\n\n👥 Всего: <b>{stats['total_users']}</b>\n🟢 За 24ч: <b>{stats['active_24h']}</b>\n🔍 Поисков: <b>{stats['total_searches']}</b>\n\n<b>🏆 Топ-10:</b>\n"
    for i, u in enumerate(stats['top_users'], 1): text += f"{i}. @{u['username'] or u['first_name']} — {u['searches']}\n"
    await message.answer(text)

@router.message(Command("logs"))
async def cmd_logs(message: Message):
    if message.from_user.id != ADMIN_ID: return
    logs = await get_recent_logs(20)
    if not logs: await message.answer("📭 Логов пока нет."); return
    text = "📋 <b>Последние действия:</b>\n\n"
    for l in logs[:15]: text += f"[{l['timestamp'][:16]}] {l['action']} @{l['username'] or l['first_name']} (ID:{l['user_id']})\n"
    await message.answer(text)

@router.message(Command("user"))
async def cmd_user(message: Message):
    if message.from_user.id != ADMIN_ID: return
    try: uid = int(message.text.split()[1])
    except: await message.answer("❌ /user ID"); return
    data = await get_user_details(uid)
    if not data: await message.answer(f"❌ Пользователь {uid} не найден."); return
    u = data['user']
    txt = f"👤 <b>{u['first_name']} {u['last_name'] or ''}</b>\n🆔 {uid}\n🔖 @{u['username'] or 'нет'}\n📅 С {u['created_at'][:10]}\n🕐 Был {u['last_seen'][:10] if u['last_seen'] else 'никогда'}\n\n"
    if data['history']: txt += "<b>Последние поиски:</b>\n" + "\n".join(f"• {h['article']} — {h['title'][:25]} ({h['price']}₽)" for h in data['history'][:5])
    await message.answer(txt)

@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if message.from_user.id != ADMIN_ID: return
    txt = message.text.replace('/broadcast', '', 1).strip()
    if not txt: await message.answer("❌ /broadcast ТЕКСТ"); return
    await message.answer("📨 Начинаю рассылку...")
    users = await get_all_users()
    s = f = 0
    for uid in users:
        try: await bot.send_message(uid, txt); s += 1; await asyncio.sleep(0.1)
        except: f += 1
    await message.answer(f"✅ Готово!\nОтправлено: {s}\nОшибок: {f}")

@router.message(ScanStates.waiting_for_location, F.location)
async def process_location(message: Message, state: FSMContext):
    lat = message.location.latitude
    lon = message.location.longitude
    data = await state.get_data()
    article = data.get("article")
    await state.clear()
    await message.answer(f"🔍 Ищу магазины рядом...\n📍 Координаты: {lat:.4f}, {lon:.4f}\n📦 Артикул: {article}", reply_markup=ReplyKeyboardRemove())
    stores = await magnit_api.get_stores_nearby(lat, lon, radius_km=15)
    if not stores: await message.answer("❌ Не удалось найти магазины рядом с тобой."); return
    stores_to_check = stores[:20]
    await message.answer(f"🏪 Найдено {len(stores)} магазинов. Проверяю наличие в {len(stores_to_check)} магазинах (это займет время)...")
    results = []
    sem = asyncio.Semaphore(5)
    async def check_store(store):
        async with sem:
            try:
                product = await magnit_api.search_product_in_store(article, store["code"])
                if not product: return None
                address = ""
                if product.in_stock: address = get_address_from_coordinates(store["latitude"], store["longitude"])
                return {"store_code": store["code"], "store_name": f"Магнит #{store['code']}", "store_address": address if address else f"~{store['distance']:.1f} км", "distance": store["distance"], "price": product.price, "quantity": product.quantity, "in_stock": product.in_stock, "url": product.url}
            except Exception as e:
                logger.error(f"Ошибка {store['code']}: {e}")
                return None
    tasks = [check_store(s) for s in stores_to_check]
    batch_results = await asyncio.gather(*tasks, return_exceptions=True)
    for res in batch_results:
        if isinstance(res, dict): results.append(res)
    if not results: await message.answer("❌ Товар не найден ни в одном магазине."); return
    in_stock = sorted([r for r in results if r["in_stock"]], key=lambda x: x["price"])
    not_in_stock = [r for r in results if not r["in_stock"]]
    top_10 = (in_stock + not_in_stock)[:10]
    text = f"📊 <b>Результаты проверки артикула {article}</b>\n\n🏪 Запрошено: {len(stores_to_check)}\n✅ Найдено: <b>{len(results)}</b>\n🟢 В наличии: <b>{len(in_stock)}</b>\n\n"
    if in_stock: text += f"<b>Топ-{min(10, len(in_stock))} по цене:</b>\n\n"
    for i, r in enumerate(top_10, 1):
        if r["in_stock"]: text += f"{i}. 🏪 <b>{r['store_name']}</b>\n   💰 Цена: <b>{r['price']:.2f} ₽</b>\n   📦 В наличии: {r['quantity']} шт.\n   📍 {r['store_address']}\n   📏 Расстояние: {r['distance']:.1f} км\n   🔗 <a href='{r['url']}'>Открыть в Магните</a>\n\n"
        else: text += f"{i}. ❌ <b>{r['store_name']}</b> - нет в наличии\n   📏 {r['distance']:.1f} км\n\n"
    await message.answer(text, disable_web_page_preview=True)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔍 Новый поиск", callback_data="new_search")]])
    await message.answer("💡 Что хотите сделать дальше?", reply_markup=kb)

@router.message(ScanStates.waiting_for_location, F.text)
async def wrong_input_during_location(message: Message):
    if message.text == "/cancel": return
    await message.answer("⚠️ Пожалуйста, отправь геолокацию через кнопку ниже.\nИли /cancel чтобы отменить.", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Отправить геолокацию", request_location=True)]], resize_keyboard=True))

@router.message(F.text)
async def handle_article(message: Message):
    raw_text = message.text.strip()
    article, shop_code, _ = extract_article_from_text(raw_text)
    if not article:
        await message.answer("❌ Не удалось найти артикул. Отправьте:\n• Артикул: <code>1199991965</code>\n• Или ссылку из приложения Магнит")
        return
    user_last_article[message.from_user.id] = article
    info = f"🔍 Ищу товар {article}"
    if shop_code: info += f" (магазин {shop_code})"
    await message.answer(info + "...")
    product = await magnit_api.search_product(article, shop_code=shop_code)
    if not product:
        await message.answer(f"❌ Товар с артикулом <code>{article}</code> не найден.")
        return
    stock = "✅ В наличии" if product.in_stock else "❌ Нет в наличии"
    text = f"📦 <b>{product.name}</b>\n\n💰 <b>Цена:</b> {product.price:.2f} ₽\n📊 <b>Статус:</b> {stock}\n📦 <b>Количество:</b> {product.quantity} шт.\n⭐ <b>Рейтинг:</b> {product.rating}/5\n\n🔗 <a href='{product.url}'>Открыть в Магните</a>"
    if product.image_url and product.image_url.startswith(('http://', 'https://')):
        try: await message.answer_photo(photo=product.image_url, caption=text)
        except: await message.answer(text)
    else: await message.answer(text)
    await add_to_history(user_id=message.from_user.id, article=article, title=product.name, price=f"{product.price:.2f}", in_stock=product.in_stock)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📊 Проверить во всех магазинах", callback_data="check_all")], [InlineKeyboardButton(text="🔍 Новый поиск", callback_data="new_search")]])
    await message.answer("💡 Что хотите сделать дальше?", reply_markup=kb)

@router.callback_query(F.data == "new_search")
async def callback_new_search(cb: CallbackQuery):
    await cb.message.answer("🔍 Отправьте артикул товара или ссылку:"); await cb.answer()

@router.callback_query(F.data == "check_all")
async def callback_check_all(cb: CallbackQuery, state: FSMContext):
    user_id = cb.from_user.id
    if user_id not in user_last_article: await cb.message.answer("❌ Сначала найдите товар."); await cb.answer(); return
    await state.update_data(article=user_last_article[user_id])
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Отправить геолокацию", request_location=True)]], resize_keyboard=True)
    await cb.message.answer("📍 Отправь геолокацию для проверки во всех магазинах:", reply_markup=kb)
    await state.set_state(ScanStates.waiting_for_location); await cb.answer()

async def main():
    try:
        logger.info("🚀 Запуск бота...")
        await init_db()
        logger.info("✅ База данных инициализирована")
        await magnit_api.init_browser()
        logger.info("✅ Браузер инициализирован")
        dp.message.middleware(LoggingMiddleware())
        dp.callback_query.middleware(LoggingMiddleware())
        dp.include_router(router)
        logger.info("🤖 Бот запущен!")
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен пользователем.")
    except Exception as e:
        logging.error(f"Фатальная ошибка: {e}", exc_info=True)
