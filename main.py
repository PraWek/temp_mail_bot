import asyncio
import os
import logging
from aiohttp import web

# Импортируем наших ботов
from tg_bot import dp, bot as tg_bot
from vk_bot import vk_bot


async def health_check(request):
    return web.Response(text="Telegram and VK Bots are running 24/7!")


async def start_web_server():
    app = web.Application()
    app.router.add_get('/', health_check)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"Web server successfully started on port {port}")


async def main():
    logging.basicConfig(level=logging.INFO)

    # Запускаем веб-сервер
    await start_web_server()

    logging.info("Starting Telegram and VK bots...")

    # Запускаем поллинг обоих ботов конкурентно (параллельно)
    await asyncio.gather(
        dp.start_polling(tg_bot),
        vk_bot.run_polling()
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bots stopped.")