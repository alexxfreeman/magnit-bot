import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
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

# Список кодов магазинов для проверки
# Можно добавить свои коды магазинов
STORE_CODES = [
    "764557",  # Пример магазина
    # Добавьте другие коды магазинов здесь
]

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "👋 <b>Привет! Я бот для проверки товаров в Магните.</b>\n\n"
        "Просто отправь мне <b>артикул товара</b> (цифрами), и я проверю:\n"
        "• Наличие в магазинах\n"
        "• Цену\n"
        "• Рейтинг\n\n"
        "Пример: <code>1199991965</code>",
        parse_mode="HTML"
    )

@dp.message(F.text)
async def handle_article(message: Message):
    """Обработка артикула"""
    article = message.text.strip()
    
    # Простая валидация
    if not article.isdigit():
        await message.answer("❌ Пожалуйста, отправьте артикул, состоящий только из цифр.")
        return
    
    await message.answer("🔍 Ищу товар в базе Магнита...")
    
    # Ищем товар в первом магазине (быстрый ответ)
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
        "💡 Хотите проверить наличие в других магазинах?\n"
        "Используйте команду /check_all для проверки во всех магазинах."
    )

@dp.message(F.text == "/check_all")
async def check_all_stores(message: Message):
    """Проверка во всех магазинах"""
    await message.answer("⏳ Эта функция в разработке...")

async def main():
    await init_db()
    logging.info("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен.")