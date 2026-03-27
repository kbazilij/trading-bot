import asyncio
import aiohttp
import logging
import random
import json
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ========== НАСТРОЙКИ (ОБЯЗАТЕЛЬНО ЗАПОЛНИ!) ==========

# 1. Токен от @BotFather
BOT_TOKEN = "8601151152:AAHfsRUQdRMQVv5_kW4mdsZzF8Ls5qT0J3s"

# 2. Ключ DeepSeek AI (получи на platform.deepseek.com)
AI_KEY = "sk-c61c8ba2dc0042e2b1ff595d15c440fb"

# 3. Твой Telegram ID (узнай через @userinfobot)
ADMIN_ID = 558427600  # Замени на свой ID (например: 123456789)

# 4. Настройки авто-сигналов
AUTO_SIGNAL_INTERVAL = 300  # Интервал в секундах (300 = 5 минут)

# ========== КОНФИГУРАЦИЯ ==========
AI_URL = "https://api.deepseek.com/chat/completions"
AI_MODEL = "deepseek-chat"
DATA_FILE = "trading_data.json"


# ========== БАЗА ДАННЫХ ==========
class TradingDatabase:
    """Управление данными бота"""

    def __init__(self):
        self.vip_users = set()  # VIP подписчики
        self.auto_users = set()  # Подписчики авто-сигналов
        self.history = []  # История сигналов
        self.stats = {
            "total": 0,
            "buy": 0,
            "sell": 0
        }
        self.load_data()

    def load_data(self):
        """Загрузка из файла"""
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.vip_users = set(data.get('vip', []))
                    self.auto_users = set(data.get('auto', []))
                    self.history = data.get('history', [])
                    self.stats = data.get('stats', {"total": 0, "buy": 0, "sell": 0})
                logging.info(f"✓ Загружено: VIP={len(self.vip_users)}, Auto={len(self.auto_users)}")
        except Exception as e:
            logging.error(f"Ошибка загрузки: {e}")

    def save_data(self):
        """Сохранение в файл"""
        try:
            data = {
                'vip': list(self.vip_users),
                'auto': list(self.auto_users),
                'history': self.history[-100:],  # Храним последние 100
                'stats': self.stats
            }
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"Ошибка сохранения: {e}")

    def add_signal(self, asset, signal, price, expiry):
        """Добавить сигнал в историю"""
        self.history.append({
            'time': datetime.now().strftime('%H:%M:%S'),
            'date': datetime.now().strftime('%d.%m.%Y'),
            'asset': asset,
            'signal': signal,
            'price': price,
            'expiry': expiry
        })

        self.stats['total'] += 1
        if signal == 'Покупка':
            self.stats['buy'] += 1
        else:
            self.stats['sell'] += 1

        self.save_data()

    def get_history(self, limit=10):
        """Получить последние сигналы"""
        return list(reversed(self.history[-limit:]))

    def is_vip(self, user_id):
        """Проверка VIP статуса"""
        return user_id == ADMIN_ID or user_id in self.vip_users

    def add_vip(self, user_id):
        """Добавить VIP"""
        self.vip_users.add(user_id)
        self.save_data()

    def remove_vip(self, user_id):
        """Удалить VIP"""
        self.vip_users.discard(user_id)
        self.save_data()


# Инициализация БД
db = TradingDatabase()


# ========== СОСТОЯНИЯ FSM ==========
class TradeFlow(StatesGroup):
    choosing_pair = State()
    choosing_expiry = State()


# ========== ДАННЫЕ ==========
PAIRS = [
    ("EURUSD", "EUR/USD 🇪🇺🇺🇸"),
    ("GBPUSD", "GBP/USD 🇬🇧🇺🇸"),
    ("USDJPY", "USD/JPY 🇺🇸🇯🇵"),
    ("AUDUSD", "AUD/USD 🇦🇺🇺🇸"),
    ("USDCHF", "USD/CHF 🇺🇸🇨🇭"),
    ("USDCAD", "USD/CAD 🇺🇸🇨🇦"),
    ("EURGBP", "EUR/GBP 🇪🇺🇬🇧"),
    ("EURJPY", "EUR/JPY 🇪🇺🇯🇵"),
    ("BITCOIN", "Bitcoin ₿")
]

EXPIRIES = ["1 мин", "2 мин", "3 мин", "5 мин", "10 мин", "15 мин"]

# Примерные цены (демо)
BASE_PRICES = {
    "EURUSD": 1.0895, "GBPUSD": 1.2645, "USDJPY": 149.85,
    "AUDUSD": 0.6385, "USDCHF": 0.8845, "USDCAD": 1.3615,
    "EURGBP": 0.8625, "EURJPY": 163.25, "BITCOIN": 65420.50
}


# ========== КЛАВИАТУРЫ ==========
def main_menu():
    """Главное меню (постоянные кнопки внизу)"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🚀 Новый сигнал")],
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="📜 История")],
            [KeyboardButton(text="⏰ Авто-сигналы"), KeyboardButton(text="ℹ️ Информация")]
        ],
        resize_keyboard=True
    )


def pairs_keyboard():
    """Выбор пары"""
    buttons = []
    for code, name in PAIRS:
        buttons.append([InlineKeyboardButton(text=name, callback_data=f"p_{code}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def expiry_keyboard():
    """Выбор времени"""
    buttons = []
    for exp in EXPIRIES:
        buttons.append([InlineKeyboardButton(text=f"⏱ {exp}", callback_data=f"e_{exp}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def signal_actions(asset):
    """Кнопки после сигнала"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Повторить", callback_data=f"repeat_{asset}")],
        [InlineKeyboardButton(text="🚀 Другая пара", callback_data="new")]
    ])


def auto_toggle(is_on):
    """Переключатель авто-сигналов"""
    text = "🔕 Отключить" if is_on else "🔔 Включить"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data="auto_toggle")]
    ])


# ========== ФУНКЦИИ ==========
def get_price(asset):
    """Генерация цены с волатильностью"""
    base = BASE_PRICES.get(asset, 1.0)
    volatility = random.uniform(-0.003, 0.003)
    price = base * (1 + volatility)

    if asset == "BITCOIN":
        return round(price, 2)
    elif "JPY" in asset:
        return round(price, 2)
    else:
        return round(price, 5)


async def ai_predict(asset, expiry, price):
    """Получение сигнала от AI"""
    prompt = f"""Ты опытный трейдер бинарных опционов.

Актив: {asset}
Цена: {price}
Экспирация: {expiry}
Время: {datetime.now().strftime('%H:%M')}

Дай прогноз движения цены.
Ответь ТОЛЬКО одним словом: CALL или PUT"""

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    AI_URL,
                    json={
                        "model": AI_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.25,
                        "max_tokens": 5
                    },
                    headers={
                        "Authorization": f"Bearer {AI_KEY}",
                        "Content-Type": "application/json"
                    },
                    timeout=15
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result = data["choices"][0]["message"]["content"].upper()
                    return "CALL" if "CALL" in result else "PUT"
    except:
        pass

    return random.choice(["CALL", "PUT"])


async def generate_signal(asset, expiry):
    """Полная генерация сигнала"""
    price = get_price(asset)
    ai_result = await ai_predict(asset, expiry, price)

    signal = "Покупка" if ai_result == "CALL" else "Продажа"
    emoji = "🟢" if ai_result == "CALL" else "🔴"

    pair_name = dict(PAIRS).get(asset, asset)

    # Сохраняем
    db.add_signal(pair_name, signal, price, expiry)

    return {
        'asset': asset,
        'pair_name': pair_name,
        'price': price,
        'expiry': expiry,
        'signal': signal,
        'emoji': emoji,
        'time': datetime.now().strftime('%H:%M:%S')
    }


def format_signal(data):
    """Форматирование сообщения"""
    return (
        f"✦ <b>ТОРГОВЫЙ СИГНАЛ</b> ✦\n\n"
        f"📊 Пара: <b>{data['pair_name']}</b>\n"
        f"💰 Цена: <b>{data['price']}</b>\n"
        f"⏱ Время: <b>{data['expiry']}</b>\n"
        f"🕒 Сформирован: <b>{data['time']}</b>\n\n"
        f"{data['emoji']} <b>{data['signal'].upper()}</b>\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🤖 AI: DeepSeek\n"
        f"⚠️ Торгуйте ответственно"
    )


# ========== TELEGRAM BOT ==========
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# --- /start ---
@dp.message(Command("start"))
async def start(msg: types.Message, state: FSMContext):
    await state.clear()

    user = msg.from_user
    is_vip = db.is_vip(user.id)

    text = (
        f"🤖 <b>Trading AI Assistant PRO</b>\n\n"
        f"👋 Привет, {user.first_name}!\n\n"
        f"Я помогаю анализировать рынок\n"
        f"и генерирую торговые сигналы.\n\n"
    )

    if not is_vip:
        text += (
            f"⚠️ <b>У вас нет VIP доступа</b>\n"
            f"Обратитесь к администратору.\n\n"
            f"Ваш ID: <code>{user.id}</code>"
        )
        await msg.answer(text, parse_mode="HTML")
        return

    text += f"✅ VIP статус активен\n\nИспользуйте меню ниже:"
    await msg.answer(text, reply_markup=main_menu(), parse_mode="HTML")


# --- /admin ---
@dp.message(Command("admin"))
async def admin(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return

    text = (
        f"🔐 <b>Админ-панель</b>\n\n"
        f"VIP: {len(db.vip_users)}\n"
        f"Авто: {len(db.auto_users)}\n"
        f"Сигналов: {db.stats['total']}\n\n"
        f"<b>Команды:</b>\n"
        f"/add [ID] - добавить VIP\n"
        f"/del [ID] - удалить VIP\n"
        f"/list - список VIP"
    )
    await msg.answer(text, parse_mode="HTML")


@dp.message(Command("add"))
async def add_vip(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        uid = int(msg.text.split()[1])
        db.add_vip(uid)
        await msg.answer(f"✅ VIP добавлен: {uid}")
    except:
        await msg.answer("Использование: /add 123456789")


@dp.message(Command("del"))
async def del_vip(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    try:
        uid = int(msg.text.split()[1])
        db.remove_vip(uid)
        await msg.answer(f"✅ VIP удалён: {uid}")
    except:
        await msg.answer("Использование: /del 123456789")


@dp.message(Command("list"))
async def list_vip(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return

    if not db.vip_users:
        await msg.answer("Список VIP пуст")
        return

    text = "👥 <b>VIP пользователи:</b>\n\n"
    for uid in db.vip_users:
        text += f"• <code>{uid}</code>\n"

    await msg.answer(text, parse_mode="HTML")


# --- Новый сигнал ---
@dp.message(F.text == "🚀 Новый сигнал")
async def new_signal(msg: types.Message, state: FSMContext):
    if not db.is_vip(msg.from_user.id):
        await msg.answer("⚠️ Доступ только для VIP")
        return

    await msg.answer(
        "📊 <b>Выберите валютную пару:</b>",
        reply_markup=pairs_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(TradeFlow.choosing_pair)


# --- Статистика ---
@dp.message(F.text == "📊 Статистика")
async def stats(msg: types.Message):
    total = db.stats['total']
    buy = db.stats['buy']
    sell = db.stats['sell']

    buy_pct = round(buy / total * 100, 1) if total > 0 else 0
    sell_pct = round(sell / total * 100, 1) if total > 0 else 0

    text = (
        f"📊 <b>Статистика</b>\n\n"
        f"Всего сигналов: <b>{total}</b>\n\n"
        f"🟢 Покупка: {buy} ({buy_pct}%)\n"
        f"🔴 Продажа: {sell} ({sell_pct}%)"
    )
    await msg.answer(text, parse_mode="HTML")


# --- История ---
@dp.message(F.text == "📜 История")
async def history(msg: types.Message):
    hist = db.get_history(10)

    if not hist:
        await msg.answer("📜 История пуста")
        return

    text = "📜 <b>Последние 10 сигналов:</b>\n\n"
    for i, s in enumerate(hist, 1):
        emoji = "🟢" if s['signal'] == 'Покупка' else "🔴"
        text += f"{i}. {emoji} <b>{s['asset']}</b> - {s['signal']}\n"
        text += f"   💰 {s['price']} | ⏱ {s['expiry']} | 🕒 {s['time']}\n\n"

    await msg.answer(text, parse_mode="HTML")


# --- Авто-сигналы ---
@dp.message(F.text == "⏰ Авто-сигналы")
async def auto_menu(msg: types.Message):
    if not db.is_vip(msg.from_user.id):
        await msg.answer("⚠️ Доступ только для VIP")
        return

    is_on = msg.from_user.id in db.auto_users
    status = "✅ Включены" if is_on else "❌ Выключены"

    text = (
        f"⏰ <b>Авто-сигналы</b>\n\n"
        f"Статус: <b>{status}</b>\n\n"
        f"Бот будет присылать сигналы\n"
        f"каждые 5 минут автоматически."
    )

    await msg.answer(text, reply_markup=auto_toggle(is_on), parse_mode="HTML")


# --- Информация ---
@dp.message(F.text == "ℹ️ Информация")
async def info(msg: types.Message):
    user = msg.from_user
    is_vip = db.is_vip(user.id)

    text = (
        f"ℹ️ <b>Информация</b>\n\n"
        f"ID: <code>{user.id}</code>\n"
        f"Имя: {user.first_name}\n"
        f"VIP: {'✅' if is_vip else '❌'}\n\n"
        f"Версия: 3.0 PRO\n"
        f"AI: DeepSeek"
    )
    await msg.answer(text, parse_mode="HTML")


# --- Callback: Выбор пары ---
@dp.callback_query(F.data.startswith("p_"))
async def cb_pair(cb: types.CallbackQuery, state: FSMContext):
    asset = cb.data[2:]
    await state.update_data(asset=asset)

    pair_name = dict(PAIRS).get(asset, asset)

    await cb.message.edit_text(
        f"✅ <b>{pair_name}</b>\n\nВыберите экспирацию:",
        reply_markup=expiry_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(TradeFlow.choosing_expiry)
    await cb.answer()


# --- Callback: Выбор времени ---
@dp.callback_query(F.data.startswith("e_"))
async def cb_expiry(cb: types.CallbackQuery, state: FSMContext):
    expiry = cb.data[2:]
    data = await state.get_data()
    asset = data.get('asset', 'EURUSD')

    await cb.message.edit_text("⏳ Генерирую сигнал...")

    signal = await generate_signal(asset, expiry)

    await cb.message.edit_text(
        format_signal(signal),
        reply_markup=signal_actions(asset),
        parse_mode="HTML"
    )

    await state.clear()
    await cb.answer()


# --- Callback: Повторить ---
@dp.callback_query(F.data.startswith("repeat_"))
async def cb_repeat(cb: types.CallbackQuery):
    asset = cb.data[7:]

    await cb.message.edit_text("🔄 Обновляю прогноз...")

    signal = await generate_signal(asset, "5 мин")

    await cb.message.edit_text(
        format_signal(signal),
        reply_markup=signal_actions(asset),
        parse_mode="HTML"
    )
    await cb.answer("🔄 Обновлено!")


# --- Callback: Новый сигнал ---
@dp.callback_query(F.data == "new")
async def cb_new(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.edit_text(
        "📊 Выберите пару:",
        reply_markup=pairs_keyboard()
    )
    await state.set_state(TradeFlow.choosing_pair)
    await cb.answer()


# --- Callback: Назад ---
@dp.callback_query(F.data == "back")
async def cb_back(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.edit_text(
        "📊 Выберите пару:",
        reply_markup=pairs_keyboard()
    )
    await state.set_state(TradeFlow.choosing_pair)
    await cb.answer()


# --- Callback: Переключатель авто ---
@dp.callback_query(F.data == "auto_toggle")
async def cb_auto_toggle(cb: types.CallbackQuery):
    uid = cb.from_user.id

    if uid in db.auto_users:
        db.auto_users.discard(uid)
        status = "❌ Выключены"
        is_on = False
    else:
        db.auto_users.add(uid)
        status = "✅ Включены"
        is_on = True

    db.save_data()

    await cb.message.edit_text(
        f"⏰ <b>Авто-сигналы</b>\n\nСтатус: <b>{status}</b>",
        reply_markup=auto_toggle(is_on),
        parse_mode="HTML"
    )
    await cb.answer(status)


# ========== АВТО-СИГНАЛЫ ==========
async def auto_sender():
    """Фоновая задача отправки авто-сигналов"""
    while True:
        await asyncio.sleep(AUTO_SIGNAL_INTERVAL)

        if not db.auto_users:
            continue

        # Случайная пара
        asset, pair_name = random.choice(PAIRS)
        signal = await generate_signal(asset, "5 мин")

        text = f"⏰ <b>АВТО-СИГНАЛ</b>\n\n{format_signal(signal)}"

        # Отправка всем
        for uid in list(db.auto_users):
            try:
                await bot.send_message(uid, text, parse_mode="HTML")
            except:
                db.auto_users.discard(uid)

        db.save_data()
        logging.info(f"📤 Авто-сигнал → {len(db.auto_users)} чел.")


# ========== ЗАПУСК ==========
async def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(message)s'
    )

    logging.info("=" * 50)
    logging.info("🚀 Trading AI Bot PRO v3.0")
    logging.info("=" * 50)

    await bot.delete_webhook(drop_pending_updates=True)

    me = await bot.get_me()
    logging.info(f"✓ Бот: @{me.username}")
    logging.info(f"✓ VIP: {len(db.vip_users)} чел.")
    logging.info(f"✓ Авто: {len(db.auto_users)} чел.")
    logging.info("=" * 50)

    # Запуск авто-сигналов
    asyncio.create_task(auto_sender())

    logging.info("🤖 Бот запущен!")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("🛑 Остановлен")