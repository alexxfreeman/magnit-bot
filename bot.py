import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Оставляем прокси, так как этот конкретный VPS блокирует прямой доступ к Telegram
session = AiohttpSession(proxy="http://nbsYBT:v6pvCe@81.177.180.246:8000")
bot = Bot(token=BOT_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("🚧 <b>ДА ЕБИСЬ ОНО ВСЁ КОНЁМ.</b>")

@dp.message(F.text)
async def echo_stub(message: Message):
    await message.answer("⏳ <b>Сервис временно недоступен.</b>\nПожалуйста, попробуйте позже.")

async def main():
    logger.info("🚀 Запуск заглушки бота...")
    try:
        await dp.start_polling(bot)
        logger.info("✅ Заглушка работает")
    except Exception as e:
        logger.error(f"❌ Ошибка запуска: {e}")

if __name__ == "__main__":
    asyncio.run(main())
