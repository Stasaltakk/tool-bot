"""
Telegram-бот учёта инструментов.
MVP по ТЗ: пользователи, категории, инструменты, передача с подтверждением, списание, история.
"""
import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask
import threading

import database as db


# ========== ИНИЦИАЛИЗАЦИЯ ==========
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    print("❌ Ошибка: BOT_TOKEN не найден!")
    exit(1)

bot = telebot.TeleBot(TOKEN)

# Telegram ID первого админа — ставится из переменной окружения,
# чтобы при первом запуске админ мог войти и добавить остальных пользователей
INITIAL_ADMIN_ID = os.environ.get("INITIAL_ADMIN_ID")
if INITIAL_ADMIN_ID:
    INITIAL_ADMIN_ID = int(INITIAL_ADMIN_ID)


# ========== УТИЛИТЫ ==========

def ensure_initial_admin():
    """При первом запуске создаёт начального админа из переменной окружения."""
    if not INITIAL_ADMIN_ID:
        return
    user = db.get_user_by_telegram_id(INITIAL_ADMIN_ID)
    if not user:
        db.add_user(INITIAL_ADMIN_ID, "Главный администратор", role="admin")
        print(f"✅ Создан начальный админ: {INITIAL_ADMIN_ID}")
    elif user["role"] != "admin":
        db.update_user(user["id"], role="admin")


def check_access(user_id: int) -> bool:
    """Проверка доступа к боту. Только зарегистрированные пользователи."""
    return db.is_registered(user_id)


def access_denied(chat_id):
    bot.send_message(
        chat_id,
        "⛔ У вас нет доступа к этому боту.\n"
        "Обратитесь к администратору для регистрации."
    )


# ========== КЛАВИАТУРЫ ==========

def main_menu(user_id: int):
    markup = InlineKeyboardMarkup(row_width=1)
    is_admin = db.is_admin(user_id)

    markup.add(InlineKeyboardButton("📂 Инструменты по категориям", callback_data="categories"))
    markup.add(InlineKeyboardButton("📋 Все инструменты", callback_data="list_all"))
    markup.add(InlineKeyboardButton("📊 Статистика", callback_data="stats"))

    if is_admin:
        markup.add(InlineKeyboardButton("➕ Добавить инструмент", callback_data="add_tool"))
        markup.add(InlineKeyboardButton("🗂 Управление категориями", callback_data="manage_cats"))
        markup.add(InlineKeyboardButton("👥 Управление пользователями", callback_data="manage_users"))

    return markup


def back_button(callback="back_to_menu"):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("◀️ Назад в меню", callback_data=callback))
    return markup


# ========== START ==========

@bot.message_handler(commands=['start', 'старт'])
def start(message):
    user_id = message.from_user.id

    # Особая обработка для начального админа — авто-регистрация
    if INITIAL_ADMIN_ID and user_id == INITIAL_ADMIN_ID:
        if not db.is_registered(user_id):
            db.add_user(user_id, "Главный администратор", role="admin")

    if not check_access(user_id):
        access_denied(message.chat.id)
        return

    user = db.get_user_by_telegram_id(user_id)
    role_text = "👑 Администратор" if user["role"] == "admin" else "👤 Пользователь"
    bot.send_message(
        message.chat.id,
        f"🔧 Бот учёта инструментов\n\n"
        f"👋 Привет, {user['full_name']}!\n"
        f"Ваша роль: {role_text}\n\n"
        f"Выберите действие:",
        reply_markup=main_menu(user_id)
    )


# ========== ГЛАВНЫЙ CALLBACK HANDLER ==========

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id

    # Проверка доступа на каждый callback
    if not check_access(user_id):
        bot.answer_callback_query(call.id, "⛔ Нет доступа", show_alert=True)
        return

    data = call.data

    # ===== ГЛАВНОЕ МЕНЮ =====
    if data == "back_to_menu":
        bot.edit_message_text(
            "🔧 Главное меню:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=main_menu(user_id)
        )
        bot.answer_callback_query(call.id)
        return

    # ===== КАТЕГОРИИ =====
    if data == "categories":
        show_categories_menu(call)
        return

    if data.startswith("cat_view_"):
        category_id = int(data.replace("cat_view_", ""))
        show_tools_in_category(call, category_id)
        return

    # ===== СПИСОК ВСЕХ ИНСТРУМЕНТОВ =====
    if data == "list_all":
        show_all_tools(call)
        return

    # ===== СТАТИСТИКА =====
    if data == "stats":
        show_stats(call)
        return

    # ===== ИНСТРУМЕНТ — ДЕТАЛИ И ДЕЙСТВИЯ =====
    if data.startswith("tool_view_"):
        tool_id = int(data.replace("tool_view_", ""))
        show_tool_details(call, tool_id)
        return

    if data.startswith("tool_history_"):
        tool_id = int(data.replace("tool_history_", ""))
        show_tool_history(call, tool_id)
        return

    if data.startswith("tool_transfer_"):
        tool_id = int(data.replace("tool_transfer_", ""))
        start_transfer(call, tool_id)
        return

    if data.startswith("tool_writeoff_"):
        if not db.is_admin(user_id):
            bot.answer_callback_query(call.id, "⛔ Только админ", show_alert=True)
            return
        tool_id = int(data.replace("tool_writeoff_", ""))
        ask_writeoff_reason(call, tool_id)
        return

    # ===== ДОБАВЛЕНИЕ ИНСТРУМЕНТА =====
    if data == "add_tool":
        if not db.is_admin(user_id):
            bot.answer_callback_query(call.id, "⛔ Только админ", show_alert=True)
            return
        start_add_tool(call)
        return

    if data.startswith("addtool_cat_"):
        category_id = int(data.replace("addtool_cat_", ""))
        ask_tool_owner(call, category_id)
        return

    if data.startswith("addtool_owner_"):
        # формат: addtool_owner_{cat_id}_{user_id}
        parts = data.replace("addtool_owner_", "").split("_")
        category_id = int(parts[0])
        owner_id = int(parts[1])
        ask_tool_name(call, category_id, owner_id)
        return

    # ===== ПЕРЕДАЧА ИНСТРУМЕНТА =====
    if data.startswith("transfer_to_"):
        # формат: transfer_to_{tool_id}_{user_id}
        parts = data.replace("transfer_to_", "").split("_")
        tool_id = int(parts[0])
        to_user_id = int(parts[1])
        send_transfer_request(call, tool_id, to_user_id)
        return

    if data.startswith("confirm_tr_"):
        transfer_id = int(data.replace("confirm_tr_", ""))
        handle_transfer_confirm(call, transfer_id)
        return

    if data.startswith("reject_tr_"):
        transfer_id = int(data.replace("reject_tr_", ""))
        handle_transfer_reject(call, transfer_id)
        return

    # ===== СПИСАНИЕ — ВЫБОР ПРИЧИНЫ =====
    if data.startswith("writeoff_reason_"):
        # формат: writeoff_reason_{tool_id}_{reason_key}
        parts = data.replace("writeoff_reason_", "").split("_", 1)
        tool_id = int(parts[0])
        reason_key = parts[1]
        process_writeoff(call, tool_id, reason_key)
        return

    # ===== УПРАВЛЕНИЕ КАТЕГОРИЯМИ =====
    if data == "manage_cats":
        if not db.is_admin(user_id):
            bot.answer_callback_query(call.id, "⛔ Только админ", show_alert=True)
            return
        show_manage_categories(call)
        return

    if data == "add_category":
        if not db.is_admin(user_id):
            return
        msg = bot.send_message(call.message.chat.id, "📝 Введите название новой категории:")
        bot.register_next_step_handler(msg, process_add_category)
        bot.answer_callback_query(call.id)
        return

    if data.startswith("cat_rename_"):
        if not db.is_admin(user_id):
            return
        category_id = int(data.replace("cat_rename_", ""))
        cat = db.get_category_by_id(category_id)
        if cat:
            msg = bot.send_message(
                call.message.chat.id,
                f"✏️ Введите новое название для '{cat['name']}':"
            )
            bot.register_next_step_handler(msg, lambda m: process_rename_category(m, category_id))
        bot.answer_callback_query(call.id)
        return

    if data.startswith("cat_delete_"):
        if not db.is_admin(user_id):
            return
        category_id = int(data.replace("cat_delete_", ""))
        if db.delete_category(category_id):
            bot.answer_callback_query(call.id, "🗑 Категория удалена", show_alert=True)
            show_manage_categories(call)
        return

    # ===== УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ =====
    if data == "manage_users":
        if not db.is_admin(user_id):
            bot.answer_callback_query(call.id, "⛔ Только админ", show_alert=True)
            return
        show_manage_users(call)
        return

    if data == "add_user":
        if not db.is_admin(user_id):
            return
        msg = bot.send_message(
            call.message.chat.id,
            "📝 Введите Telegram ID нового пользователя:\n"
            "(Узнать свой ID можно у @userinfobot)"
        )
        bot.register_next_step_handler(msg, process_add_user_id)
        bot.answer_callback_query(call.id)
        return

    if data.startswith("user_view_"):
        if not db.is_admin(user_id):
            return
        target_id = int(data.replace("user_view_", ""))
        show_user_details(call, target_id)
        return

    if data.startswith("user_rename_"):
        if not db.is_admin(user_id):
            return
        target_id = int(data.replace("user_rename_", ""))
        msg = bot.send_message(call.message.chat.id, "✏️ Введите новое имя:")
        bot.register_next_step_handler(msg, lambda m: process_rename_user(m, target_id))
        bot.answer_callback_query(call.id)
        return

    if data.startswith("user_role_"):
        if not db.is_admin(user_id):
            return
        target_id = int(data.replace("user_role_", ""))
        toggle_user_role(call, target_id)
        return

    if data.startswith("user_delete_"):
        if not db.is_admin(user_id):
            return
        target_id = int(data.replace("user_delete_", ""))
        db.soft_delete_user(target_id)
        bot.answer_callback_query(call.id, "🗑 Пользователь удалён", show_alert=True)
        show_manage_users(call)
        return


# ========== ОТОБРАЖЕНИЕ — КАТЕГОРИИ ==========

def show_categories_menu(call):
    cats = db.get_all_categories()
    if not cats:
        bot.edit_message_text(
            "📭 Категорий пока нет.\n\nПопросите администратора создать категорию.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=back_button()
        )
        bot.answer_callback_query(call.id)
        return

    markup = InlineKeyboardMarkup(row_width=1)
    for cat in cats:
        markup.add(InlineKeyboardButton(
            f"📂 {cat['name']} ({cat['tools_count']})",
            callback_data=f"cat_view_{cat['id']}"
        ))
    markup.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu"))
    bot.edit_message_text(
        "📂 Выберите категорию:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )
    bot.answer_callback_query(call.id)


def show_tools_in_category(call, category_id: int):
    cat = db.get_category_by_id(category_id)
    if not cat:
        bot.answer_callback_query(call.id, "❌ Категория не найдена", show_alert=True)
        return
    tools = db.get_tools_by_category(category_id)
    markup = InlineKeyboardMarkup(row_width=1)
    if not tools:
        text = f"📂 {cat['name']}\n\n📭 В этой категории нет инструментов"
    else:
        text = f"📂 {cat['name']}\n\nВыберите инструмент:"
        for t in tools:
            owner = t['owner_name'] or "—"
            markup.add(InlineKeyboardButton(
                f"🔧 {t['name']} → {owner}",
                callback_data=f"tool_view_{t['id']}"
            ))
    markup.add(InlineKeyboardButton("◀️ К категориям", callback_data="categories"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)


def show_all_tools(call):
    tools = db.get_all_tools()
    if not tools:
        bot.edit_message_text(
            "📭 Инструментов пока нет",
            call.message.chat.id, call.message.message_id,
            reply_markup=back_button()
        )
        bot.answer_callback_query(call.id)
        return
    text = "📋 Все инструменты:\n\n"
    for t in tools:
        cat = t['category_name'] or "без категории"
        owner = t['owner_name'] or "—"
        text += f"🔧 {t['name']}\n   📂 {cat}\n   👤 {owner}\n\n"
    bot.edit_message_text(
        text, call.message.chat.id, call.message.message_id,
        reply_markup=back_button()
    )
    bot.answer_callback_query(call.id)


# ========== ОТОБРАЖЕНИЕ — ИНСТРУМЕНТ ==========

def show_tool_details(call, tool_id: int):
    tool = db.get_tool_by_id(tool_id)
    if not tool:
        bot.answer_callback_query(call.id, "❌ Инструмент не найден", show_alert=True)
        return
    cat = tool['category_name'] or "без категории"
    owner = tool['owner_name'] or "—"
    status = "✅ Активен" if tool['status'] == 'active' else "🗑 Списан"
    text = f"🔧 {tool['name']}\n\n📂 Категория: {cat}\n👤 Владелец: {owner}\n📊 Статус: {status}"
    if tool['status'] == 'written_off' and tool['write_off_reason']:
        text += f"\n📝 Причина: {tool['write_off_reason']}"

    markup = InlineKeyboardMarkup(row_width=1)
    if tool['status'] == 'active':
        markup.add(InlineKeyboardButton("🔄 Передать", callback_data=f"tool_transfer_{tool_id}"))
    markup.add(InlineKeyboardButton("📜 История", callback_data=f"tool_history_{tool_id}"))
    if db.is_admin(call.from_user.id) and tool['status'] == 'active':
        markup.add(InlineKeyboardButton("🗑 Списать", callback_data=f"tool_writeoff_{tool_id}"))
    if tool['category_id']:
        markup.add(InlineKeyboardButton("◀️ К категории", callback_data=f"cat_view_{tool['category_id']}"))
    markup.add(InlineKeyboardButton("◀️ В меню", callback_data="back_to_menu"))

    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)


def show_tool_history(call, tool_id: int):
    tool = db.get_tool_by_id(tool_id)
    if not tool:
        return
    history = db.get_tool_history(tool_id, limit=10)
    text = f"📜 История '{tool['name']}'\n\n"
    if not history:
        text += "Записей нет"
    else:
        for h in history:
            dt = h['created_at'].strftime('%d.%m.%Y %H:%M')
            event_type = h['event_type']
            if event_type == 'created':
                text += f"➕ {dt}\n   {h['note'] or 'Создан'}\n\n"
            elif event_type == 'transfer':
                status_emoji = {'confirmed': '✅', 'pending': '⏳', 'rejected': '❌'}.get(h['status'], '?')
                fr = h['from_name'] or '—'
                to = h['to_name'] or '—'
                text += f"🔄 {dt} {status_emoji}\n   {fr} → {to}\n\n"
            elif event_type == 'written_off':
                text += f"🗑 {dt}\n   {h['note']}\n\n"
            elif event_type == 'renamed':
                text += f"✏️ {dt}\n   {h['note']}\n\n"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("◀️ Назад", callback_data=f"tool_view_{tool_id}"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)


# ========== ДОБАВЛЕНИЕ ИНСТРУМЕНТА ==========

def start_add_tool(call):
    cats = db.get_all_categories()
    if not cats:
        bot.answer_callback_query(
            call.id,
            "❌ Сначала создайте хотя бы одну категорию",
            show_alert=True
        )
        return
    markup = InlineKeyboardMarkup(row_width=1)
    for cat in cats:
        markup.add(InlineKeyboardButton(
            f"📂 {cat['name']}", callback_data=f"addtool_cat_{cat['id']}"
        ))
    markup.add(InlineKeyboardButton("◀️ Отмена", callback_data="back_to_menu"))
    bot.edit_message_text(
        "📂 Шаг 1/3: Выберите категорию для нового инструмента:",
        call.message.chat.id, call.message.message_id, reply_markup=markup
    )
    bot.answer_callback_query(call.id)


def ask_tool_owner(call, category_id: int):
    users = db.get_all_users()
    if not users:
        bot.answer_callback_query(
            call.id, "❌ Нет зарегистрированных пользователей", show_alert=True
        )
        return
    markup = InlineKeyboardMarkup(row_width=1)
    for u in users:
        markup.add(InlineKeyboardButton(
            f"👤 {u['full_name']}",
            callback_data=f"addtool_owner_{category_id}_{u['id']}"
        ))
    markup.add(InlineKeyboardButton("◀️ Отмена", callback_data="back_to_menu"))
    bot.edit_message_text(
        "👤 Шаг 2/3: За кем закрепить инструмент?",
        call.message.chat.id, call.message.message_id, reply_markup=markup
    )
    bot.answer_callback_query(call.id)


def ask_tool_name(call, category_id: int, owner_id: int):
    msg = bot.send_message(
        call.message.chat.id,
        "📝 Шаг 3/3: Введите название инструмента:"
    )
    bot.register_next_step_handler(msg, lambda m: process_tool_name(m, category_id, owner_id))
    bot.answer_callback_query(call.id)


def process_tool_name(message, category_id: int, owner_id: int):
    name = message.text.strip()
    if not name:
        bot.send_message(message.chat.id, "❌ Название не может быть пустым")
        bot.send_message(message.chat.id, "Меню:", reply_markup=main_menu(message.from_user.id))
        return
    tool = db.add_tool(name, category_id, owner_id)
    bot.send_message(message.chat.id, f"✅ Инструмент '{tool['name']}' добавлен!")
    bot.send_message(message.chat.id, "Меню:", reply_markup=main_menu(message.from_user.id))


# ========== ПЕРЕДАЧА ИНСТРУМЕНТА ==========

def start_transfer(call, tool_id: int):
    tool = db.get_tool_by_id(tool_id)
    if not tool or tool['status'] != 'active':
        bot.answer_callback_query(call.id, "❌ Инструмент недоступен", show_alert=True)
        return
    # право на передачу: текущий владелец или админ
    user = db.get_user_by_telegram_id(call.from_user.id)
    if user['role'] != 'admin' and tool['current_owner_id'] != user['id']:
        bot.answer_callback_query(
            call.id, "⛔ Передавать может только текущий владелец или админ",
            show_alert=True
        )
        return

    users = db.get_all_users()
    # исключаем текущего владельца
    users = [u for u in users if u['id'] != tool['current_owner_id']]
    if not users:
        bot.answer_callback_query(call.id, "❌ Некому передать", show_alert=True)
        return

    markup = InlineKeyboardMarkup(row_width=1)
    for u in users:
        markup.add(InlineKeyboardButton(
            f"👤 {u['full_name']}",
            callback_data=f"transfer_to_{tool_id}_{u['id']}"
        ))
    markup.add(InlineKeyboardButton("◀️ Отмена", callback_data=f"tool_view_{tool_id}"))
    bot.edit_message_text(
        f"🔄 Передать '{tool['name']}'\n\nКому передаёте?",
        call.message.chat.id, call.message.message_id, reply_markup=markup
    )
    bot.answer_callback_query(call.id)


def send_transfer_request(call, tool_id: int, to_user_id: int):
    tool = db.get_tool_by_id(tool_id)
    to_user = db.get_user_by_id(to_user_id)
    from_user = db.get_user_by_telegram_id(call.from_user.id)

    if not tool or not to_user or not from_user:
        bot.answer_callback_query(call.id, "❌ Ошибка", show_alert=True)
        return

    transfer = db.create_transfer_request(tool_id, from_user['id'], to_user_id)

    # уведомление получателю
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm_tr_{transfer['id']}"),
        InlineKeyboardButton("❌ Отказать", callback_data=f"reject_tr_{transfer['id']}")
    )
    try:
        bot.send_message(
            to_user['telegram_id'],
            f"📩 Вам передают инструмент!\n\n"
            f"🔧 Инструмент: {tool['name']}\n"
            f"👤 От кого: {from_user['full_name']}\n\n"
            f"Подтверждение через бота служит аналогом подписи.\n"
            f"Подтверждаете получение?",
            reply_markup=markup
        )
    except Exception as e:
        bot.answer_callback_query(
            call.id,
            f"⚠️ Не удалось отправить уведомление получателю.\n"
            f"Возможно, он не запускал бота командой /start",
            show_alert=True
        )
        return

    bot.edit_message_text(
        f"⏳ Запрос на передачу '{tool['name']}' отправлен пользователю {to_user['full_name']}.\n"
        f"Ожидаем подтверждения.",
        call.message.chat.id, call.message.message_id,
        reply_markup=back_button()
    )
    bot.answer_callback_query(call.id, "✅ Запрос отправлен")


def handle_transfer_confirm(call, transfer_id: int):
    transfer = db.get_transfer_by_id(transfer_id)
    if not transfer:
        bot.answer_callback_query(call.id, "❌ Передача не найдена", show_alert=True)
        return
    # проверка что подтверждает именно получатель
    if transfer['to_telegram_id'] != call.from_user.id:
        bot.answer_callback_query(call.id, "⛔ Подтвердить может только получатель", show_alert=True)
        return
    if transfer['status'] != 'pending':
        bot.answer_callback_query(call.id, "⚠️ Запрос уже обработан", show_alert=True)
        return

    db.confirm_transfer(transfer_id)

    bot.edit_message_text(
        f"✅ Вы подтвердили получение '{transfer['tool_name']}'.\n"
        f"Инструмент закреплён за вами.",
        call.message.chat.id, call.message.message_id
    )

    # уведомление отправителю
    try:
        bot.send_message(
            transfer['from_telegram_id'],
            f"✅ {transfer['to_name']} подтвердил(а) получение инструмента '{transfer['tool_name']}'."
        )
    except Exception:
        pass

    bot.answer_callback_query(call.id)


def handle_transfer_reject(call, transfer_id: int):
    transfer = db.get_transfer_by_id(transfer_id)
    if not transfer:
        return
    if transfer['to_telegram_id'] != call.from_user.id:
        bot.answer_callback_query(call.id, "⛔ Только получатель может отказать", show_alert=True)
        return
    if transfer['status'] != 'pending':
        bot.answer_callback_query(call.id, "⚠️ Запрос уже обработан", show_alert=True)
        return

    db.reject_transfer(transfer_id)

    bot.edit_message_text(
        f"❌ Вы отказались от инструмента '{transfer['tool_name']}'.\n"
        f"Инструмент остался у прежнего владельца.",
        call.message.chat.id, call.message.message_id
    )

    try:
        bot.send_message(
            transfer['from_telegram_id'],
            f"❌ {transfer['to_name']} отказался(ась) от инструмента '{transfer['tool_name']}'."
        )
    except Exception:
        pass

    bot.answer_callback_query(call.id)


# ========== СПИСАНИЕ ==========

WRITEOFF_REASONS = {
    "wear": "Износ / выработан ресурс",
    "broken": "Поломка",
    "sold": "Продажа",
    "lost": "Утеря",
    "stolen": "Кража",
    "other": "Другое",
}


def ask_writeoff_reason(call, tool_id: int):
    tool = db.get_tool_by_id(tool_id)
    if not tool:
        return
    markup = InlineKeyboardMarkup(row_width=1)
    for key, label in WRITEOFF_REASONS.items():
        markup.add(InlineKeyboardButton(
            label, callback_data=f"writeoff_reason_{tool_id}_{key}"
        ))
    markup.add(InlineKeyboardButton("◀️ Отмена", callback_data=f"tool_view_{tool_id}"))
    bot.edit_message_text(
        f"🗑 Списание '{tool['name']}'\n\nВыберите причину:",
        call.message.chat.id, call.message.message_id, reply_markup=markup
    )
    bot.answer_callback_query(call.id)


def process_writeoff(call, tool_id: int, reason_key: str):
    if reason_key == "other":
        msg = bot.send_message(
            call.message.chat.id,
            "📝 Введите свою причину списания:"
        )
        bot.register_next_step_handler(msg, lambda m: finalize_writeoff(m, tool_id, m.text.strip()))
        bot.answer_callback_query(call.id)
        return

    reason = WRITEOFF_REASONS.get(reason_key, "не указана")
    if db.write_off_tool(tool_id, reason):
        tool = db.get_tool_by_id(tool_id)
        bot.edit_message_text(
            f"🗑 '{tool['name']}' списан\nПричина: {reason}",
            call.message.chat.id, call.message.message_id,
            reply_markup=back_button()
        )
    bot.answer_callback_query(call.id)


def finalize_writeoff(message, tool_id: int, reason: str):
    if not reason:
        bot.send_message(message.chat.id, "❌ Причина не может быть пустой")
        return
    if db.write_off_tool(tool_id, reason):
        tool = db.get_tool_by_id(tool_id)
        bot.send_message(message.chat.id, f"🗑 '{tool['name']}' списан\nПричина: {reason}")
    bot.send_message(message.chat.id, "Меню:", reply_markup=main_menu(message.from_user.id))


# ========== УПРАВЛЕНИЕ КАТЕГОРИЯМИ ==========

def show_manage_categories(call):
    cats = db.get_all_categories()
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("➕ Добавить категорию", callback_data="add_category"))
    for cat in cats:
        markup.add(
            InlineKeyboardButton(
                f"✏️ {cat['name']} ({cat['tools_count']})",
                callback_data=f"cat_rename_{cat['id']}"
            )
        )
        markup.add(
            InlineKeyboardButton(
                f"🗑 Удалить '{cat['name']}'",
                callback_data=f"cat_delete_{cat['id']}"
            )
        )
    markup.add(InlineKeyboardButton("◀️ В меню", callback_data="back_to_menu"))
    text = "🗂 Управление категориями\n\nДля переименования нажмите ✏️"
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)


def process_add_category(message):
    if not db.is_admin(message.from_user.id):
        return
    name = message.text.strip()
    if not name:
        bot.send_message(message.chat.id, "❌ Название не может быть пустым")
    elif db.add_category(name):
        bot.send_message(message.chat.id, f"✅ Категория '{name}' создана!")
    else:
        bot.send_message(message.chat.id, f"⚠️ Категория '{name}' уже существует")
    bot.send_message(message.chat.id, "Меню:", reply_markup=main_menu(message.from_user.id))


def process_rename_category(message, category_id: int):
    new_name = message.text.strip()
    if not new_name:
        bot.send_message(message.chat.id, "❌ Название не может быть пустым")
    elif db.rename_category(category_id, new_name):
        bot.send_message(message.chat.id, f"✅ Категория переименована в '{new_name}'")
    else:
        bot.send_message(message.chat.id, "❌ Не удалось переименовать")
    bot.send_message(message.chat.id, "Меню:", reply_markup=main_menu(message.from_user.id))


# ========== УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ ==========

def show_manage_users(call):
    users = db.get_all_users()
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("➕ Добавить пользователя", callback_data="add_user"))
    for u in users:
        role_icon = "👑" if u['role'] == 'admin' else "👤"
        markup.add(InlineKeyboardButton(
            f"{role_icon} {u['full_name']}",
            callback_data=f"user_view_{u['id']}"
        ))
    markup.add(InlineKeyboardButton("◀️ В меню", callback_data="back_to_menu"))
    bot.edit_message_text(
        "👥 Пользователи системы:",
        call.message.chat.id, call.message.message_id, reply_markup=markup
    )
    bot.answer_callback_query(call.id)


def show_user_details(call, target_id: int):
    user = db.get_user_by_id(target_id)
    if not user:
        return
    role = "👑 Администратор" if user['role'] == 'admin' else "👤 Пользователь"
    text = (
        f"👤 {user['full_name']}\n\n"
        f"🆔 Telegram ID: {user['telegram_id']}\n"
        f"📊 Роль: {role}"
    )
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("✏️ Переименовать", callback_data=f"user_rename_{target_id}"))
    new_role_label = "Сделать пользователем" if user['role'] == 'admin' else "Сделать админом"
    markup.add(InlineKeyboardButton(f"🔄 {new_role_label}", callback_data=f"user_role_{target_id}"))
    markup.add(InlineKeyboardButton("🗑 Удалить", callback_data=f"user_delete_{target_id}"))
    markup.add(InlineKeyboardButton("◀️ К списку", callback_data="manage_users"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)


# ВРЕМЕННОЕ ХРАНИЛИЩЕ для процесса добавления пользователя (telegram_id → ожидаем ввод имени)
_pending_user_ids = {}


def process_add_user_id(message):
    if not db.is_admin(message.from_user.id):
        return
    try:
        new_tg_id = int(message.text.strip())
    except ValueError:
        bot.send_message(message.chat.id, "❌ Telegram ID должен быть числом")
        bot.send_message(message.chat.id, "Меню:", reply_markup=main_menu(message.from_user.id))
        return
    _pending_user_ids[message.from_user.id] = new_tg_id
    msg = bot.send_message(
        message.chat.id,
        "📝 Введите имя пользователя (например: Иванов Иван):"
    )
    bot.register_next_step_handler(msg, process_add_user_name)


def process_add_user_name(message):
    if not db.is_admin(message.from_user.id):
        return
    full_name = message.text.strip()
    new_tg_id = _pending_user_ids.pop(message.from_user.id, None)
    if not new_tg_id or not full_name:
        bot.send_message(message.chat.id, "❌ Ошибка ввода")
        bot.send_message(message.chat.id, "Меню:", reply_markup=main_menu(message.from_user.id))
        return
    db.add_user(new_tg_id, full_name, role="user")
    bot.send_message(
        message.chat.id,
        f"✅ Пользователь '{full_name}' добавлен!\n"
        f"Попросите его запустить бота командой /start"
    )
    bot.send_message(message.chat.id, "Меню:", reply_markup=main_menu(message.from_user.id))


def process_rename_user(message, target_id: int):
    if not db.is_admin(message.from_user.id):
        return
    new_name = message.text.strip()
    if new_name and db.update_user(target_id, full_name=new_name):
        bot.send_message(message.chat.id, f"✅ Имя изменено на '{new_name}'")
    else:
        bot.send_message(message.chat.id, "❌ Не удалось переименовать")
    bot.send_message(message.chat.id, "Меню:", reply_markup=main_menu(message.from_user.id))


def toggle_user_role(call, target_id: int):
    user = db.get_user_by_id(target_id)
    if not user:
        return
    new_role = "user" if user['role'] == "admin" else "admin"
    db.update_user(target_id, role=new_role)
    bot.answer_callback_query(call.id, f"✅ Роль изменена на: {new_role}", show_alert=True)
    show_user_details(call, target_id)


# ========== СТАТИСТИКА ==========

def show_stats(call):
    stats = db.get_statistics()
    text = (
        f"📊 Статистика\n\n"
        f"🔧 Активных инструментов: {stats['total_tools']}\n"
        f"🗑 Списано: {stats['written_off']}\n"
        f"🔄 Подтверждённых передач: {stats['transfers']}\n"
        f"📂 Категорий: {stats['categories']}\n"
        f"👥 Пользователей: {stats['users']}"
    )
    bot.edit_message_text(
        text, call.message.chat.id, call.message.message_id,
        reply_markup=back_button()
    )
    bot.answer_callback_query(call.id)


# ========== FLASK ДЛЯ RAILWAY ==========

app = Flask(__name__)


@app.route('/')
def home():
    return "✅ Бот учёта инструментов работает!"


def run_bot():
    print("🚀 Бот запущен")
    bot.infinity_polling()


# ========== ЗАПУСК ==========

if __name__ == "__main__":
    db.init_db()
    ensure_initial_admin()

    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    port = int(os.environ.get("PORT", 5000))
    print(f"🌐 Веб-сервер запущен на порту {port}")
    app.run(host='0.0.0.0', port=port)
