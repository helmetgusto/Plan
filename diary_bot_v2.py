import asyncio
import logging
import json
import os
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы
DAYS_OF_WEEK = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
DAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
DEFAULT_TIMEZONE = "Asia/Irkutsk"
SUMMARY_TIME = "23:59"
MAIN_MENU_KEYBOARD = [
    ["📋 Настроить планы", "🌍 Глобальные планы"],
    ["Мои планы", "🌐 Часовой пояс"],
]

# Файлы для хранения данных
USERS_FILE = "users_data.json"
GLOBAL_PLANS_FILE = "global_plans.json"

# Состояния для ConversationHandler
(MAIN_MENU, SETUP_PLANS, CHOOSING_DAY, ENTERING_PLANS, REVIEW_PLANS, 
 GLOBAL_MENU, ENTERING_GLOBAL_PLANS, REVIEWING_GLOBAL, ITOG_REVIEW) = range(9)

def get_timezone_offset_label(tz_name: str) -> str:
    """Вернуть строку UTC-смещения для отображения"""
    try:
        now_in_tz = datetime.now(ZoneInfo(tz_name))
        offset = now_in_tz.utcoffset()
        if offset is None:
            return tz_name
        total_minutes = int(offset.total_seconds() // 60)
        hours, minutes = divmod(abs(total_minutes), 60)
        sign = "+" if total_minutes >= 0 else "-"
        return f"UTC{sign}{hours:02d}:{minutes:02d}"
    except Exception:
        return tz_name

def get_user_timezone(user: dict) -> str:
    """Вернуть часовой пояс пользователя (по умолчанию Иркутск)"""
    return user.get("timezone", DEFAULT_TIMEZONE)

def get_user_now(user: dict) -> datetime:
    """Текущее время пользователя"""
    try:
        return datetime.now(ZoneInfo(get_user_timezone(user)))
    except Exception:
        return datetime.now()

async def cleanup_user_message(update: Update):
    """Удалить сообщение пользователя после нажатия кнопки/команды"""
    message = getattr(update, "message", None)
    if not message:
        return
    try:
        await message.delete()
    except Exception as error:
        logger.debug(f"Не удалось удалить сообщение: {error}")

async def prompt_notification_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Попросить указать время уведомлений"""
    context.user_data['waiting_for_time'] = True
    offset_label = get_timezone_offset_label(DEFAULT_TIMEZONE)
    users = load_users()
    text = (
        f"⏰ Во сколько напоминать о планах? (ваш пояс: {offset_label})\n"
        "Напиши время в формате ЧЧ:ММ, например 09:00."
    )
    await send_and_replace(
        update,
        users,
        text,
        ReplyKeyboardRemove(),
    )

async def ensure_notification_time(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict) -> bool:
    """Проверяет, нужно ли запросить время уведомлений. Возвращает True, если запрос отправлен."""
    if not user.get("notification_time"):
        if not context.user_data.get('waiting_for_time'):
            await prompt_notification_time(update, context)
        return True
    return False

# ========== РАБОТА С ФАЙЛАМИ ==========

def load_users():
    """Загрузить данные пользователей"""
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_users(users):
    """Сохранить данные пользователей"""
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def load_global_plans():
    """Загрузить глобальные планы"""
    if os.path.exists(GLOBAL_PLANS_FILE):
        with open(GLOBAL_PLANS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_global_plans(plans):
    """Сохранить глобальные планы"""
    with open(GLOBAL_PLANS_FILE, 'w', encoding='utf-8') as f:
        json.dump(plans, f, ensure_ascii=False, indent=2)

# ========== ОСНОВНЫЕ ФУНКЦИИ ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Команда /start - приветствие"""
    await cleanup_user_message(update)
    user_id = str(update.effective_user.id)
    users = load_users()
    
    if user_id not in users:
        users[user_id] = {
            "name": update.effective_user.first_name,
            "timezone": DEFAULT_TIMEZONE,
            "notification_time": None,
            "plans": {day: [] for day in DAYS_OF_WEEK},
            "setup_complete": False,
            "last_message_id": None,
            "last_summary_date": None,
            "itog_state": None,
            "last_bot_message_id": None,
            "last_bot_message_chat_id": None,
        }
    else:
        users[user_id].setdefault("timezone", DEFAULT_TIMEZONE)
        users[user_id].setdefault("notification_time", None)
        users[user_id].setdefault("plans", {day: [] for day in DAYS_OF_WEEK})
        users[user_id].setdefault("setup_complete", False)
        users[user_id].setdefault("last_message_id", None)
        users[user_id].setdefault("last_summary_date", None)
        users[user_id].setdefault("itog_state", None)
        users[user_id].setdefault("last_bot_message_id", None)
        users[user_id].setdefault("last_bot_message_chat_id", None)
    
    save_users(users)
    user = users[user_id]
    
    welcome_text = (
        f"🎯 Привет, {update.effective_user.first_name}!\n\n"
        "Я твой персональный дневник-планировщик. Утром помогаю сфокусироваться, "
        "вечером — мягко подвожу к подведению итогов.\n\n"
        "✨ Что я умею:\n"
        "• напомнить утром о планах и показать глобальные ориентиры;\n"
        "• бережно провести через подведение итогов командой /itog;\n"
        "• подсказать планы за любой день командой /day ДД.ММ.ГГГГ.\n\n"
        "⏰ Командой /plan можно обновить расписание в любой момент.\n"
        "💬 Необязательно заполнять все дни сразу — бери только то, что действительно важно.\n\n"
        "Готов начать?"
    )
    
    reply_markup = ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True)
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    await ensure_notification_time(update, context, user)
    return MAIN_MENU

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Главное меню"""
    await cleanup_user_message(update)
    user_id = str(update.effective_user.id)
    users = load_users()
    user = users.get(user_id, {})
    
    if context.user_data.get('waiting_for_time'):
        return await handle_time_input(update, context)
    
    if context.user_data.get("choosing_timezone"):
        tz = update.message.text.strip()
        if tz in TIMEZONES:
            if user_id in users:
                users[user_id]["timezone"] = tz
                save_users(users)
            context.user_data["choosing_timezone"] = False
            await send_and_replace(
                update,
                users,
                f"✅ Часовой пояс обновлён: {tz} ({get_timezone_offset_label(tz)}).",
                ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True),
            )
            return MAIN_MENU
        buttons = [[zone] for zone in TIMEZONES]
        reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
        await send_and_replace(
            update,
            users,
            "❌ Не узнал этот часовой пояс. Выбери вариант с клавиатуры:",
            reply_markup,
        )
        return MAIN_MENU
    
    if update.message.text == "📋 Настроить планы":
        return await setup_plans(update, context)
    elif update.message.text == "🌍 Глобальные планы":
        return await global_plans_menu(update, context)
    elif update.message.text == "Мои планы":
        await show_weekly_plans(update, user, users)
        return MAIN_MENU
    elif update.message.text == "🌐 Часовой пояс":
        return await timezone_command(update, context)
    
    reply_markup = ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True)
    await send_and_replace(update, users, "Выбери, чем займёмся дальше:", reply_markup)
    return MAIN_MENU

async def plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Команда /plan для быстрого перехода к настройке"""
    await cleanup_user_message(update)
    return await setup_plans(update, context)

async def day_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /day для просмотра планов/итогов по дате"""
    await cleanup_user_message(update)
    user_id = str(update.effective_user.id)
    users = load_users()
    user = users.get(user_id)
    
    if not user:
        await send_and_replace(update, users, "Сначала нажми /start — так мы успеем познакомиться 😉")
        return
    
    if not context.args:
        await send_and_replace(update, users, "Напиши дату в формате ДД.ММ.ГГГГ, например /day 12.05.2025")
        return
    
    date_text = context.args[0]
    try:
        target_date = datetime.strptime(date_text, "%d.%m.%Y")
    except ValueError:
        await send_and_replace(update, users, "❌ Хочется видеть дату вроде 12.05.2025 — попробуй ещё раз 🙂")
        return
    
    day_name = DAYS_OF_WEEK[target_date.weekday()]
    day_plans = user.get('plans', {}).get(day_name, [])
    global_plans = load_global_plans().get(user_id, [])
    
    message_parts = [
        f"📅 {date_text} — {day_name}",
        "",
    ]
    
    if day_plans:
        message_parts.append("📋 План на день:")
        message_parts.extend([f"• {format_plan_line(plan)}" for plan in day_plans])
    else:
        message_parts.append("📋 Пока ничего не записано — можно заполнить через /plan.")
    
    if global_plans:
        message_parts.append("")
        message_parts.append("🌍 Глобальные ориентиры:")
        message_parts.extend([f"• {plan}" for plan in global_plans])
    
    await send_and_replace(update, users, "\n".join(message_parts))

def format_weekly_plans_text(user: dict) -> str:
    """Сформировать текст плана на неделю"""
    plans = user.get('plans', {})
    lines = ["🗓️ Твоя неделя на ладони:", ""]
    
    for day in DAYS_OF_WEEK:
        day_plans = plans.get(day, [])
        if day_plans:
            lines.append(f"{day}:")
            lines.append("\n".join([f"   • {format_plan_line(p)}" for p in day_plans]))
        else:
            lines.append(f"{day}: — отдых или спонтанность")
        lines.append("")
    
    return "\n".join(lines).strip()

def escape_html(text: str) -> str:
    """Экранировать html для сообщений"""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

def format_plan_line(plan) -> str:
    """Вернуть строку для отображения плана (с учётом времени)"""
    if isinstance(plan, dict):
        text = plan.get("text", "")
        if plan.get("time"):
            return f"{plan['time']} — {text}"
        return text
    return str(plan)

async def show_weekly_plans(update: Update, user: dict, users: dict):
    """Отправить пользователю планы на неделю"""
    if not user:
        await send_and_replace(
            update,
            users,
            "Сначала запусти /start — так я узнаю твои планы 😉",
            ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True),
        )
        return
    
    text = format_weekly_plans_text(user)
    await send_and_replace(
        update,
        users,
        text,
        ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True),
    )

def build_itog_list_text(day_name: str, date_text: str, plans: list, completed: set[int]) -> str:
    """Сформировать текст для списка планов при итогах"""
    lines = [f"📘 Итоговый чек-лист: {date_text} • {day_name}", ""]
    
    if not plans:
        lines.append("На сегодня планов нет.")
    else:
        for idx, plan in enumerate(plans):
            plan_text = escape_html(format_plan_line(plan))
            if idx in completed:
                plan_text = f"<s>{plan_text}</s>"
            lines.append(f"{idx + 1}. {plan_text}")
    
    if plans:
        lines.extend(["", "Жми «Да» или «Нет» для каждого пункта ниже."])
    
    return "\n".join(lines)

async def delete_message_safe(bot, chat_id: str, message_id: Optional[int]):
    """Безопасно удалить сообщение"""
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as error:
        logger.debug(f"Не удалось удалить сообщение {message_id} в чате {chat_id}: {error}")

async def send_and_replace(
    update: Update,
    users: dict,
    text: str,
    reply_markup: ReplyKeyboardMarkup | ReplyKeyboardRemove | None = None,
):
    """Отправить новое сообщение и удалить предыдущее сообщение бота для пользователя."""
    message = getattr(update, "message", None)
    chat = update.effective_chat
    user_id = str(update.effective_user.id)
    user = users.get(user_id, {})

    last_id = user.get("last_bot_message_id")
    last_chat = user.get("last_bot_message_chat_id")
    if last_id and last_chat:
        try:
            await update.get_bot().delete_message(chat_id=last_chat, message_id=last_id)
        except Exception as error:
            logger.debug(f"Не удалось удалить прошлое сообщение бота {last_id}: {error}")

    if message:
        msg = await message.reply_text(text, reply_markup=reply_markup)
    elif chat:
        msg = await chat.send_message(text, reply_markup=reply_markup)
    else:
        return None

    user["last_bot_message_id"] = msg.message_id
    user["last_bot_message_chat_id"] = msg.chat_id
    users[user_id] = user
    save_users(users)
    return msg

async def send_itog_question(bot, chat_id: str, plan_text: str, index: int) -> int:
    """Отправить вопрос по конкретному пункту плана"""
    keyboard = ReplyKeyboardMarkup([["Да", "Нет"]], resize_keyboard=True)
    msg = await bot.send_message(
        chat_id=chat_id,
        text=f"Как прошёл пункт {index + 1}?\n\n{plan_text}",
        reply_markup=keyboard
    )
    return msg.message_id

async def update_itog_list_message(bot, chat_id: str, state: dict):
    """Обновить список планов с зачёркнутыми пунктами"""
    list_message_id = state.get("list_message_id")
    if not list_message_id:
        return
    plans = state.get("plans", [])
    day_name = state.get("day_name", "")
    date_text = state.get("date", "")
    completed = set(state.get("completed", []))
    text = build_itog_list_text(day_name, date_text, plans, completed)
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=list_message_id,
            text=text,
            parse_mode='HTML'
        )
    except Exception as error:
        logger.debug(f"Не удалось обновить список итогов для {chat_id}: {error}")

async def cleanup_itog_state(bot, user_id: str, state: dict, keep_list: bool = False):
    """Удалить служебные сообщения предыдущего режима итогов"""
    await delete_message_safe(bot, user_id, state.get("question_message_id"))
    if not keep_list:
        await delete_message_safe(bot, user_id, state.get("list_message_id"))

def apply_itog_results_to_plans(user: dict, state: dict):
    """Удалить выполненные пункты из планов пользователя"""
    day_name = state.get("day_name")
    snapshot = state.get("plans", [])
    completed = set(state.get("completed", []))
    
    if not day_name or not snapshot or not completed:
        return
    
    remaining = [plan for idx, plan in enumerate(snapshot) if idx not in completed]
    user.setdefault("plans", {})[day_name] = remaining

async def start_itog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Команда /itog - начало подведения итогов"""
    await cleanup_user_message(update)
    user_id = str(update.effective_user.id)
    users = load_users()
    user = users.get(user_id)
    
    if not user:
        await send_and_replace(update, users, "Сначала запусти /start, чтобы я знал о тебе 😉")
        return MAIN_MENU
    
    today = get_user_now(user)
    day_name = DAYS_OF_WEEK[today.weekday()]
    today_plans = list(user.get('plans', {}).get(day_name, []))
    date_text = today.strftime("%d.%m.%Y")
    
    if not today_plans:
        await send_and_replace(update, users, "Похоже, на сегодня записей нет. Добавь их командой /plan, и я вернусь к итогам позже.")
        return MAIN_MENU
    
    if user.get("itog_state"):
        await cleanup_itog_state(context.bot, user_id, user["itog_state"])
    
    list_text = build_itog_list_text(day_name, date_text, today_plans, set())
    list_msg = await update.message.reply_text(list_text, parse_mode='HTML')
    question_id = await send_itog_question(context.bot, user_id, format_plan_line(today_plans[0]), 0)
    
    user['itog_state'] = {
        "date": date_text,
        "day_name": day_name,
        "plans": today_plans,
        "current_index": 0,
        "completed": [],
        "list_message_id": list_msg.message_id,
        "question_message_id": question_id,
    }
    users[user_id] = user
    save_users(users)
    return ITOG_REVIEW

async def handle_itog_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка ответов Да/Нет в режиме итогов"""
    await cleanup_user_message(update)
    user_id = str(update.effective_user.id)
    users = load_users()
    user = users.get(user_id)
    
    if not user or not user.get("itog_state"):
        await send_and_replace(update, users, "Сейчас итоги не активны. Нажми /itog, чтобы начать заново.")
        return MAIN_MENU
    
    state = user["itog_state"]
    plans = state.get("plans", [])
    
    if not plans:
        user["itog_state"] = None
        users[user_id] = user
        save_users(users)
        await send_and_replace(update, users, "Похоже, планов нет. Возвращаю в меню.")
        return MAIN_MENU
    
    current_index = state.get("current_index", 0)
    if current_index >= len(plans):
        await cleanup_itog_state(context.bot, user_id, state, keep_list=True)
        apply_itog_results_to_plans(user, state)
        user["itog_state"] = None
        users[user_id] = user
        save_users(users)
        reply_markup = ReplyKeyboardRemove()
        await send_and_replace(update, users, "Все пункты уже разобрали 🙌", reply_markup)
        menu_markup = ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True)
        await send_and_replace(update, users, "Чем займёмся дальше?", menu_markup)
        return MAIN_MENU
    
    answer = update.message.text.strip().lower()
    await delete_message_safe(context.bot, user_id, state.get("question_message_id"))
    
    if answer == "да":
        completed = set(state.get("completed", []))
        completed.add(current_index)
        state["completed"] = list(completed)
        await update_itog_list_message(context.bot, user_id, state)
    
    state["current_index"] = current_index + 1
    
    if state["current_index"] >= len(plans):
        apply_itog_results_to_plans(user, state)
        user["itog_state"] = None
        users[user_id] = user
        save_users(users)
        
        completed_count = len(state.get("completed", []))
        total = len(plans)
        reply_markup = ReplyKeyboardRemove()
        await send_and_replace(
            update,
            users,
            f"✅ Готово! Выполнено {completed_count} из {total}. Горжусь твоим прогрессом.",
            reply_markup,
        )
        menu_markup = ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True)
        await send_and_replace(update, users, "Верну тебя в главное меню:", menu_markup)
        return MAIN_MENU
    
    next_index = state["current_index"]
    next_question_id = await send_itog_question(
        context.bot,
        user_id,
        format_plan_line(plans[next_index]),
        next_index
    )
    state["question_message_id"] = next_question_id
    user["itog_state"] = state
    users[user_id] = user
    save_users(users)
    return ITOG_REVIEW

async def setup_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало настройки планов"""
    user_id = str(update.effective_user.id)
    users = load_users()
    context.user_data['setup_day'] = 0
    context.user_data['action'] = 'replace'
    context.user_data['deleting_day'] = False
    
    keyboard = [[day] for day in DAYS_SHORT]
    keyboard.append(["⏭️ Пропустить все"])
    keyboard.append(["🗑️ Удалить планы на день"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    
    await send_and_replace(
        update,
        users,
        "📅 С какого дня начнём? Можно отметить только те дни, которые сейчас важны. Остальные успеем позже ✨",
        reply_markup
    )
    return CHOOSING_DAY

async def choose_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор дня недели"""
    await cleanup_user_message(update)
    user_id = str(update.effective_user.id)
    users = load_users()
    text = update.message.text.strip()
    
    # Пропуск всех дней
    if text == "⏭️ Пропустить все":
        users[user_id]['setup_complete'] = True
        save_users(users)
        
        reply_markup = ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True)
        await send_and_replace(
            update,
            users,
            "👌 Оставляем всё, как есть. Если понадобится — вернись ко мне /plan.\n\nГлавное меню:",
            reply_markup
        )
        await ensure_notification_time(update, context, users[user_id])
        return MAIN_MENU
    
    if text == "✅ Готово":
        users[user_id]['setup_complete'] = True
        save_users(users)
        reply_markup = ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True)
        await send_and_replace(
            update,
            users,
            "✅ Отлично! Планы сохранены. Возвращаю в меню.",
            reply_markup
        )
        await ensure_notification_time(update, context, users[user_id])
        return MAIN_MENU
    
    if text == "🗑️ Удалить планы на день":
        keyboard = [[day] for day in DAYS_SHORT]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await send_and_replace(
            update,
            users,
            "Выбери день, у которого нужно полностью удалить планы:",
            reply_markup,
        )
        context.user_data["deleting_day"] = True
        return CHOOSING_DAY
    
    # Режим удаления планов
    if context.user_data.get("deleting_day"):
        day_index = None
        for i, day_short in enumerate(DAYS_SHORT):
            if text == day_short:
                day_index = i
                break
        if day_index is None:
            await send_and_replace(update, users, "❌ Выбери день недели с клавиатуры.")
            return CHOOSING_DAY
        day_name = DAYS_OF_WEEK[day_index]
        users[user_id]['plans'][day_name] = []
        save_users(users)
        context.user_data["deleting_day"] = False
        reply_markup = ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True)
        await send_and_replace(
            update,
            users,
            f"🗑️ Все планы на {day_name} удалены.",
            reply_markup,
        )
        return MAIN_MENU
    
    # Найти день по короткому названию
    day_index = None
    for i, day_short in enumerate(DAYS_SHORT):
        if text == day_short:
            day_index = i
            break
    
    if day_index is None:
        await send_and_replace(update, users, "❌ Выбери, пожалуйста, день из списка на клавиатуре.")
        return CHOOSING_DAY
    
    context.user_data['current_day'] = DAYS_OF_WEEK[day_index]
    context.user_data['day_index'] = day_index
    context.user_data['skip_day'] = False
    
    keyboard = [["⏭️ Пропустить день"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await send_and_replace(
        update,
        users,
        f"📝 {DAYS_OF_WEEK[day_index]}\n\nПеречисли планы через точку с запятой (;).\n"
        "Пример: сходить погулять; купить молоко; позвонить другу",
        reply_markup
    )
    return ENTERING_PLANS

async def enter_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ввод планов"""
    await cleanup_user_message(update)
    user_id = str(update.effective_user.id)
    users = load_users()
    text = update.message.text.strip()
    
    # Отмена
    if text == "❌ Отмена":
        reply_markup = ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True)
        await send_and_replace(update, users, "Окей, отменяем. Вот меню:", reply_markup)
        return MAIN_MENU
    
    # Пропуск дня
    if text == "⏭️ Пропустить день":
        context.user_data['current_plans'] = None
        context.user_data['skip_day'] = True
    else:
        # Парсим планы: "08:00 сделать зарядку; позвонить другу"
        raw_items = [item.strip() for item in text.split(';') if item.strip()]
        plans = []
        for item in raw_items:
            parts = item.split(maxsplit=1)
            if (
                len(parts) == 2
                and len(parts[0]) == 5
                and parts[0][2] == ':'
                and parts[0][:2].isdigit()
                and parts[0][3:].isdigit()
            ):
                hh = int(parts[0][:2])
                mm = int(parts[0][3:])
                if 0 <= hh <= 23 and 0 <= mm <= 59:
                    plans.append({"time": parts[0], "text": parts[1]})
                    continue
            # без времени
            plans.append({"time": None, "text": item})
        context.user_data['current_plans'] = plans
        context.user_data['skip_day'] = False
    
    return await review_plans(update, context)

async def review_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Проверка и подтверждение планов"""
    user_id = str(update.effective_user.id)
    users = load_users()
    
    current_day = context.user_data.get('current_day')
    plans = context.user_data.get('current_plans', [])
    skip_day = context.user_data.get('skip_day', False)
    
    # Форматируем планы для отображения
    if skip_day:
        existing_plans = users[user_id]['plans'].get(current_day, [])
        if existing_plans:
            plans_text = "\n".join([f"{i+1}. {format_plan_line(plan)}" for i, plan in enumerate(existing_plans)])
            plans_text = "Оставляем без изменений:\n" + plans_text
        else:
            plans_text = "Этот день пока останется свободным."
    elif plans:
        plans_text = "\n".join([f"{i+1}. {format_plan_line(plan)}" for i, plan in enumerate(plans)])
    else:
        plans_text = "Этот день пока без записей."
    
    review_message = (
        f"✅ Всё готово для {current_day}!\n\n"
        f"{plans_text}\n\n"
        "Нужно что-нибудь подправить или идём дальше?"
    )
    
    keyboard = [
        ["➕ Дополнить", "✏️ Изменить"],
        ["➡️ Продолжить"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await send_and_replace(update, users, review_message, reply_markup)
    return REVIEW_PLANS

async def handle_review_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка действий после проверки"""
    await cleanup_user_message(update)
    user_id = str(update.effective_user.id)
    users = load_users()
    text = update.message.text.strip()
    
    if text == "➕ Дополнить":
        keyboard = [["❌ Отмена"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await send_and_replace(
            update,
            users,
            "Добавь пункты через точку с запятой. Я просто допишу их к текущему списку:",
            reply_markup
        )
        context.user_data['action'] = 'supplement'
        return ENTERING_PLANS
    
    elif text == "✏️ Изменить":
        keyboard = [["❌ Отмена"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await send_and_replace(
            update,
            users,
            "Введи планы заново (используй точку с запятой между пунктами):",
            reply_markup
        )
        context.user_data['action'] = 'replace'
        return ENTERING_PLANS
    
    elif text == "➡️ Продолжить":
        current_day = context.user_data.get('current_day')
        action = context.user_data.get('action', 'replace')
        plans = context.user_data.get('current_plans', [])
        skip_day = context.user_data.get('skip_day', False)
        
        if not skip_day:
            if action == 'supplement' and plans:
                users[user_id]['plans'][current_day].extend(plans)
            else:
                users[user_id]['plans'][current_day] = plans
        
        context.user_data['action'] = 'replace'
        context.user_data['skip_day'] = False
        day_index = context.user_data.get('day_index', 0)
        save_users(users)
        
        # После дня всегда показываем все дни + кнопки
        keyboard = [[day] for day in DAYS_SHORT]
        keyboard.append(["✅ Готово"])
        keyboard.append(["🗑️ Удалить планы на день"])
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
        await send_and_replace(
            update,
            users,
            f"✨ {current_day} готов. Можно выбрать следующий день, нажать «✅ Готово» "
            "или «🗑️ Удалить планы на день».",
            reply_markup
        )
        return CHOOSING_DAY
    
    save_users(users)
    return REVIEW_PLANS

async def handle_time_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка ввода времени уведомления"""
    user_id = str(update.effective_user.id)
    users = load_users()
    text = update.message.text.strip()
    
    if context.user_data.get('waiting_for_time'):
        # Проверяем формат времени
        try:
            parts = text.split(':')
            if len(parts) != 2:
                raise ValueError
            hour = int(parts[0])
            minute = int(parts[1])
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
            
            users[user_id]['notification_time'] = f"{hour:02d}:{minute:02d}"
            save_users(users)
            context.user_data['waiting_for_time'] = False
            
            reply_markup = ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True)
            tz_name = get_user_timezone(users[user_id])
            
            await send_and_replace(
                update,
                users,
                f"✅ Отлично! Теперь я буду писать в {users[user_id]['notification_time']} "
                f"({get_timezone_offset_label(tz_name)}).\n\nЧем займёмся дальше?",
                reply_markup
            )
            return MAIN_MENU
        
        except (ValueError, IndexError):
            await send_and_replace(
                update,
                users,
                "❌ Не получилось прочитать время. Нужен формат ЧЧ:ММ, например 09:00."
            )
            return MAIN_MENU
    
    reply_markup = ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True)
    await send_and_replace(update, users, "Главное меню:", reply_markup)
    return MAIN_MENU

TIMEZONES = [
    "Asia/Irkutsk",
    "Europe/Moscow",
    "Europe/Kaliningrad",
    "Asia/Yekaterinburg",
    "Asia/Krasnoyarsk",
    "Asia/Vladivostok",
]

async def timezone_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор часового пояса"""
    await cleanup_user_message(update)
    user_id = str(update.effective_user.id)
    users = load_users()
    user = users.get(user_id)
    
    if not user:
        await send_and_replace(update, users, "Сначала запусти /start 😉")
        return MAIN_MENU
    
    buttons = [[tz] for tz in TIMEZONES]
    reply_markup = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
    
    await send_and_replace(
        update,
        users,
        "Выбери свой часовой пояс (по названию региона):",
        reply_markup,
    )
    context.user_data["choosing_timezone"] = True
    return MAIN_MENU

# ========== ГЛОБАЛЬНЫЕ ПЛАНЫ ==========

async def global_plans_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Меню глобальных планов"""
    user_id = str(update.effective_user.id)
    users = load_users()
    global_plans = load_global_plans()
    user_plans = global_plans.get(user_id, [])
    
    if user_plans:
        plans_text = "\n".join([f"{i+1}. {plan}" for i, plan in enumerate(user_plans)])
        message = f"🌍 Твои глобальные ориентиры:\n\n{plans_text}"
    else:
        message = "🌍 Пока нет записей. Добавим пару больших целей?"
    
    keyboard = [
        ["➕ Добавить", "✏️ Редактировать"],
        ["🗑️ Удалить", "⬅️ Назад"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await send_and_replace(
        update,
        users,
        message + "\n\nВыбери действие:",
        reply_markup
    )
    return GLOBAL_MENU

async def handle_global_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка действий с глобальными планами"""
    await cleanup_user_message(update)
    text = update.message.text.strip()
    user_id = str(update.effective_user.id)
    users = load_users()
    
    if text == "➕ Добавить":
        await send_and_replace(
            update,
            users,
            "Перечисли глобальные планы через точку с запятой — я добавлю их к списку:",
            ReplyKeyboardRemove()
        )
        context.user_data['global_action'] = 'add'
        return ENTERING_GLOBAL_PLANS
    
    elif text == "✏️ Редактировать":
        await send_and_replace(
            update,
            users,
            "Напиши глобальные планы заново (они заменят предыдущие):",
            ReplyKeyboardRemove()
        )
        context.user_data['global_action'] = 'replace'
        return ENTERING_GLOBAL_PLANS
    
    elif text == "🗑️ Удалить":
        global_plans = load_global_plans()
        if user_id in global_plans:
            del global_plans[user_id]
            save_global_plans(global_plans)
            await send_and_replace(update, users, "✅ Глобальные планы очищены. Можно начать с чистого листа!")
        else:
            await send_and_replace(update, users, "❌ Пока нечего удалять — список пуст.")
        
        reply_markup = ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True)
        await send_and_replace(update, users, "Возвращаю в главное меню:", reply_markup)
        return MAIN_MENU
    
    elif text == "⬅️ Назад":
        reply_markup = ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True)
        await send_and_replace(update, users, "Главное меню открыто:", reply_markup)
        return MAIN_MENU
    
    return GLOBAL_MENU

async def enter_global_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ввод глобальных планов"""
    await cleanup_user_message(update)
    user_id = str(update.effective_user.id)
    users = load_users()
    global_plans = load_global_plans()
    text = update.message.text.strip()
    
    new_plans = [plan.strip() for plan in text.split(';') if plan.strip()]
    action = context.user_data.get('global_action', 'replace')
    
    if action == 'add':
        if user_id not in global_plans:
            global_plans[user_id] = []
        global_plans[user_id].extend(new_plans)
    else:
        global_plans[user_id] = new_plans
    
    save_global_plans(global_plans)
    
    reply_markup = ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True)
    
    await send_and_replace(
        update,
        users,
        "✅ Глобальные планы обновлены! Возвращаю тебя в меню.",
        reply_markup
    )
    return MAIN_MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена текущей операции"""
    await cleanup_user_message(update)
    users = load_users()
    reply_markup = ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True)
    await send_and_replace(update, users, "Операцию отменил. Вот меню:", reply_markup)
    return MAIN_MENU

# ========== ОТПРАВКА УВЕДОМЛЕНИЙ ==========

async def send_daily_notification(user_id: str, application):
    """Отправить ежедневное уведомление конкретному пользователю"""
    try:
        users = load_users()
        global_plans = load_global_plans()
        
        if user_id not in users:
            return
        
        user_data = users[user_id]
        
        today_dt = get_user_now(user_data)
        today_name = DAYS_OF_WEEK[today_dt.weekday()]
        
        plans = user_data['plans'].get(today_name, [])
        user_global = global_plans.get(user_id, [])
        
        # Формируем сообщение
        message_lines = [
            f"🌞 {today_name}, {today_dt.strftime('%d.%m')}",
            "",
            "Вот, что у тебя в фокусе сегодня:",
            "",
        ]
        
        if plans:
            message_lines.append("📋 Ежедневные задачи:")
            message_lines.extend([f"• {format_plan_line(plan)}" for plan in plans])
        else:
            message_lines.append("📋 Ежедневные планы не записаны — можно добавить через /plan.")
        
        if user_global:
            message_lines.extend([
                "",
                "🌍 Глобальные ориентиры:",
            ])
            message_lines.extend([f"• {plan}" for plan in user_global])
        
        message = "\n".join(message_lines)
        
        # Удаляем старое сообщение, если оно есть
        if user_data.get('last_message_id'):
            try:
                await application.bot.delete_message(
                    chat_id=user_id,
                    message_id=user_data['last_message_id']
                )
            except Exception as e:
                logger.warning(f"Не удалось удалить старое сообщение для {user_id}: {e}")
        
        # Отправляем новое сообщение
        msg = await application.bot.send_message(chat_id=user_id, text=message)
        
        # Сохраняем ID нового сообщения
        user_data['last_message_id'] = msg.message_id
        users[user_id] = user_data
        save_users(users)
        
        logger.info(f"Уведомление отправлено пользователю {user_id}")
        
    except Exception as e:
        logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")

async def send_daily_summary(user_id: str, application):
    """Отправить напоминание подвести итоги дня"""
    try:
        users = load_users()
        if user_id not in users:
            return
        
        user_data = users[user_id]
        today = get_user_now(user_data)
        day_name = DAYS_OF_WEEK[today.weekday()]
        date_text = today.strftime("%d.%m.%Y")
        plans = user_data.get('plans', {}).get(day_name, [])
        
        lines = [
            f"🌙 {date_text} • {day_name}",
            "",
            "Самое время мягко подвести итоги дня ✨",
            "",
        ]
        
        if plans:
            lines.append("Вот что было в планах:")
            lines.extend([f"• {format_plan_line(plan)}" for plan in plans])
        else:
            lines.append("Сегодня не было записанных задач — можно просто отметить настроение.")
        
        lines.extend([
            "",
            "Чтобы пройтись по каждому пункту вместе, нажми /itog."
        ])
        
        await application.bot.send_message(chat_id=user_id, text="\n".join(lines))
        
        user_data["last_summary_date"] = today.strftime("%Y-%m-%d")
        users[user_id] = user_data
        save_users(users)
        
        logger.info(f"Вечернее напоминание отправлено пользователю {user_id}")
    except Exception as e:
        logger.error(f"Ошибка при отправке итогового сообщения пользователю {user_id}: {e}")

async def notification_scheduler(application):
    """Проверяет каждую минуту, нужно ли отправить уведомления"""
    while True:
        try:
            users = load_users()
            
            for user_id, user_data in users.items():
                notification_time = user_data.get('notification_time') or '09:00'
                user_now = get_user_now(user_data)
                
                current_time = f"{user_now.hour:02d}:{user_now.minute:02d}"
                
                if current_time == notification_time and user_data.get('setup_complete'):
                    await send_daily_notification(user_id, application)
                
                today_name = DAYS_OF_WEEK[user_now.weekday()]
                day_plans = user_data.get('plans', {}).get(today_name, [])
                today_key = user_now.strftime("%Y-%m-%d")
                
                for plan in day_plans:
                    if isinstance(plan, dict) and plan.get("time") == current_time:
                        sent_key = f"sent_{today_key}_{plan['time']}_{plan.get('text','')}"
                        if not user_data.get(sent_key):
                            await application.bot.send_message(
                                chat_id=user_id,
                                text=f"⏰ Сейчас {plan['time']} — {plan.get('text','')}"
                            )
                            user_data[sent_key] = True
                            users[user_id] = user_data
                            save_users(users)
                
                if (
                    current_time == SUMMARY_TIME
                    and user_data.get('setup_complete')
                    and user_data.get('last_summary_date') != today_key
                ):
                    await send_daily_summary(user_id, application)
                    user_data['last_summary_date'] = today_key
            
            await asyncio.sleep(60)  # Проверяем каждую минуту
            
        except Exception as e:
            logger.error(f"Ошибка в scheduler: {e}")
            await asyncio.sleep(60)

# ========== ОСНОВНАЯ ФУНКЦИЯ ==========
async def start_notification_scheduler(app: Application):
    """Запускает фоновый планировщик после инициализации приложения"""
    # Сохраняем задачу, чтобы её можно было при необходимости отменить
    if not hasattr(app, "notification_task") or app.notification_task.done():
        app.notification_task = asyncio.create_task(notification_scheduler(app))

def main():
    """Запуск бота"""
    # Введите ваш токен бота
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("timezone", timezone_command))
    # ConversationHandler для управления потоком диалога
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("plan", plan_command),
            CommandHandler("itog", start_itog),
        ],
        states={
            MAIN_MENU: [
                CommandHandler("plan", plan_command),
                CommandHandler("itog", start_itog),
                MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu),
            ],
            CHOOSING_DAY: [
                CommandHandler("plan", plan_command),
                CommandHandler("itog", start_itog),
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_day),
            ],
            ENTERING_PLANS: [
                CommandHandler("plan", plan_command),
                CommandHandler("itog", start_itog),
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_plans),
            ],
            REVIEW_PLANS: [
                CommandHandler("plan", plan_command),
                CommandHandler("itog", start_itog),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_review_action),
            ],
            GLOBAL_MENU: [
                CommandHandler("plan", plan_command),
                CommandHandler("itog", start_itog),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_global_action),
            ],
            ENTERING_GLOBAL_PLANS: [
                CommandHandler("plan", plan_command),
                CommandHandler("itog", start_itog),
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_global_plans),
            ],
            ITOG_REVIEW: [
                CommandHandler("plan", plan_command),
                CommandHandler("itog", start_itog),
                MessageHandler(filters.Regex("^(Да|Нет)$") & ~filters.COMMAND, handle_itog_response),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("plan", plan_command),
            CommandHandler("itog", start_itog),
        ],
    )
    
    application.add_handler(CommandHandler("day", day_command))
    application.add_handler(conv_handler)
    
    # Добавляем scheduler для проверки времени и отправки уведомлений
    application.post_init = start_notification_scheduler
    
    logger.info("Бот запущен...")
    application.run_polling()

if __name__ == '__main__':
    main()
