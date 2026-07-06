import asyncio
import logging
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
    """Проверка товара во всех магазинах"""
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
    await message.answer(f" Проверяю артикул <b>{article}</b> во всех магазинах...", parse_mode="HTML")
    
    # Здесь будет логика проверки во всех магазинах
    # Пока заглушка
    await message.answer("⏳ Функция в разработке. Скоро будет доступна!")

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
