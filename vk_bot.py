import os
import random
import string
import html
import json
import httpx
from vkbottle.bot import Bot, Message
from vkbottle import Keyboard, KeyboardButtonColor, Text, BaseStateGroup

# Токен берем из переменных окружения
VK_TOKEN = os.getenv("VK_TOKEN")
API_URL = "https://api.mail.tm"

if not VK_TOKEN:
    print("ВНИМАНИЕ: Переменная окружения VK_TOKEN не задана!")

vk_bot = Bot(token=VK_TOKEN or "dummy_token")

# База данных для ВК пользователей
vk_users_db = {}


# --- FSM Состояния ---
class LoginState(BaseStateGroup):
    WAITING_FOR_ADDRESS = 1
    WAITING_FOR_PASSWORD = 2


# --- Вспомогательные функции API Mail.tm (такие же как в ТГ) ---
async def get_domain():
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{API_URL}/domains")
        return response.json()["hydra:member"][0]["domain"]


async def create_account(address, password):
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{API_URL}/accounts", json={"address": address, "password": password})
        return response.status_code in [200, 201]


async def get_token(address, password):
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{API_URL}/token", json={"address": address, "password": password})
        if response.status_code == 200:
            return response.json()["token"]
        return None


async def get_messages(token):
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{API_URL}/messages", headers={"Authorization": f"Bearer {token}"})
        return response.json().get("hydra:member", [])


async def get_message(token, msg_id):
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{API_URL}/messages/{msg_id}", headers={"Authorization": f"Bearer {token}"})
        return response.json()


def generate_random_string(length=10):
    return ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(length))


# --- Клавиатуры ВК ---
def main_menu():
    keyboard = Keyboard(inline=True)
    keyboard.add(Text("🆕 Создать ящик"), color=KeyboardButtonColor.POSITIVE).row()
    keyboard.add(Text("🔑 Войти в ящик"), color=KeyboardButtonColor.PRIMARY).row()
    keyboard.add(Text("📥 Проверить входящие"), color=KeyboardButtonColor.SECONDARY)
    return keyboard.get_json()


def cancel_menu():
    keyboard = Keyboard(inline=True)
    keyboard.add(Text("❌ Отмена"), color=KeyboardButtonColor.NEGATIVE)
    return keyboard.get_json()


# --- Обработчики команд ВК ---

@vk_bot.on.message(text=["/start", "Начать", "Привет"])
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я бот для работы с временной почтой.\n\nВыберите нужное действие:",
        keyboard=main_menu()
    )


@vk_bot.on.message(text="❌ Отмена")
async def cancel_action(message: Message):
    await vk_bot.state_dispenser.delete(message.peer_id)
    await message.answer("🚫 Действие отменено.", keyboard=main_menu())


@vk_bot.on.message(text="🆕 Создать ящик")
async def process_create_mail(message: Message):
    await message.answer("⏳ Генерирую адрес и регистрирую ящик...")
    try:
        domain = await get_domain()
        username = generate_random_string(8)
        password = generate_random_string(12)
        address = f"{username}@{domain}"

        if await create_account(address, password):
            token = await get_token(address, password)
            vk_users_db[message.from_id] = {"address": address, "token": token}
            await message.answer(
                f"✅ Ваш новый почтовый ящик готов!\n\n"
                f"📧 Адрес: {address}\n"
                f"🔑 Пароль: {password}\n\n"
                f"⚠️ Обязательно сохраните пароль!",
                keyboard=main_menu()
            )
        else:
            await message.answer("❌ Ошибка при создании ящика.", keyboard=main_menu())
    except Exception as e:
        await message.answer(f"❌ Произошла ошибка: {e}", keyboard=main_menu())


@vk_bot.on.message(text="🔑 Войти в ящик")
async def process_login_start(message: Message):
    await vk_bot.state_dispenser.set(message.peer_id, LoginState.WAITING_FOR_ADDRESS)
    await message.answer("Введите адрес вашей почты (например, example@domain.com):", keyboard=cancel_menu())


@vk_bot.on.message(state=LoginState.WAITING_FOR_ADDRESS)
async def process_login_address(message: Message):
    address = message.text.strip()
    await vk_bot.state_dispenser.set(message.peer_id, LoginState.WAITING_FOR_PASSWORD, address=address)
    await message.answer(f"📧 Адрес: {address}\n\nТеперь введите пароль от ящика:", keyboard=cancel_menu())


@vk_bot.on.message(state=LoginState.WAITING_FOR_PASSWORD)
async def process_login_password(message: Message):
    password = message.text.strip()
    state_data = await vk_bot.state_dispenser.get(message.peer_id)
    address = state_data.payload["address"]
    await vk_bot.state_dispenser.delete(message.peer_id)

    await message.answer("⏳ Авторизация...")
    token = await get_token(address, password)

    if token:
        vk_users_db[message.from_id] = {"address": address, "token": token}
        await message.answer(f"✅ Вы успешно вошли!\nТекущий ящик: {address}", keyboard=main_menu())
    else:
        await message.answer("❌ Неверный адрес или пароль.", keyboard=main_menu())


@vk_bot.on.message(text=["📥 Проверить входящие", "🔙 К списку писем"])
async def process_check_mail(message: Message):
    user_data = vk_users_db.get(message.from_id)
    if not user_data:
        return await message.answer("У вас нет активного ящика. Создайте его или войдите!", keyboard=main_menu())

    await message.answer("⏳ Проверяю входящие...")
    try:
        messages = await get_messages(user_data["token"])
        if not messages:
            return await message.answer(f"📬 Входящих писем пока нет.\nЯщик: {user_data['address']}",
                                        keyboard=main_menu())

        keyboard = Keyboard(inline=True)
        text = "📬 Входящие письма (последние 5):\n\n"

        for idx, msg in enumerate(messages[:5]):
            sender = msg['from']['address']
            subject = msg.get('subject', 'Без темы')
            text += f"{idx + 1}. От: {sender}\nТема: {subject}\n\n"
            # Передаем payload (скрытые данные в кнопке) для чтения конкретного письма
            keyboard.add(Text(f"Читать {idx + 1}", payload={"cmd": "read", "id": msg['id']})).row()

        keyboard.add(Text("🔙 Назад к меню"), color=KeyboardButtonColor.SECONDARY)
        await message.answer(text, keyboard=keyboard.get_json())
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}", keyboard=main_menu())


# Перехватываем нажатия на кнопки с payload (когда нажимают "Читать 1", "Читать 2" и т.д.)
@vk_bot.on.message(func=lambda msg: msg.payload and json.loads(msg.payload).get("cmd") == "read")
async def process_read_mail(message: Message):
    payload = json.loads(message.payload)
    msg_id = payload["id"]
    user_data = vk_users_db.get(message.from_id)

    if not user_data:
        return await message.answer("Сессия истекла.", keyboard=main_menu())

    await message.answer("⏳ Загружаю письмо...")
    try:
        msg = await get_message(user_data["token"], msg_id)
        subject = html.unescape(msg.get("subject", "Без темы"))
        from_email = msg.get("from", {}).get("address", "Неизвестен")
        body = msg.get("text", "Текст отсутствует (HTML-формат).")

        if len(body) > 3000:
            body = body[:3000] + "\n\n...[ТЕКСТ ОБРЕЗАН]..."

        text = (
            f"📨 От: {from_email}\n"
            f"📝 Тема: {subject}\n"
            f"〰️〰️〰️〰️〰️〰️〰️〰️〰️\n"
            f"{body}"
        )

        keyboard = Keyboard(inline=True)
        keyboard.add(Text("🔙 К списку писем"), color=KeyboardButtonColor.PRIMARY)
        await message.answer(text, keyboard=keyboard.get_json())
    except Exception as e:
        await message.answer(f"❌ Ошибка загрузки письма: {e}", keyboard=main_menu())


@vk_bot.on.message(text="🔙 Назад к меню")
async def back_to_main(message: Message):
    await message.answer("👋 Вы вернулись в главное меню.", keyboard=main_menu())