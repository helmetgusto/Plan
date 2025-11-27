import logging
import json
import os
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
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

# Файлы для хранения данных
USERS_FILE = "users_data.json"
GLOBAL_PLANS_FILE = "global_plans.json"

# Состояния для ConversationHandler
(MAIN_MENU, SETUP_PLANS, CHOOSING_DAY, ENTERING_PLANS, REVIEW_PLANS, 
 GLOBAL_MENU, ENTERING_GLOBAL_PLANS, REVIEWING_GLOBAL) = range(8)

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
    user_id = str(update.effective_user.id)
    users = load_users()
    
    if user_id not in users:
        users[user_id] = {
            "name": update.effective_user.first_name,
            "notification_time": "09:00",
            "plans": {day: [] for day in DAYS_OF_WEEK},
            "setup_complete": False,
            "last_message_id": None
        }
        save_users(users)
    
    welcome_text = f"""🎯 Привет, {update.effective_user.first_name}!

Добро пожаловать в ежедневник-бот! Я помогу вам организовать ваш день.

**Мои возможности:**
✅ Планирование на каждый день недели
✅ Глобальные планы (на все дни)
✅ Ежедневные напоминания
✅ Добавление, редактирование и удаление планов

Давайте начнём!"""
    
    keyboard = [["📋 Настроить планы", "🌍 Глобальные планы"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    return MAIN_MENU

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Главное меню"""
    user_id = str(update.effective_user.id)
    users = load_users()
    user = users.get(user_id, {})
    
    if update.message.text == "📋 Настроить планы":
        return await setup_plans(update, context)
    elif update.message.text == "🌍 Глобальные планы":
        return await global_plans_menu(update, context)
    
    keyboard = [["📋 Настроить планы", "🌍 Глобальные планы"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)
    return MAIN_MENU

async def setup_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало настройки планов"""
    user_id = str(update.effective_user.id)
    context.user_data['setup_day'] = 0
    
    keyboard = [[day] for day in DAYS_SHORT]
    keyboard.append(["⏭️ Пропустить все"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    
    await update.message.reply_text(
        "📅 Выберите день для начала:\n(Нажимайте на дни по порядку или пропустите)",
        reply_markup=reply_markup
    )
    return CHOOSING_DAY

async def choose_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Выбор дня недели"""
    user_id = str(update.effective_user.id)
    users = load_users()
    text = update.message.text.strip()
    
    # Пропуск всех дней
    if text == "⏭️ Пропустить все":
        users[user_id]['plans'] = {day: [] for day in DAYS_OF_WEEK}
        users[user_id]['setup_complete'] = True
        save_users(users)
        
        keyboard = [["📋 Настроить планы", "🌍 Глобальные планы"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "✅ Все дни заполнены пропусками!\n\nМеню:",
            reply_markup=reply_markup
        )
        return MAIN_MENU
    
    # Найти день по короткому названию
    day_index = None
    for i, day_short in enumerate(DAYS_SHORT):
        if text == day_short:
            day_index = i
            break
    
    if day_index is None:
        await update.message.reply_text("❌ Пожалуйста, выберите день из предложенных вариантов")
        return CHOOSING_DAY
    
    context.user_data['current_day'] = DAYS_OF_WEEK[day_index]
    context.user_data['day_index'] = day_index
    
    keyboard = [["⏭️ Пропустить день"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await update.message.reply_text(
        f"📝 {DAYS_OF_WEEK[day_index]}\n\nВпишите планы, разделяя их точкой с запятой (;):\n\nПример: сходить погулять; купить молоко; позвонить другу",
        reply_markup=reply_markup
    )
    return ENTERING_PLANS

async def enter_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ввод планов"""
    user_id = str(update.effective_user.id)
    users = load_users()
    text = update.message.text.strip()
    
    # Пропуск дня
    if text == "⏭️ Пропустить день":
        context.user_data['current_plans'] = []
    else:
        # Парсим планы
        plans = [plan.strip() for plan in text.split(';') if plan.strip()]
        context.user_data['current_plans'] = plans
    
    return await review_plans(update, context)

async def review_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Проверка и подтверждение планов"""
    user_id = str(update.effective_user.id)
    users = load_users()
    
    current_day = context.user_data.get('current_day')
    plans = context.user_data.get('current_plans', [])
    
    # Форматируем планы для отображения
    if plans:
        plans_text = "\n".join([f"{i+1}. {plan}" for i, plan in enumerate(plans)])
    else:
        plans_text = "Пусто (день пропущен)"
    
    review_message = f"""✅ Проверка планов для {current_day}:

{plans_text}

Что дальше?"""
    
    keyboard = [
        ["➕ Дополнить", "✏️ Изменить"],
        ["➡️ Продолжить"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await update.message.reply_text(review_message, reply_markup=reply_markup)
    return REVIEW_PLANS

async def handle_review_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка действий после проверки"""
    user_id = str(update.effective_user.id)
    users = load_users()
    text = update.message.text.strip()
    
    if text == "➕ Дополнить":
        keyboard = [["❌ Отмена"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            "Введите новые планы (разделяйте точкой с запятой):",
            reply_markup=reply_markup
        )
        context.user_data['action'] = 'supplement'
        return ENTERING_PLANS
    
    elif text == "✏️ Изменить":
        keyboard = [["❌ Отмена"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            "Введите планы заново (разделяйте точкой с запятой):",
            reply_markup=reply_markup
        )
        context.user_data['action'] = 'replace'
        return ENTERING_PLANS
    
    elif text == "➡️ Продолжить":
        current_day = context.user_data.get('current_day')
        action = context.user_data.get('action', 'replace')
        plans = context.user_data.get('current_plans', [])
        
        if action == 'supplement':
            users[user_id]['plans'][current_day].extend(plans)
        else:
            users[user_id]['plans'][current_day] = plans
        
        context.user_data['action'] = 'replace'
        day_index = context.user_data.get('day_index', 0)
        
        # Проверяем, остались ли дни
        if day_index < 6:
            # Показываем дни от следующего до конца
            remaining_days = [DAYS_SHORT[i] for i in range(day_index + 1, 7)]
            
            keyboard = [[day] for day in remaining_days]
            keyboard.append(["✅ Готово"])
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
            
            await update.message.reply_text(
                f"✅ {current_day} готов!\n\nВыберите следующий день:",
                reply_markup=reply_markup
            )
            return CHOOSING_DAY
        else:
            # Все дни заполнены
            users[user_id]['setup_complete'] = True
            save_users(users)
            
            # Спросим время уведомлений
            keyboard = [[]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                "⏰ В какое время вы хотите получать уведомления?\n\nВведите время в формате ЧЧ:МММ (например: 09:00)",
                reply_markup=ReplyKeyboardRemove()
            )
            context.user_data['waiting_for_time'] = True
            return MAIN_MENU
    
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
            
            keyboard = [["📋 Настроить планы", "🌍 Глобальные планы"]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                f"✅ Время уведомлений установлено: {users[user_id]['notification_time']}\n\nМеню:",
                reply_markup=reply_markup
            )
            return MAIN_MENU
        
        except (ValueError, IndexError):
            await update.message.reply_text(
                "❌ Неверный формат! Используйте ЧЧ:МММ (например: 09:00)"
            )
            return MAIN_MENU
    
    keyboard = [["📋 Настроить планы", "🌍 Глобальные планы"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Меню:", reply_markup=reply_markup)
    return MAIN_MENU

# ========== ГЛОБАЛЬНЫЕ ПЛАНЫ ==========

async def global_plans_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Меню глобальных планов"""
    user_id = str(update.effective_user.id)
    global_plans = load_global_plans()
    user_plans = global_plans.get(user_id, [])
    
    if user_plans:
        plans_text = "\n".join([f"{i+1}. {plan}" for i, plan in enumerate(user_plans)])
        message = f"🌍 Ваши глобальные планы:\n\n{plans_text}"
    else:
        message = "🌍 У вас нет глобальных планов"
    
    keyboard = [
        ["➕ Добавить", "✏️ Редактировать"],
        ["🗑️ Удалить", "⬅️ Назад"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await update.message.reply_text(
        message + "\n\nВыберите действие:",
        reply_markup=reply_markup
    )
    return GLOBAL_MENU

async def handle_global_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка действий с глобальными планами"""
    text = update.message.text.strip()
    user_id = str(update.effective_user.id)
    
    if text == "➕ Добавить":
        keyboard = [[]]
        await update.message.reply_text(
            "Введите новые глобальные планы (разделяйте точкой с запятой):",
            reply_markup=ReplyKeyboardRemove()
        )
        context.user_data['global_action'] = 'add'
        return ENTERING_GLOBAL_PLANS
    
    elif text == "✏️ Редактировать":
        keyboard = [[]]
        await update.message.reply_text(
            "Введите новые глобальные планы (заменят старые):",
            reply_markup=ReplyKeyboardRemove()
        )
        context.user_data['global_action'] = 'replace'
        return ENTERING_GLOBAL_PLANS
    
    elif text == "🗑️ Удалить":
        global_plans = load_global_plans()
        if user_id in global_plans:
            del global_plans[user_id]
            save_global_plans(global_plans)
            await update.message.reply_text("✅ Все глобальные планы удалены")
        else:
            await update.message.reply_text("❌ Нет планов для удаления")
        
        keyboard = [["📋 Настроить планы", "🌍 Глобальные планы"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Меню:", reply_markup=reply_markup)
        return MAIN_MENU
    
    elif text == "⬅️ Назад":
        keyboard = [["📋 Настроить планы", "🌍 Глобальные планы"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text("Меню:", reply_markup=reply_markup)
        return MAIN_MENU
    
    return GLOBAL_MENU

async def enter_global_plans(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ввод глобальных планов"""
    user_id = str(update.effective_user.id)
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
    
    keyboard = [["📋 Настроить планы", "🌍 Глобальные планы"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"✅ Глобальные планы обновлены!\n\nМеню:",
        reply_markup=reply_markup
    )
    return MAIN_MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена текущей операции"""
    keyboard = [["📋 Настроить планы", "🌍 Глобальные планы"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Отменено. Меню:", reply_markup=reply_markup)
    return MAIN_MENU

# ========== ОТПРАВКА УВЕДОМЛЕНИЙ ==========

async def send_daily_notification(application):
    """Отправить ежедневные уведомления"""
    users = load_users()
    global_plans = load_global_plans()
    
    today = datetime.now().weekday()
    today_name = DAYS_OF_WEEK[today]
    
    for user_id, user_data in users.items():
        try:
            plans = user_data['plans'].get(today_name, [])
            user_global = global_plans.get(user_id, [])
            
            # Формируем сообщение
            message = f"📅 План на {today_name}:\n\n"
            
            if plans:
                message += "📋 Ежедневные планы:\n"
                message += "\n".join([f"• {plan}" for plan in plans])
            else:
                message += "📋 Нет ежедневных планов"
            
            if user_global:
                message += "\n\n🌍 Глобальные планы:\n"
                message += "\n".join([f"• {plan}" for plan in user_global])
            
            # Отправляем сообщение
            msg = await application.bot.send_message(chat_id=user_id, text=message)
            
            # Сохраняем ID сообщения для последующего удаления
            users[user_id]['last_message_id'] = msg.message_id
            
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения пользователю {user_id}: {e}")
    
    save_users(users)

# ========== ОСНОВНАЯ ФУНКЦИЯ ==========

def main():
    """Запуск бота"""
    # Введите ваш токен бота
    TOKEN = "YOUR_BOT_TOKEN_HERE"
    
    application = Application.builder().token(TOKEN).build()
    
    # ConversationHandler для управления потоком диалога
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu),
            ],
            CHOOSING_DAY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_day),
            ],
            ENTERING_PLANS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_plans),
            ],
            REVIEW_PLANS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_review_action),
            ],
            GLOBAL_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_global_action),
            ],
            ENTERING_GLOBAL_PLANS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, enter_global_plans),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))
    
    # Scheduler для отправки уведомлений
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        send_daily_notification,
        'cron',
        hour=9,
        minute=0,
        args=[application]
    )
    scheduler.start()
    
    logger.info("Бот запущен...")
    application.run_polling()

if __name__ == '__main__':
    main()
