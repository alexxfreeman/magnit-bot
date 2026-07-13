   import os
   from dotenv import load_dotenv

   load_dotenv()

   BOT_TOKEN = os.getenv("BOT_TOKEN")
   ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))

   if not BOT_TOKEN:
       raise ValueError("BOT_TOKEN не найден в .env!")
