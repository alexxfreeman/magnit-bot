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
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiohttp import ProxyConnector

from config import BOT_TOKEN, ADMIN_ID
from database import (
    init_db, add_to_history,
    get_user_stats, get_recent_logs, get_user_details, get_all_users
)
from magnit_api import magnit_api, get_address_from_coordinates
from middlewares import LoggingMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === НАСТРОЙКА ПРОКСИ ДЛЯ TELEGRAM ===
# Мы используем прокси только для связи с Telegram, чтобы обойти блокировку хостинга
proxy_url = "http://nbsYBT:v6pvCe@81.177.180.246:8000"
connector = ProxyConnector.from_url(proxy_url)
session = AiohttpSession(connector=connector)

bot = Bot(
    token=BOT_TOKEN,
    session=session,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
# =======================================

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
    await message.answer("👋 <b>Привет! Я бот для проверки товаров в Магните.</b>\n\nОтправь мне <b>артикул товара</b> или <b>ссылку</b> из приложения Магнит, и я проверю наличие и цену.\n\nПримеры:\n• Артикул: <code>1199991965</code>\n• Ссылка из приложения Магнит", parse_mode="HTML")

@router.message(Command("check_all"))
async def cmd_check_all(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user
