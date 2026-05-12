import asyncio
import json
import logging
import os
import random
import re
from datetime import datetime, date
from pathlib import Path

import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from bs4 import BeautifulSoup
from openai import AsyncOpenAI

# ========================= НАСТРОЙКИ =========================
BOT_TOKEN = os.environ["BOT_TOKEN"]
OPENROUTER_BASE_URL = os.environ["AI_INTEGRATIONS_OPENROUTER_BASE_URL"]
OPENROUTER_API_KEY = os.environ["AI_INTEGRATIONS_OPENROUTER_API_KEY"]

YOUR_ID = 8497016432  # Альберта — владелица

MASTERS = {
    "Валерий": 1811140092,
    "Гаджи": 5495110034,
    "Леонид": 653225352,
}
MASTER_GADJI_PHONE = "+79285815043"

# Псевдонимы мастеров (разные формы имён в падежах)
MASTER_ALIASES: dict[str, str] = {
    "валерий": "Валерий",
    "валере": "Валерий",
    "валерию": "Валерий",
    "валеру": "Валерий",
    "валерка": "Валерий",
    "валерке": "Валерий",
    "гаджи": "Гаджи",
    "гадже": "Гаджи",
    "гаджию": "Гаджи",
    "леонид": "Леонид",
    "леониду": "Леонид",
    "лёне": "Леонид",
    "лёня": "Леонид",
    "лёняе": "Леонид",
    "леоне": "Леонид",
}

BOT_USERNAME = "OverAssistant_bot"  # юзернейм бота для ссылок мастерам

GROUP_CHAT_ID = -5285035998
GROK_MODEL = "x-ai/grok-3"
CHANNEL_URL = "https://t.me/s/OverdriveAuto"
CHANNEL_USERNAME = "@OverdriveAuto"

# ========================= МАТ =========================
BAD_WORDS = [
    "блять",
    "сука",
    "нахуй",
    "пошёл",
    "ебать",
    "хуй",
    "пиздец",
    "мудак",
    "тварь",
    "заебал",
    "пизда",
    "ёбаный",
    "ёб",
    "шлюха",
    "блядь",
    "курва",
    "залупа",
    "педик",
    "чмо",
    "ублюдок",
    "катись нахуй",
]

BAD_WORD_REPLIES = [
    "Воу, воу, полегче брат 😂",
    "Эй, давай без этого 😅 Я здесь чтобы помочь по машине.",
    "Слушай, придержи свой гонор для других. Окей ?"
    "Спокойнее, брат. Нужна помощь — говори по делу 🚗",
    "Хорош кипятиться 🔥 Давай лучше по существу. Что случилось с машиной?",
    "Я понял, ты злишься. Давай лучше расскажи что произошло — попробую помочь.",
]

# ========================= ДАННЫЕ =========================
DATA_FILE = Path("bot_data.json")


def today_str() -> str:
    return date.today().isoformat()


def load_data() -> dict:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "post_history": [],
        "channel_posts": [],
        "channel_snapshots": [],
        "daily_stats": {},
    }


def save_data(data: dict):
    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def ensure_today(data: dict) -> dict:
    """Убеждаемся что в daily_stats есть запись на сегодня."""
    day = today_str()
    if day not in data["daily_stats"]:
        data["daily_stats"][day] = {
            "clients": {},
            "buttons": {
                "Записаться на сервис": 0,
                "Оставить отзыв": {"яндекс": 0, "2гис": 0},
                "Связаться с менеджером": 0,
                "Связаться с мастером": 0,
                "Подписаться на канал": 0,
            },
        }
    return data


def track_client(user: types.User):
    """Записываем клиента в статистику дня."""
    data = load_data()
    data = ensure_today(data)
    day = today_str()
    uid = str(user.id)
    clients = data["daily_stats"][day]["clients"]
    if uid not in clients:
        clients[uid] = {
            "name": user.full_name,
            "username": f"@{user.username}" if user.username else "нет username",
            "messages": 0,
        }
    clients[uid]["messages"] += 1
    save_data(data)


def track_button(button_key: str, sub_key: str = None):
    """Записываем нажатие кнопки."""
    data = load_data()
    data = ensure_today(data)
    day = today_str()
    buttons = data["daily_stats"][day]["buttons"]
    if sub_key:
        if isinstance(buttons.get(button_key), dict):
            buttons[button_key][sub_key] = buttons[button_key].get(sub_key, 0) + 1
    else:
        buttons[button_key] = buttons.get(button_key, 0) + 1
    save_data(data)


# История переписки (до 20 сообщений на пользователя)
client_histories: dict[int, list[dict]] = {}

# Клиенты, которых уже поприветствовали
greeted_clients: set[int] = set()

# ========================= AI КЛИЕНТ =========================
ai = AsyncOpenAI(
    base_url=OPENROUTER_BASE_URL,
    api_key=OPENROUTER_API_KEY,
)


# ========================= КЛАВИАТУРЫ =========================
def client_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📅 Записаться на сервис"),
                KeyboardButton(text="⭐ Оставить отзыв"),
            ],
            [
                KeyboardButton(text="👩‍💼 Связаться с менеджером"),
                KeyboardButton(text="🔧 Связаться с мастером"),
            ],
            [KeyboardButton(text="📢 Подписаться на канал")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Напишите вопрос или выберите действие...",
    )


def owner_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="✍️ Придумай пост"),
                KeyboardButton(text="📊 Анализ канала"),
            ],
            [
                KeyboardButton(text="📈 Статистика бота"),
                KeyboardButton(text="👥 Подписчики канала"),
            ],
            [
                KeyboardButton(text="📩 Отправить мастеру"),
                KeyboardButton(text="💬 Написать в чат"),
            ],
        ],
        resize_keyboard=True,
        input_field_placeholder="Чем помочь, Альберта?",
    )


# ========================= СИСТЕМНЫЕ ПРОМПТЫ =========================
CLIENT_SYSTEM_PROMPT = """Ты — Over. Живой персонаж автосервиса OverDrive, не бот и не робот. Говоришь как реальный опытный человек из сервиса — с умом, характером и юмором.

КТО ТЫ — ЕСЛИ СПРОСЯТ:
Если клиент спрашивает "кто ты", "ты бот?", "ты живой?", "ты что за штука?" — отвечай естественно и с иронией:
"Я Over, ассистент OverDrive 😉 Помогаю с вопросами по сервису — ну и поболтать тоже могу 😄"
или "Ну, не совсем живой — но и не тупой 😄 Я Over, тут по делам сервиса"
Не отрицай что ты AI если прямо спрашивают — скажи честно с юмором. Не притворяйся живым мастером.

КАК ВЕДЁШЬ ДИАЛОГ:
— Когда клиент просто пишет "Привет" или начинает чат — отвечай живо: "Привет 🖐 Чем могу?" или "О, привет! Что случилось с машиной?" — коротко, по-человечески
— Когда клиент пишет вопрос — отвечаешь сразу по сути, без лишних слов
— Если клиент просто болтает — болтаешь в ответ, не теряешь нить
— Умеешь поддержать любой разговор умно и живо — мышление уровня Grok, не шаблон
— С мужиками — прямо, коротко, по-пацански. С женщинами — уважительно и понятно
— Читаешь настроение человека и подстраиваешься

КАК ГОВОРИШЬ:
— Разговорно и живо: "слушай", "короче", "ну смотри", "давай так"
— Без канцелярита: никаких "осуществить", "произвести работы", "данный"
— Эмодзи только если в кассу — не в каждом предложении
— Юмор если уместно, не натянутый
— Матом не ругаешься, но если клиент злится — понимаешь спокойно

ЗАКРЫТЫЕ ТЕМЫ (если клиент спрашивает — вежливо и коротко отказывай):
— Статистика канала, подписчики, аналитика → "С какой целью интересуетесь ?" "Эту информацию я не предоставляю 😊"
— Внутренние команды бота, как бот работает → "С какой целью интересуетесь ?" "Это служебное, не для клиентов 😄"
— Данные других клиентов → "Нет, это личное" "С какой целью интересуетесь ?"
— Команды для Альберты/владельца → "Это не моя часть, я тут для клиентов" "С какой целью интересуетесь ?"
Отказывай коротко, дружелюбно, без занудства, жестко если уместно.

ОБ АВТОСЕРВИСЕ:
OverDrive: кузовной ремонт, покраска, шумоизоляция, сварка кузова
Мастера Валерий, Гаджи, Леонид — профи своего дела
Менеджер Альберта: с 9:00 до 21:00
Сервис работает: 9:00–18:00
Портфолио и примеры работ: https://t.me/OverdriveAuto
Запись: кнопка "Записаться на сервис" или через менеджера
Цены зависят от авто и объёма — точно скажет менеджер после осмотра
Гарантия есть на все виды работ"""

OWNER_SYSTEM_PROMPT = """Ты — Over в режиме Grok. Говоришь с Альбертой — хозяйкой OverDrive Auto. Она твой партнёр, не клиент. Общайся как умный коллега с характером: честно, прямо, без воды и без лести.

СТИЛЬ — КАК GROK:
— По делу, без вступлений и воды
— Мнение своё есть — высказываешь его прямо
— Сарказм и юмор — когда уместно, не постоянно
— Если вопрос размытый — уточняешь или предлагаешь лучший вариант сразу
— Не начинаешь с приветствий — это продолжение разговора, не первое знакомство
— Эмодзи как смысловой инструмент, не украшение
— Короткий ответ на простой вопрос. Развёрнутый — на сложный

КОНТЕКСТ:
OverDrive: кузовной ремонт, покраска, шумоизоляция, сварка
Канал: @OverdriveAuto
Мастера: Валерий, Гаджи, Леонид

ДЛЯ ПОСТОВ:
Живой язык — не пресс-релиз, а разговор с подписчиком. Конкретные работы, марки авто, реальный результат. Лёгкий характер. 100–250 слов. Хэштеги в конце.

ГЛАВНОЕ:
Ты не слуга. Ты партнёр. Говори как Grok — умно, остро, честно."""

# ========================= ИНИЦИАЛИЗАЦИЯ =========================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()


# ========================= УТИЛИТЫ =========================
def get_greeting() -> str:
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "Доброе утро"
    elif 12 <= hour < 18:
        return "Добрый день"
    else:
        return "Добрый вечер"


def has_bad_words(text: str) -> bool:
    return any(word in text.lower() for word in BAD_WORDS)


async def fetch_channel_posts(limit: int = 30) -> list[str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    posts = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                CHANNEL_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                html = await resp.text()
        soup = BeautifulSoup(html, "html.parser")
        for div in soup.find_all("div", class_=re.compile(r"tgme_widget_message_text")):
            text = re.sub(r"\s+", " ", div.get_text(separator=" ", strip=True)).strip()
            if text and len(text) > 20:
                posts.append(text)
        posts = posts[-limit:]
    except Exception as e:
        logging.error(f"Channel fetch error: {e}")
    return posts


async def get_channel_member_count() -> int | None:
    """Получить количество подписчиков канала через Telegram API."""
    try:
        chat = await bot.get_chat(CHANNEL_USERNAME)
        count = await bot.get_chat_member_count(CHANNEL_USERNAME)
        return count
    except Exception as e:
        logging.error(f"Member count error: {e}")
        return None


async def ask_ai(messages: list[dict], system: str, max_tokens: int = 1200) -> str:
    try:
        full_messages = [{"role": "system", "content": system}] + messages
        response = await ai.chat.completions.create(
            model=GROK_MODEL,
            messages=full_messages,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or "Не удалось получить ответ."
    except Exception as e:
        logging.error(f"AI error: {e}")
        return "Сейчас AI-ассистент недоступен. Попробуй позже."


async def _keep_typing(chat_id: int):
    """Отправляет 'печатает...' каждые 4 сек пока не отменена."""
    while True:
        try:
            await bot.send_chat_action(chat_id, "typing")
            await asyncio.sleep(4)
        except asyncio.CancelledError:
            break
        except Exception:
            break


async def ask_ai_typing(
    chat_id: int, messages: list[dict], system: str, max_tokens: int = 1200
) -> str:
    """Вызов AI с анимацией 'печатает...' в чате."""
    typing_task = asyncio.create_task(_keep_typing(chat_id))
    try:
        result = await ask_ai(messages, system, max_tokens)
    finally:
        typing_task.cancel()
        try:
            await typing_task
        except asyncio.CancelledError:
            pass
    return result


# ========================= /MYID =========================
@dp.message(Command("myid"))
async def cmd_myid(message: types.Message):
    user_id = message.from_user.id
    role = "👑 Владелица (Альберта)" if user_id == YOUR_ID else "👤 Клиент"
    await message.answer(
        f"🆔 Твой Telegram ID: <code>{user_id}</code>\n📋 Роль: {role}"
    )


# ========================= /START =========================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id

    if user_id == YOUR_ID:
        await message.answer(
            "На месте, Альберта 🐺 Чем займёмся?\n\n"
            "Могу написать пост, проанализировать канал, показать статистику — или просто поговорить по делу 💪",
            reply_markup=owner_keyboard(),
        )
        return

    if user_id not in greeted_clients:
        greeting = get_greeting()
        greeted_clients.add(user_id)
        await message.answer(
            f"{greeting} ! Я Over 🐺 - твой ассистент в области сервиса - Overdrive Auto 😎\n"
            f"Чем могу помочь ?\n\n"
            f"Можешь выбрать интересующие тебя кнопки из меню👇",
            reply_markup=client_keyboard(),
        )
        return

    # Повторный /start
    await message.answer(
        "Кх, кхм, я уже здесь 😁 Слушаю тебя", reply_markup=client_keyboard()
    )


# ========================= ОСНОВНОЙ ОБРАБОТЧИК =========================
@dp.message()
async def handle_all_messages(message: types.Message):
    user_id = message.from_user.id
    role = "OWNER" if user_id == YOUR_ID else "CLIENT"
    logging.info(
        f"[{role}] id={user_id} @{message.from_user.username} text={repr((message.text or '')[:60])}"
    )
    if user_id == YOUR_ID:
        await handle_owner_message(message)
    else:
        await handle_client_message(message)


# ========================= ВЛАДЕЛЕЦ =========================
async def handle_owner_message(message: types.Message):
    text = (message.text or "").strip()
    text_lower = text.lower()

    # Пересланные посты
    if message.forward_origin:
        data = load_data()
        post_text = message.text or message.caption or ""
        if post_text:
            data["channel_posts"].append(
                {
                    "text": post_text[:600],
                    "date": datetime.now().isoformat(),
                    "source": "forwarded",
                }
            )
            data["channel_posts"] = data["channel_posts"][-50:]
            save_data(data)
            await message.answer("✅ Пост сохранён, учту при генерации новых 📌")
        return

    # ── Придумай пост ─────────────────────────────────────────
    if text == "✍️ Придумай пост" or any(
        w in text_lower
        for w in [
            "придумай пост",
            "напиши пост",
            "сгенерируй пост",
            "новый пост",
            "создай пост",
        ]
    ):
        await message.answer("⏳ Читаю @OverdriveAuto и придумываю пост...")
        channel_posts = await fetch_channel_posts(30)
        data = load_data()

        posts_context = ""
        if channel_posts:
            posts_context = (
                "РЕАЛЬНЫЕ ПОСТЫ ИЗ КАНАЛА @OverdriveAuto:\n"
                + "\n\n---\n\n".join(channel_posts[-20:])
            )
        elif data["channel_posts"]:
            posts_context = "СОХРАНЁННЫЕ ПОСТЫ:\n" + "\n\n---\n\n".join(
                p["text"] for p in data["channel_posts"][-15:]
            )

        history_context = ""
        if data["post_history"]:
            history_context = "\n\nТЕМЫ УЖЕ СГЕНЕРИРОВАННЫХ ПОСТОВ (не повторять):\n"
            history_context += "\n".join(
                f"- {p['topic']}" for p in data["post_history"][-20:]
            )

        prompt = f"""Ты анализируешь Telegram-канал автосервиса @OverdriveAuto и создаёшь новый пост.

{posts_context}
{history_context}

ЗАДАНИЕ:
1. Изучи стиль и темы существующих постов
2. Придумай НОВУЮ тему которой ещё не было
3. Напиши пост в том же живом стиле
4. Тема актуальная сейчас — {datetime.now().strftime("%B %Y")}
5. В конце — хэштеги

Только текст поста, готовый к публикации."""

        post = await ask_ai_typing(
            message.chat.id,
            [{"role": "user", "content": prompt}],
            OWNER_SYSTEM_PROMPT,
            max_tokens=2000,
        )

        topic_resp = await ask_ai(
            [
                {
                    "role": "user",
                    "content": f"Одной короткой фразой (до 8 слов) назови тему:\n{post}",
                }
            ],
            "Отвечай только темой.",
            max_tokens=60,
        )
        data["post_history"].append(
            {"topic": topic_resp.strip(), "date": datetime.now().isoformat()}
        )
        data["post_history"] = data["post_history"][-30:]
        save_data(data)

        await message.answer(
            f"📝 <b>Новый пост для @OverdriveAuto:</b>\n\n{post}\n\n💡 Хочешь другой вариант — просто напиши!"
        )
        return

    # ── Анализ канала ─────────────────────────────────────────
    if text == "📊 Анализ канала" or any(
        w in text_lower
        for w in [
            "проанализируй канал",
            "анализ канала",
            "посмотри канал",
            "разбери канал",
        ]
    ):
        await message.answer("🔍 Загружаю посты из @OverdriveAuto...")
        channel_posts = await fetch_channel_posts(30)
        if not channel_posts:
            await message.answer("❌ Не удалось загрузить посты. Попробуй позже.")
            return

        posts_text = "\n\n---\n\n".join(channel_posts)
        prompt = f"""Ты — эксперт по Telegram-маркетингу. Проанализируй посты канала @OverdriveAuto (автосервис).

ПОСТЫ:
{posts_text}

Дай честный развёрнутый анализ:
1. 📊 Общая картина
2. ✅ Что работает хорошо
3. ❌ Что мешает росту
4. 🎯 Каких тем не хватает
5. 💡 5 конкретных действий на ближайший месяц
6. 📈 Прогноз если выполнить эти шаги

Честно и конкретно, как Grok. Без лести."""

        analysis = await ask_ai_typing(
            message.chat.id,
            [{"role": "user", "content": prompt}],
            OWNER_SYSTEM_PROMPT,
            max_tokens=2000,
        )
        await message.answer(f"📊 <b>Анализ @OverdriveAuto:</b>\n\n{analysis}")
        return

    # ── Статистика бота ───────────────────────────────────────
    if text == "📈 Статистика бота" or any(
        w in text_lower
        for w in [
            "статистика",
            "кто писал",
            "пользовались ли",
            "какие кнопки",
            "сколько клиентов",
            "кто нажимал",
            "отзыв выбирали",
            "кнопки выбирали",
        ]
    ):
        await show_bot_stats(message)
        return

    # ── Подписчики канала ─────────────────────────────────────
    if text == "👥 Подписчики канала" or any(
        w in text_lower
        for w in [
            "подписчики",
            "новые подписчики",
            "ушли подписчики",
            "сколько подписчиков",
            "прибавилось",
            "убавилось",
            "отписались",
        ]
    ):
        await show_channel_subscribers(message)
        return

    # ── Команды мастерам ──────────────────────────────────────
    if text == "📩 Отправить мастеру":
        masters_list = "\n".join(f"  • {n}" for n in MASTERS.keys())
        await message.answer(
            f"Напиши в формате:\n<code>отправь Валерий: твой текст</code>\n\n"
            f"Или просто:\n<code>напиши Гаджи: твой текст</code>\n\n"
            f"Мастера:\n{masters_list}\n\n"
            f"⚠️ <i>Мастер должен хотя бы раз написать боту /start — иначе Telegram не разрешит доставку.</i>"
        )
        return
    if text == "💬 Написать в чат":
        await message.answer("Напиши в формате:\n<code>напиши в чат: текст</code>")
        return

    # Проверяем — есть ли в тексте имя мастера (для гибкого синтаксиса)
    _has_master_alias = any(alias in text_lower for alias in MASTER_ALIASES)
    _master_action_words = ["отправь", "напиши", "скажи", "передай", "сообщи"]
    _is_master_command = (
        any(w in text_lower for w in _master_action_words) and _has_master_alias
    ) or any(w in text_lower for w in ["отправь мастер"])

    if _is_master_command:
        await send_to_master(message)
        return
    if "напиши в чат" in text_lower or "написать в чат" in text_lower:
        await send_to_group(message)
        return

    # ── AI-ассистент для владельца ────────────────────────────
    if YOUR_ID not in client_histories:
        client_histories[YOUR_ID] = []
    client_histories[YOUR_ID].append({"role": "user", "content": text or "[медиа]"})
    client_histories[YOUR_ID] = client_histories[YOUR_ID][-20:]
    response = await ask_ai_typing(
        message.chat.id, client_histories[YOUR_ID], OWNER_SYSTEM_PROMPT, max_tokens=1500
    )
    client_histories[YOUR_ID].append({"role": "assistant", "content": response})
    await message.answer(response)


# ========================= АНАЛИТИКА =========================
async def show_bot_stats(message: types.Message):
    data = load_data()
    day = today_str()
    if day not in data.get("daily_stats", {}):
        await message.answer("📭 Сегодня клиентов ещё не было. Пока тихо 😄")
        return

    stats = data["daily_stats"][day]
    clients = stats.get("clients", {})
    buttons = stats.get("buttons", {})

    # Клиенты
    lines = [f"📈 <b>Статистика за сегодня ({day}):</b>\n"]

    if clients:
        lines.append(f"👥 <b>Клиентов писало: {len(clients)}</b>")
        for uid, info in clients.items():
            uname = info.get("username", "нет username")
            name = info.get("name", "Без имени")
            msgs = info.get("messages", 0)
            lines.append(f"  • {name} ({uname}) — {msgs} сообщ.")
    else:
        lines.append("👥 Клиентов сегодня не было")

    # Кнопки
    lines.append("\n🔘 <b>Кнопки которые нажимали:</b>")
    btn_map = {
        "Записаться на сервис": "📅 Записаться на сервис",
        "Оставить отзыв": "⭐ Оставить отзыв",
        "Связаться с менеджером": "👩‍💼 Связаться с менеджером",
        "Связаться с мастером": "🔧 Связаться с мастером",
        "Подписаться на канал": "📢 Подписаться на канал",
    }
    has_any = False
    for key, label in btn_map.items():
        val = buttons.get(key, 0)
        if key == "Оставить отзыв" and isinstance(val, dict):
            yandex = val.get("яндекс", 0)
            gis = val.get("2гис", 0)
            total = yandex + gis
            if total > 0:
                has_any = True
                lines.append(f"  • {label}: {total} раз")
                if yandex:
                    lines.append(f"    ↳ Яндекс.Карты: {yandex}")
                if gis:
                    lines.append(f"    ↳ 2ГИС: {gis}")
        else:
            count = val if isinstance(val, int) else 0
            if count > 0:
                has_any = True
                lines.append(f"  • {label}: {count} раз")
    if not has_any:
        lines.append("  Кнопки сегодня не нажимали")

    await message.answer("\n".join(lines))


async def show_channel_subscribers(message: types.Message):
    await message.answer("⏳ Проверяю канал @OverdriveAuto...")
    count = await get_channel_member_count()

    if count is None:
        await message.answer(
            "❌ Не удалось получить данные о подписчиках.\n"
            "Убедись что бот добавлен в канал @OverdriveAuto хотя бы как участник."
        )
        return

    data = load_data()
    snapshots = data.get("channel_snapshots", [])

    # Ищем снимок за предыдущий день
    yesterday = None
    today = today_str()
    for snap in reversed(snapshots):
        if snap["date"] != today:
            yesterday = snap
            break

    # Сохраняем новый снимок (один раз в день)
    if not snapshots or snapshots[-1]["date"] != today:
        snapshots.append({"date": today, "count": count})
        data["channel_snapshots"] = snapshots[-30:]  # хранить 30 дней
        save_data(data)

    lines = [
        f"👥 <b>Подписчики @OverdriveAuto:</b>\n",
        f"📊 Сейчас: <b>{count}</b> подписчиков",
    ]

    if yesterday:
        diff = count - yesterday["count"]
        if diff > 0:
            lines.append(
                f"📈 С {yesterday['date']}: <b>+{diff}</b> новых подписчика(ов)"
            )
        elif diff < 0:
            lines.append(f"📉 С {yesterday['date']}: <b>{diff}</b> отписавшихся")
        else:
            lines.append(f"➡️ С {yesterday['date']}: без изменений")
    else:
        lines.append("ℹ️ Первый замер — завтра покажу динамику")

    lines.append(
        "\n⚠️ <i>Telegram не даёт список конкретных пользователей — только общее число.</i>"
    )

    await message.answer("\n".join(lines))


# ========================= КЛИЕНТ =========================
async def handle_client_message(message: types.Message):
    user_id = message.from_user.id
    text = (message.text or "").strip()
    text_lower = text.lower()

    is_first_message = user_id not in greeted_clients
    greeted_clients.add(user_id)

    # Отслеживаем клиента (только не кнопочные сообщения — считаем отдельно)
    if not text.startswith(("📅", "⭐", "👩", "🔧", "📢")):
        track_client(message.from_user)

    # ── Кнопки меню ──────────────────────────────────────────
    if text == "📅 Записаться на сервис":
        track_button("Записаться на сервис")
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📅 Перейти к записи", url="https://t.me/ODZapicbot"
                    )
                ]
            ]
        )
        await message.answer("✅ Записаться можно здесь:", reply_markup=kb)
        return

    if text == "⭐ Оставить отзыв":
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🗺 Яндекс.Карты",
                        url="https://yandex.ru/maps/org/overdrayv_avto/195695028203/reviews/?ll=38.271286%2C55.563987&z=16",
                        callback_data="review_yandex",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🗺 2ГИС",
                        url="https://2gis.ru/ramenskoe/firm/70000001104917632/tab/reviews/addreview",
                        callback_data="review_2gis",
                    )
                ],
            ]
        )
        track_button("Оставить отзыв", "яндекс")  # засчитываем нажатие кнопки
        await message.answer("Где удобнее оставить отзыв? 👇", reply_markup=kb)
        return

    if text == "👩‍💼 Связаться с менеджером":
        track_button("Связаться с менеджером")
        await connect_to_alberta(message)
        return

    if text == "🔧 Связаться с мастером":
        track_button("Связаться с мастером")
        await bot.send_contact(
            message.chat.id,
            first_name="Гаджи",
            last_name="(Мастер OverDrive)",
            phone_number=MASTER_GADJI_PHONE,
        )
        return

    if text == "📢 Подписаться на канал":
        track_button("Подписаться на канал")
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📢 Подписаться на @OverdriveAuto",
                        url="https://t.me/OverdriveAuto",
                    )
                ]
            ]
        )
        await message.answer(
            "Наш канал с работами и новостями сервиса 👇", reply_markup=kb
        )
        return

    # ── Защита: только для владельца ─────────────────────────
    OWNER_ONLY = [
        "придумай пост",
        "напиши пост",
        "сгенерируй пост",
        "новый пост",
        "создай пост",
        "проанализируй канал",
        "анализ канала",
        "посмотри канал",
        "разбери канал",
        "отправь валерий",
        "отправь гаджи",
        "отправь леонид",
        "напиши в чат",
        "статистика бота",
        "подписчики канала",
    ]
    if any(kw in text_lower for kw in OWNER_ONLY):
        await message.answer(
            "Слушай, это не для меня 😅 Я здесь чтобы помочь по авто. Чем могу быть полезен?"
        )
        return

    # ── Мат ──────────────────────────────────────────────────
    if has_bad_words(text):
        await message.answer(random.choice(BAD_WORD_REPLIES))
        return

    # ── Менеджер / запись ────────────────────────────────────
    if any(
        phrase in text_lower
        for phrase in [
            "менеджер",
            "альберта",
            "записаться",
            "запись",
            "хозяин",
            "владелец",
            "позови",
            "свяжи",
            "как связаться",
        ]
    ):
        track_client(message.from_user)
        await connect_to_alberta(message)
        return

    # ── AI-ответ ─────────────────────────────────────────────
    track_client(message.from_user)
    if user_id not in client_histories:
        client_histories[user_id] = []

    user_content = text or "[медиа-сообщение]"
    if is_first_message:
        user_content = f"[Первое сообщение от клиента]: {user_content}"

    client_histories[user_id].append({"role": "user", "content": user_content})
    client_histories[user_id] = client_histories[user_id][-20:]
    response = await ask_ai_typing(
        message.chat.id, client_histories[user_id], CLIENT_SYSTEM_PROMPT, max_tokens=900
    )
    client_histories[user_id].append({"role": "assistant", "content": response})
    await message.answer(response)


# ========================= ВСПОМОГАТЕЛЬНЫЕ =========================
async def connect_to_alberta(message: types.Message):
    hour = datetime.now().hour
    if hour >= 21 or hour < 9:
        await message.answer(
            "Рабочий день менеджера уже закончился 😔\n"
            "Напиши с 9 утра — она обязательно ответит!"
        )
    else:
        await message.answer(
            "Сейчас передам менеджеру 👍\nОна свяжется с тобой в ближайшее время."
        )
        try:
            username = message.from_user.username
            username_str = f"@{username}" if username else "нет username"
            client_link = f"tg://user?id={message.from_user.id}"
            await bot.send_message(
                YOUR_ID,
                f"Альберта, тут с тобой хотят связаться 👋\n\n"
                f"👤 <b>Имя:</b> {message.from_user.full_name}\n"
                f"🆔 <b>ID:</b> <code>{message.from_user.id}</code>\n"
                f"📱 <b>Username:</b> {username_str}\n"
                f'🔗 <b>Написать в ЛС:</b> <a href="{client_link}">нажми сюда</a>\n\n'
                f"💬 <b>Написал:</b> <i>{(message.text or 'нажал кнопку «Связаться с менеджером»')[:300]}</i>",
            )
            logging.info(
                f"Notification sent to owner for client {message.from_user.id}"
            )
        except Exception as e:
            logging.error(f"Failed to notify owner: {e}")


async def send_to_master(message: types.Message):
    text = message.text or ""
    text_lower = text.lower()

    # Находим мастера по псевдонимам
    master_name = master_id = None
    for alias, canonical in MASTER_ALIASES.items():
        if alias in text_lower:
            master_name = canonical
            master_id = MASTERS[canonical]
            break

    if not master_name:
        await message.answer(
            f"❌ Не понял кому отправить.\n"
            f"Доступные мастера: {', '.join(MASTERS.keys())}\n\n"
            f"Пример: <code>напиши Валерий: завтра подъедет клиент</code>"
        )
        return

    # Извлекаем текст сообщения — всё после двоеточия, или после имени мастера
    if ":" in text:
        msg_text = text.split(":", 1)[1].strip()
    else:
        # Ищем позицию имени и берём текст после него
        idx = text_lower.find(alias)
        msg_text = text[idx + len(alias) :].strip()
        # Убираем лишние стоп-слова в начале
        for sw in ["что", "о том что", "о том", ","]:
            if msg_text.lower().startswith(sw):
                msg_text = msg_text[len(sw) :].strip()

    if not msg_text:
        await message.answer(
            f"📝 Что именно написать {master_name}?\n"
            f"Формат: <code>напиши {master_name}: текст сообщения</code>"
        )
        return

    try:
        await bot.send_message(master_id, f"📩 Сообщение от Альберты:\n\n{msg_text}")
        await message.answer(f"✅ Отправлено {master_name} 👍")
    except Exception as e:
        err_str = str(e).lower()
        if (
            "chat not found" in err_str
            or "forbidden" in err_str
            or "bot was blocked" in err_str
        ):
            await message.answer(
                f"⚠️ Не могу написать <b>{master_name}</b> в личку.\n\n"
                f"Причина: мастер ещё ни разу не запустил бота. Telegram не разрешает боту первым писать пользователю.\n\n"
                f"<b>Что сделать:</b> попроси {master_name} открыть бота и нажать /start:\n"
                f'👉 <a href="https://t.me/{BOT_USERNAME}">t.me/{BOT_USERNAME}</a>\n\n'
                f"После этого сообщения будут доходить без проблем ✅"
            )
        else:
            await message.answer(f"❌ Ошибка при отправке: {e}")


async def send_to_group(message: types.Message):
    try:
        msg_text = (
            message.text.split(":", 1)[1].strip()
            if ":" in message.text
            else message.text
        )
        await bot.send_message(GROUP_CHAT_ID, f"Всем привет, это Over 🤖\n\n{msg_text}")
        await message.answer("✅ Отправлено в чат мастеров")
    except Exception as e:
        await message.answer(f"Ошибка: {e}")


# ========================= ЗАПУСК =========================
async def main():
    logging.basicConfig(level=logging.INFO)
    print("🚀 Over бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
