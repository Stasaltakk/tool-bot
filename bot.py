"""
Telegram-бот учёта инструментов.
Полностью переработанный UX:
 - Действия редактируют сообщение, без дубликатов меню
 - Команды /menu, /tools, /add, /users, /cancel, /help
 - Кнопки 'Отмена' на всех шагах ввода
 - Подтверждения опасных действий
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

INITIAL_ADMIN_ID = os.environ.get("INITIAL_ADMIN_ID")
if INITIAL_ADMIN_ID:
    INITIAL_ADMIN_ID = int(INITIAL_ADMIN_ID)


# ========== СОСТОЯНИЕ ОЖИДАНИЯ ВВОДА ==========
# Хранит для какого пользователя какое действие сейчас ожидается
# {user_id: {"action": "add_category", "data": {...}, "msg_id": int}}
pending_input = {}


def set_pending(user_id: int, action: str, data: dict = None, msg_id: int = None):
    pending_input[user_id] = {"action": action, "data": data or {}, "msg_id": msg_id}


def clear_pending(user_id: int):
    pending_input.pop(user_id, None)


def get_pending(user_id: int):
    return pending_input.get(user_id)


# ========== УТИЛИТЫ ==========

def ensure_initial_admin():
    if not INITIAL_ADMIN_ID:
        return
    user = db.get_user_by_telegram_id(INITIAL_ADMIN_ID)
    if not user:
        db.add_user(INITIAL_ADMIN_ID, "Главный администратор", role="admin")
        print(f"✅ Создан начальный админ: {INITIAL_ADMIN_ID}")
    elif user["role"] != "admin":
        db.update_user(user["id"], role="admin")


def check_access(user_id: int) -> bool:
    return db.is_registered(user_id)


def safe_edit(chat_id, message_id, text, reply_markup=None):
    """Безопасное редактирование сообщения. Если не получается — отправляет новое."""
    try:
        bot.edit_message_text(
            text, chat_id, message_id,
            reply_markup=reply_markup,
            parse_mode=None
        )
    except Exception:
        # Сообщение нельзя отредактировать (старое или удалено) — отправляем новое
        bot.send_message(chat_id, text, reply_markup=reply_markup)


def cancel_button(callback_data="back_to_menu", text="❌ Отмена"):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text, callback_data=callback_data))
    return markup


def back_button(callback="back_to_menu", text="◀️ В меню"):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text, callback_data=callback))
    return markup


# ========== ГЛАВНОЕ МЕНЮ ==========

def main_menu_markup(user_id: int):
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


def main_menu_text(user):
    role_text = "👑 Администратор" if user["role"] == "admin" else "👤 Пользователь"
    return (
        f"🔧 Бот учёта инструментов\n\n"
        f"👋 Привет, {user['full_name']}!\n"
        f"Ваша роль: {role_text}\n\n"
        f"Выберите действие или используйте /help"
    )


def show_main_menu_new_message(chat_id, user):
    bot.send_message(
        chat_id,
        main_menu_text(user),
        reply_markup=main_menu_markup(user["telegram_id"])
    )


# ========== КОМАНДЫ ==========

@bot.message_handler(commands=['start', 'старт'])
def cmd_start(message):
    user_id = message.from_user.id

    if INITIAL_ADMIN_ID and user_id == INITIAL_ADMIN_ID:
        if not db.is_registered(user_id):
            db.add_user(user_id, "Главный администратор", role="admin")

    if not check_access(user_id):
        bot.send_message(
            message.chat.id,
            "⛔ У вас нет доступа к этому боту.\n\n"
            "Обратитесь к администратору для регистрации.\n"
            f"Сообщите ему ваш Telegram ID: <code>{user_id}</code>",
            parse_mode="HTML"
        )
        return

    clear_pending(user_id)
    user = db.get_user_by_telegram_id(user_id)
    show_main_menu_new_message(message.chat.id, user)


@bot.message_handler(commands=['menu', 'меню'])
def cmd_menu(message):
    user_id = message.from_user.id
    if not check_access(user_id):
        return
    clear_pending(user_id)
    user = db.get_user_by_telegram_id(user_id)
    show_main_menu_new_message(message.chat.id, user)


@bot.message_handler(commands=['cancel', 'отмена'])
def cmd_cancel(message):
    user_id = message.from_user.id
    if not check_access(user_id):
        return
    if get_pending(user_id):
        clear_pending(user_id)
        bot.send_message(message.chat.id, "❌ Действие отменено.\n/menu — вернуться в меню")
    else:
        bot.send_message(message.chat.id, "Нет активных действий. /menu — открыть меню")


@bot.message_handler(commands=['help', 'помощь'])
def cmd_help(message):
    user_id = message.from_user.id
    if not check_access(user_id):
        return
    is_adm = db.is_admin(user_id)
    text = (
        "📖 Доступные команды:\n\n"
        "/start — начать работу\n"
        "/menu — главное меню\n"
        "/tools — все инструменты\n"
        "/categories — список категорий\n"
        "/stats — статистика\n"
        "/cancel — отменить текущее действие\n"
        "/help — эта справка"
    )
    if is_adm:
        text += (
            "\n\nКоманды администратора:\n"
            "/add — добавить инструмент\n"
            "/users — управление пользователями\n"
            "/cats — управление категориями"
        )
    bot.send_message(message.chat.id, text)


@bot.message_handler(commands=['tools', 'инструменты'])
def cmd_tools(message):
    user_id = message.from_user.id
    if not check_access(user_id):
        return
    clear_pending(user_id)
    tools = db.get_all_tools()
    if not tools:
        bot.send_message(message.chat.id, "📭 Инструментов пока нет", reply_markup=back_button())
        return
    text = "📋 Все инструменты:\n\n"
    for t in tools:
        cat = t['category_name'] or "без категории"
        owner = t['owner_name'] or "—"
        text += f"🔧 {t['name']}\n   📂 {cat}\n   👤 {owner}\n\n"
    bot.send_message(message.chat.id, text, reply_markup=back_button())


@bot.message_handler(commands=['categories', 'категории'])
def cmd_categories(message):
    user_id = message.from_user.id
    if not check_access(user_id):
        return
    clear_pending(user_id)
    msg = bot.send_message(message.chat.id, "Загрузка...")
    show_categories_view(message.chat.id, msg.message_id)


@bot.message_handler(commands=['stats', 'статистика'])
def cmd_stats(message):
    user_id = message.from_user.id
    if not check_access(user_id):
        return
    clear_pending(user_id)
    stats = db.get_statistics()
    text = (
        f"📊 Статистика\n\n"
        f"🔧 Активных инструментов: {stats['total_tools']}\n"
        f"🗑 Списано: {stats['written_off']}\n"
        f"🔄 Подтверждённых передач: {stats['transfers']}\n"
        f"📂 Категорий: {stats['categories']}\n"
        f"👥 Пользователей: {stats['users']}"
    )
    bot.send_message(message.chat.id, text, reply_markup=back_button())


@bot.message_handler(commands=['add', 'добавить'])
def cmd_add(message):
    user_id = message.from_user.id
    if not check_access(user_id):
        return
    if not db.is_admin(user_id):
        bot.send_message(message.chat.id, "⛔ Команда доступна только администраторам")
        return
    clear_pending(user_id)
    msg = bot.send_message(message.chat.id, "Загрузка...")
    start_add_tool_flow(message.chat.id, msg.message_id)


@bot.message_handler(commands=['users', 'пользователи'])
def cmd_users(message):
    user_id = message.from_user.id
    if not check_access(user_id) or not db.is_admin(user_id):
        return
    clear_pending(user_id)
    msg = bot.send_message(message.chat.id, "Загрузка...")
    show_manage_users(message.chat.id, msg.message_id)


@bot.message_handler(commands=['cats'])
def cmd_cats(message):
    user_id = message.from_user.id
    if not check_access(user_id) or not db.is_admin(user_id):
        return
    clear_pending(user_id)
    msg = bot.send_message(message.chat.id, "Загрузка...")
    show_manage_categories(message.chat.id, msg.message_id)


# ========== ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ ==========

@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text(message):
    user_id = message.from_user.id
    if not check_access(user_id):
        return

    pending = get_pending(user_id)
    if not pending:
        bot.send_message(
            message.chat.id,
            "Не понял запрос. Используйте команды:\n/menu — меню, /help — справка"
        )
        return

    action = pending["action"]
    data = pending["data"]
    text = message.text.strip()

    if action == "add_category_name":
        process_add_category(message.chat.id, user_id, text)
    elif action == "rename_category":
        process_rename_category(message.chat.id, user_id, data["category_id"], text)
    elif action == "add_user_id":
        process_add_user_id(message.chat.id, user_id, text)
    elif action == "add_user_name":
        process_add_user_name(message.chat.id, user_id, data["telegram_id"], text)
    elif action == "rename_user":
        process_rename_user(message.chat.id, user_id, data["target_id"], text)
    elif action == "add_tool_name":
        process_add_tool_name(message.chat.id, user_id, data["category_id"], data["owner_id"], text)
    elif action == "rename_tool":
        process_rename_tool(message.chat.id, user_id, data["tool_id"], text)
    elif action == "writeoff_custom_reason":
        process_writeoff_custom_reason(message.chat.id, user_id, data["tool_id"], text)


# ========== CALLBACK HANDLER ==========

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    msg_id = call.message.message_id

    if not check_access(user_id):
        bot.answer_callback_query(call.id, "⛔ Нет доступа", show_alert=True)
        return

    data = call.data
    bot.answer_callback_query(call.id)

    if data == "back_to_menu":
        clear_pending(user_id)
        user = db.get_user_by_telegram_id(user_id)
        safe_edit(chat_id, msg_id, main_menu_text(user), main_menu_markup(user_id))
        return

    if data == "categories":
        show_categories_view(chat_id, msg_id)
        return

    if data.startswith("cat_view_"):
        category_id = int(data.replace("cat_view_", ""))
        show_tools_in_category(chat_id, msg_id, category_id)
        return

    if data == "list_all":
        show_all_tools_view(chat_id, msg_id)
        return

    if data == "stats":
        show_stats_view(chat_id, msg_id)
        return

    if data.startswith("tool_view_"):
        tool_id = int(data.replace("tool_view_", ""))
        show_tool_details(chat_id, msg_id, user_id, tool_id)
        return

    if data.startswith("tool_history_"):
        tool_id = int(data.replace("tool_history_", ""))
        show_tool_history(chat_id, msg_id, tool_id)
        return

    if data.startswith("tool_transfer_"):
        tool_id = int(data.replace("tool_transfer_", ""))
        start_transfer(chat_id, msg_id, user_id, tool_id)
        return

    if data.startswith("tool_writeoff_"):
        if not db.is_admin(user_id):
            bot.answer_callback_query(call.id, "⛔ Только админ", show_alert=True)
            return
        tool_id = int(data.replace("tool_writeoff_", ""))
        ask_writeoff_reason(chat_id, msg_id, tool_id)
        return

    if data.startswith("tool_rename_"):
        if not db.is_admin(user_id):
            return
        tool_id = int(data.replace("tool_rename_", ""))
        tool = db.get_tool_by_id(tool_id)
        if tool:
            set_pending(user_id, "rename_tool", {"tool_id": tool_id}, msg_id)
            safe_edit(
                chat_id, msg_id,
                f"✏️ Переименование '{tool['name']}'\n\nВведите новое название:",
                cancel_button(f"tool_view_{tool_id}")
            )
        return

    if data == "add_tool":
        if not db.is_admin(user_id):
            bot.answer_callback_query(call.id, "⛔ Только админ", show_alert=True)
            return
        start_add_tool_flow(chat_id, msg_id)
        return

    if data.startswith("addtool_cat_"):
        category_id = int(data.replace("addtool_cat_", ""))
        ask_tool_owner(chat_id, msg_id, category_id)
        return

    if data.startswith("addtool_owner_"):
        parts = data.replace("addtool_owner_", "").split("_")
        category_id = int(parts[0])
        owner_id = int(parts[1])
        set_pending(user_id, "add_tool_name",
                    {"category_id": category_id, "owner_id": owner_id}, msg_id)
        safe_edit(
            chat_id, msg_id,
            "📝 Шаг 3/3: Введите название инструмента:",
            cancel_button("back_to_menu")
        )
        return

    if data.startswith("transfer_to_"):
        parts = data.replace("transfer_to_", "").split("_")
        tool_id = int(parts[0])
        to_user_id = int(parts[1])
        send_transfer_request(chat_id, msg_id, user_id, tool_id, to_user_id)
        return

    if data.startswith("confirm_tr_"):
        transfer_id = int(data.replace("confirm_tr_", ""))
        handle_transfer_confirm(call, transfer_id)
        return

    if data.startswith("reject_tr_"):
        transfer_id = int(data.replace("reject_tr_", ""))
        handle_transfer_reject(call, transfer_id)
        return

    if data.startswith("writeoff_reason_"):
        parts = data.replace("writeoff_reason_", "").split("_", 1)
        tool_id = int(parts[0])
        reason_key = parts[1]
        process_writeoff(chat_id, msg_id, user_id, tool_id, reason_key)
        return

    if data.startswith("confirm_writeoff_"):
        parts = data.replace("confirm_writeoff_", "").split("_", 1)
        tool_id = int(parts[0])
        reason_key = parts[1]
        finalize_writeoff_simple(chat_id, msg_id, tool_id, reason_key)
        return

    if data == "manage_cats":
        if not db.is_admin(user_id):
            return
        show_manage_categories(chat_id, msg_id)
        return

    if data == "add_category":
        if not db.is_admin(user_id):
            return
        set_pending(user_id, "add_category_name", {}, msg_id)
        safe_edit(
            chat_id, msg_id,
            "📝 Введите название новой категории:",
            cancel_button("manage_cats")
        )
        return

    if data.startswith("cat_rename_"):
        if not db.is_admin(user_id):
            return
        category_id = int(data.replace("cat_rename_", ""))
        cat = db.get_category_by_id(category_id)
        if cat:
            set_pending(user_id, "rename_category", {"category_id": category_id}, msg_id)
            safe_edit(
                chat_id, msg_id,
                f"✏️ Переименование категории '{cat['name']}'\n\nВведите новое название:",
                cancel_button("manage_cats")
            )
        return

    if data.startswith("cat_delete_confirm_"):
        if not db.is_admin(user_id):
            return
        category_id = int(data.replace("cat_delete_confirm_", ""))
        db.delete_category(category_id)
        show_manage_categories(chat_id, msg_id, header="🗑 Категория удалена\n\n")
        return

    if data.startswith("cat_delete_"):
        if not db.is_admin(user_id):
            return
        category_id = int(data.replace("cat_delete_", ""))
        cat = db.get_category_by_id(category_id)
        if cat:
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("✅ Да, удалить", callback_data=f"cat_delete_confirm_{category_id}"),
                InlineKeyboardButton("❌ Отмена", callback_data="manage_cats")
            )
            safe_edit(
                chat_id, msg_id,
                f"⚠️ Удалить категорию '{cat['name']}'?\n\n"
                f"Инструменты не удалятся, но останутся без категории.",
                markup
            )
        return

    if data == "manage_users":
        if not db.is_admin(user_id):
            return
        show_manage_users(chat_id, msg_id)
        return

    if data == "add_user":
        if not db.is_admin(user_id):
            return
        set_pending(user_id, "add_user_id", {}, msg_id)
        safe_edit(
            chat_id, msg_id,
            "📝 Шаг 1/2: Введите Telegram ID нового пользователя\n\n"
            "(узнать ID можно у @userinfobot)",
            cancel_button("manage_users")
        )
        return

    if data.startswith("user_view_"):
        if not db.is_admin(user_id):
            return
        target_id = int(data.replace("user_view_", ""))
        show_user_details(chat_id, msg_id, target_id)
        return

    if data.startswith("user_rename_"):
        if not db.is_admin(user_id):
            return
        target_id = int(data.replace("user_rename_", ""))
        user = db.get_user_by_id(target_id)
        if user:
            set_pending(user_id, "rename_user", {"target_id": target_id}, msg_id)
            safe_edit(
                chat_id, msg_id,
                f"✏️ Переименование '{user['full_name']}'\n\nВведите новое имя:",
                cancel_button(f"user_view_{target_id}")
            )
        return

    if data.startswith("user_role_confirm_"):
        if not db.is_admin(user_id):
            return
        target_id = int(data.replace("user_role_confirm_", ""))
        user = db.get_user_by_id(target_id)
        if user:
            new_role = "user" if user['role'] == "admin" else "admin"
            db.update_user(target_id, role=new_role)
        show_user_details(chat_id, msg_id, target_id)
        return

    if data.startswith("user_role_"):
        if not db.is_admin(user_id):
            return
        target_id = int(data.replace("user_role_", ""))
        user = db.get_user_by_id(target_id)
        if user:
            new_role = "user" if user['role'] == "admin" else "admin"
            new_role_label = "пользователем" if new_role == "user" else "администратором"
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("✅ Да", callback_data=f"user_role_confirm_{target_id}"),
                InlineKeyboardButton("❌ Отмена", callback_data=f"user_view_{target_id}")
            )
            safe_edit(
                chat_id, msg_id,
                f"⚠️ Сделать '{user['full_name']}' {new_role_label}?",
                markup
            )
        return

    if data.startswith("user_delete_confirm_"):
        if not db.is_admin(user_id):
            return
        target_id = int(data.replace("user_delete_confirm_", ""))
        db.soft_delete_user(target_id)
        show_manage_users(chat_id, msg_id, header="🗑 Пользователь удалён\n\n")
        return

    if data.startswith("user_delete_"):
        if not db.is_admin(user_id):
            return
        target_id = int(data.replace("user_delete_", ""))
        user = db.get_user_by_id(target_id)
        if user:
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("✅ Да, удалить", callback_data=f"user_delete_confirm_{target_id}"),
                InlineKeyboardButton("❌ Отмена", callback_data=f"user_view_{target_id}")
            )
            safe_edit(
                chat_id, msg_id,
                f"⚠️ Удалить пользователя '{user['full_name']}'?\n\n"
                f"История его действий сохранится.",
                markup
            )
        return


# ========== ВЬЮХИ — КАТЕГОРИИ ==========

def show_categories_view(chat_id, msg_id):
    cats = db.get_all_categories()
    markup = InlineKeyboardMarkup(row_width=1)
    if not cats:
        text = "📭 Категорий пока нет.\n\nПопросите администратора создать категорию."
    else:
        text = "📂 Выберите категорию:"
        for cat in cats:
            markup.add(InlineKeyboardButton(
                f"📂 {cat['name']} ({cat['tools_count']})",
                callback_data=f"cat_view_{cat['id']}"
            ))
    markup.add(InlineKeyboardButton("◀️ В меню", callback_data="back_to_menu"))
    safe_edit(chat_id, msg_id, text, markup)


def show_tools_in_category(chat_id, msg_id, category_id: int):
    cat = db.get_category_by_id(category_id)
    if not cat:
        safe_edit(chat_id, msg_id, "❌ Категория не найдена", back_button())
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
    markup.add(InlineKeyboardButton("🏠 В меню", callback_data="back_to_menu"))
    safe_edit(chat_id, msg_id, text, markup)


def show_all_tools_view(chat_id, msg_id):
    tools = db.get_all_tools()
    if not tools:
        safe_edit(chat_id, msg_id, "📭 Инструментов пока нет", back_button())
        return
    text = "📋 Все инструменты:\n\n"
    for t in tools:
        cat = t['category_name'] or "без категории"
        owner = t['owner_name'] or "—"
        text += f"🔧 {t['name']}\n   📂 {cat}\n   👤 {owner}\n\n"
    safe_edit(chat_id, msg_id, text, back_button())


def show_stats_view(chat_id, msg_id):
    stats = db.get_statistics()
    text = (
        f"📊 Статистика\n\n"
        f"🔧 Активных инструментов: {stats['total_tools']}\n"
        f"🗑 Списано: {stats['written_off']}\n"
        f"🔄 Подтверждённых передач: {stats['transfers']}\n"
        f"📂 Категорий: {stats['categories']}\n"
        f"👥 Пользователей: {stats['users']}"
    )
    safe_edit(chat_id, msg_id, text, back_button())


# ========== ВЬЮХИ — ИНСТРУМЕНТ ==========

def show_tool_details(chat_id, msg_id, viewer_id: int, tool_id: int):
    tool = db.get_tool_by_id(tool_id)
    if not tool:
        safe_edit(chat_id, msg_id, "❌ Инструмент не найден", back_button())
        return
    cat = tool['category_name'] or "без категории"
    owner = tool['owner_name'] or "—"
    status = "✅ Активен" if tool['status'] == 'active' else "🗑 Списан"
    text = f"🔧 {tool['name']}\n\n📂 Категория: {cat}\n👤 Владелец: {owner}\n📊 Статус: {status}"
    if tool['status'] == 'written_off' and tool['write_off_reason']:
        text += f"\n📝 Причина: {tool['write_off_reason']}"

    markup = InlineKeyboardMarkup(row_width=1)
    is_adm = db.is_admin(viewer_id)
    if tool['status'] == 'active':
        markup.add(InlineKeyboardButton("🔄 Передать", callback_data=f"tool_transfer_{tool_id}"))
    markup.add(InlineKeyboardButton("📜 История", callback_data=f"tool_history_{tool_id}"))
    if is_adm and tool['status'] == 'active':
        markup.add(InlineKeyboardButton("✏️ Переименовать", callback_data=f"tool_rename_{tool_id}"))
        markup.add(InlineKeyboardButton("🗑 Списать", callback_data=f"tool_writeoff_{tool_id}"))
    if tool['category_id']:
        markup.add(InlineKeyboardButton("◀️ К категории", callback_data=f"cat_view_{tool['category_id']}"))
    markup.add(InlineKeyboardButton("🏠 В меню", callback_data="back_to_menu"))

    safe_edit(chat_id, msg_id, text, markup)


def show_tool_history(chat_id, msg_id, tool_id: int):
    tool = db.get_tool_by_id(tool_id)
    if not tool:
        safe_edit(chat_id, msg_id, "❌ Инструмент не найден", back_button())
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
    markup.add(InlineKeyboardButton("🏠 В меню", callback_data="back_to_menu"))
    safe_edit(chat_id, msg_id, text, markup)


# ========== ДОБАВЛЕНИЕ ИНСТРУМЕНТА ==========

def start_add_tool_flow(chat_id, msg_id):
    cats = db.get_all_categories()
    if not cats:
        safe_edit(
            chat_id, msg_id,
            "❌ Сначала создайте хотя бы одну категорию",
            back_button("manage_cats", "🗂 К категориям")
        )
        return
    markup = InlineKeyboardMarkup(row_width=1)
    for cat in cats:
        markup.add(InlineKeyboardButton(
            f"📂 {cat['name']}", callback_data=f"addtool_cat_{cat['id']}"
        ))
    markup.add(InlineKeyboardButton("❌ Отмена", callback_data="back_to_menu"))
    safe_edit(
        chat_id, msg_id,
        "📂 Шаг 1/3: Выберите категорию для нового инструмента:",
        markup
    )


def ask_tool_owner(chat_id, msg_id, category_id: int):
    users = db.get_all_users()
    if not users:
        safe_edit(
            chat_id, msg_id,
            "❌ Нет зарегистрированных пользователей",
            back_button()
        )
        return
    markup = InlineKeyboardMarkup(row_width=1)
    for u in users:
        markup.add(InlineKeyboardButton(
            f"👤 {u['full_name']}",
            callback_data=f"addtool_owner_{category_id}_{u['id']}"
        ))
    markup.add(InlineKeyboardButton("❌ Отмена", callback_data="back_to_menu"))
    safe_edit(
        chat_id, msg_id,
        "👤 Шаг 2/3: За кем закрепить инструмент?",
        markup
    )


def process_add_tool_name(chat_id, user_id, category_id: int, owner_id: int, name: str):
    pending = get_pending(user_id)
    msg_id = pending["msg_id"] if pending else None
    clear_pending(user_id)

    if not name:
        if msg_id:
            safe_edit(chat_id, msg_id, "❌ Название не может быть пустым", back_button())
        return

    tool = db.add_tool(name, category_id, owner_id)

    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton(f"🔧 Открыть '{tool['name']}'", callback_data=f"tool_view_{tool['id']}"))
    markup.add(InlineKeyboardButton("➕ Добавить ещё", callback_data="add_tool"))
    markup.add(InlineKeyboardButton("🏠 В меню", callback_data="back_to_menu"))

    if msg_id:
        safe_edit(chat_id, msg_id, f"✅ Инструмент '{tool['name']}' добавлен!", markup)
    else:
        bot.send_message(chat_id, f"✅ Инструмент '{tool['name']}' добавлен!", reply_markup=markup)


def process_rename_tool(chat_id, user_id, tool_id: int, new_name: str):
    pending = get_pending(user_id)
    msg_id = pending["msg_id"] if pending else None
    clear_pending(user_id)

    if not new_name:
        if msg_id:
            safe_edit(chat_id, msg_id, "❌ Название не может быть пустым", back_button())
        return

    if db.rename_tool(tool_id, new_name):
        if msg_id:
            show_tool_details(chat_id, msg_id, user_id, tool_id)
        else:
            bot.send_message(chat_id, f"✅ Переименован в '{new_name}'", reply_markup=back_button())


# ========== ПЕРЕДАЧА ==========

def start_transfer(chat_id, msg_id, user_id: int, tool_id: int):
    tool = db.get_tool_by_id(tool_id)
    if not tool or tool['status'] != 'active':
        safe_edit(chat_id, msg_id, "❌ Инструмент недоступен", back_button())
        return
    user = db.get_user_by_telegram_id(user_id)
    if user['role'] != 'admin' and tool['current_owner_id'] != user['id']:
        bot.send_message(chat_id, "⛔ Передавать может только текущий владелец или админ")
        return

    users = db.get_all_users()
    users = [u for u in users if u['id'] != tool['current_owner_id']]
    if not users:
        safe_edit(chat_id, msg_id, "❌ Некому передать", back_button(f"tool_view_{tool_id}", "◀️ Назад"))
        return

    markup = InlineKeyboardMarkup(row_width=1)
    for u in users:
        markup.add(InlineKeyboardButton(
            f"👤 {u['full_name']}",
            callback_data=f"transfer_to_{tool_id}_{u['id']}"
        ))
    markup.add(InlineKeyboardButton("❌ Отмена", callback_data=f"tool_view_{tool_id}"))
    safe_edit(
        chat_id, msg_id,
        f"🔄 Передать '{tool['name']}'\n\nКому передаёте?",
        markup
    )


def send_transfer_request(chat_id, msg_id, user_id, tool_id: int, to_user_id: int):
    tool = db.get_tool_by_id(tool_id)
    to_user = db.get_user_by_id(to_user_id)
    from_user = db.get_user_by_telegram_id(user_id)

    if not tool or not to_user or not from_user:
        safe_edit(chat_id, msg_id, "❌ Ошибка", back_button())
        return

    transfer = db.create_transfer_request(tool_id, from_user['id'], to_user_id)

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
    except Exception:
        safe_edit(
            chat_id, msg_id,
            f"⚠️ Не удалось отправить уведомление получателю.\n"
            f"Возможно, он не запускал бота командой /start",
            back_button(f"tool_view_{tool_id}", "◀️ Назад")
        )
        return

    safe_edit(
        chat_id, msg_id,
        f"⏳ Запрос на передачу '{tool['name']}' отправлен пользователю {to_user['full_name']}.\n"
        f"Ожидаем подтверждения.",
        back_button()
    )


def handle_transfer_confirm(call, transfer_id: int):
    transfer = db.get_transfer_by_id(transfer_id)
    if not transfer:
        safe_edit(call.message.chat.id, call.message.message_id,
                  "❌ Передача не найдена", back_button())
        return
    if transfer['to_telegram_id'] != call.from_user.id:
        bot.answer_callback_query(call.id, "⛔ Подтвердить может только получатель", show_alert=True)
        return
    if transfer['status'] != 'pending':
        safe_edit(call.message.chat.id, call.message.message_id,
                  "⚠️ Запрос уже обработан", back_button())
        return

    db.confirm_transfer(transfer_id)
    safe_edit(
        call.message.chat.id, call.message.message_id,
        f"✅ Вы подтвердили получение '{transfer['tool_name']}'.\n"
        f"Инструмент закреплён за вами.",
        back_button()
    )
    try:
        bot.send_message(
            transfer['from_telegram_id'],
            f"✅ {transfer['to_name']} подтвердил(а) получение инструмента '{transfer['tool_name']}'."
        )
    except Exception:
        pass


def handle_transfer_reject(call, transfer_id: int):
    transfer = db.get_transfer_by_id(transfer_id)
    if not transfer:
        return
    if transfer['to_telegram_id'] != call.from_user.id:
        bot.answer_callback_query(call.id, "⛔ Только получатель может отказать", show_alert=True)
        return
    if transfer['status'] != 'pending':
        safe_edit(call.message.chat.id, call.message.message_id,
                  "⚠️ Запрос уже обработан", back_button())
        return

    db.reject_transfer(transfer_id)
    safe_edit(
        call.message.chat.id, call.message.message_id,
        f"❌ Вы отказались от инструмента '{transfer['tool_name']}'.\n"
        f"Инструмент остался у прежнего владельца.",
        back_button()
    )
    try:
        bot.send_message(
            transfer['from_telegram_id'],
            f"❌ {transfer['to_name']} отказался(ась) от инструмента '{transfer['tool_name']}'."
        )
    except Exception:
        pass


# ========== СПИСАНИЕ ==========

WRITEOFF_REASONS = {
    "wear": "Износ / выработан ресурс",
    "broken": "Поломка",
    "sold": "Продажа",
    "lost": "Утеря",
    "stolen": "Кража",
    "other": "Другое",
}


def ask_writeoff_reason(chat_id, msg_id, tool_id: int):
    tool = db.get_tool_by_id(tool_id)
    if not tool:
        return
    markup = InlineKeyboardMarkup(row_width=1)
    for key, label in WRITEOFF_REASONS.items():
        markup.add(InlineKeyboardButton(
            label, callback_data=f"writeoff_reason_{tool_id}_{key}"
        ))
    markup.add(InlineKeyboardButton("❌ Отмена", callback_data=f"tool_view_{tool_id}"))
    safe_edit(
        chat_id, msg_id,
        f"🗑 Списание '{tool['name']}'\n\nВыберите причину:",
        markup
    )


def process_writeoff(chat_id, msg_id, user_id, tool_id: int, reason_key: str):
    if reason_key == "other":
        set_pending(user_id, "writeoff_custom_reason", {"tool_id": tool_id}, msg_id)
        safe_edit(
            chat_id, msg_id,
            "📝 Введите причину списания:",
            cancel_button(f"tool_view_{tool_id}")
        )
        return

    tool = db.get_tool_by_id(tool_id)
    reason = WRITEOFF_REASONS.get(reason_key, "не указана")
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✅ Да, списать", callback_data=f"confirm_writeoff_{tool_id}_{reason_key}"),
        InlineKeyboardButton("❌ Отмена", callback_data=f"tool_view_{tool_id}")
    )
    safe_edit(
        chat_id, msg_id,
        f"⚠️ Подтвердите списание\n\n🔧 {tool['name']}\n📝 Причина: {reason}",
        markup
    )


def finalize_writeoff_simple(chat_id, msg_id, tool_id: int, reason_key: str):
    reason = WRITEOFF_REASONS.get(reason_key, "не указана")
    if db.write_off_tool(tool_id, reason):
        tool = db.get_tool_by_id(tool_id)
        safe_edit(
            chat_id, msg_id,
            f"🗑 '{tool['name']}' списан\nПричина: {reason}",
            back_button()
        )


def process_writeoff_custom_reason(chat_id, user_id, tool_id: int, reason: str):
    pending = get_pending(user_id)
    msg_id = pending["msg_id"] if pending else None
    clear_pending(user_id)

    if not reason:
        if msg_id:
            safe_edit(chat_id, msg_id, "❌ Причина не может быть пустой", back_button())
        return

    if db.write_off_tool(tool_id, reason):
        tool = db.get_tool_by_id(tool_id)
        text = f"🗑 '{tool['name']}' списан\nПричина: {reason}"
        if msg_id:
            safe_edit(chat_id, msg_id, text, back_button())
        else:
            bot.send_message(chat_id, text, reply_markup=back_button())


# ========== УПРАВЛЕНИЕ КАТЕГОРИЯМИ ==========

def show_manage_categories(chat_id, msg_id, header: str = ""):
    cats = db.get_all_categories()
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("➕ Добавить категорию", callback_data="add_category"))
    for cat in cats:
        markup.add(InlineKeyboardButton(
            f"✏️ {cat['name']} ({cat['tools_count']})",
            callback_data=f"cat_rename_{cat['id']}"
        ))
        markup.add(InlineKeyboardButton(
            f"🗑 Удалить '{cat['name']}'",
            callback_data=f"cat_delete_{cat['id']}"
        ))
    markup.add(InlineKeyboardButton("🏠 В меню", callback_data="back_to_menu"))
    text = header + "🗂 Управление категориями\n\nДля переименования нажмите ✏️"
    safe_edit(chat_id, msg_id, text, markup)


def process_add_category(chat_id, user_id, name: str):
    pending = get_pending(user_id)
    msg_id = pending["msg_id"] if pending else None
    clear_pending(user_id)

    if not name:
        if msg_id:
            safe_edit(chat_id, msg_id, "❌ Название не может быть пустым", back_button())
        return

    cat = db.add_category(name)
    if cat:
        if msg_id:
            show_manage_categories(chat_id, msg_id, header=f"✅ Категория '{name}' создана\n\n")
        else:
            bot.send_message(chat_id, f"✅ Категория '{name}' создана!", reply_markup=back_button())
    else:
        if msg_id:
            safe_edit(chat_id, msg_id, f"⚠️ Категория '{name}' уже существует", back_button("manage_cats"))


def process_rename_category(chat_id, user_id, category_id: int, new_name: str):
    pending = get_pending(user_id)
    msg_id = pending["msg_id"] if pending else None
    clear_pending(user_id)

    if not new_name:
        if msg_id:
            safe_edit(chat_id, msg_id, "❌ Название не может быть пустым", back_button("manage_cats"))
        return

    if db.rename_category(category_id, new_name):
        if msg_id:
            show_manage_categories(chat_id, msg_id, header=f"✅ Переименовано в '{new_name}'\n\n")


# ========== УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ ==========

def show_manage_users(chat_id, msg_id, header: str = ""):
    users = db.get_all_users()
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("➕ Добавить пользователя", callback_data="add_user"))
    for u in users:
        role_icon = "👑" if u['role'] == 'admin' else "👤"
        markup.add(InlineKeyboardButton(
            f"{role_icon} {u['full_name']}",
            callback_data=f"user_view_{u['id']}"
        ))
    markup.add(InlineKeyboardButton("🏠 В меню", callback_data="back_to_menu"))
    safe_edit(chat_id, msg_id, header + "👥 Пользователи системы:", markup)


def show_user_details(chat_id, msg_id, target_id: int):
    user = db.get_user_by_id(target_id)
    if not user:
        safe_edit(chat_id, msg_id, "❌ Пользователь не найден", back_button())
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
    safe_edit(chat_id, msg_id, text, markup)


def process_add_user_id(chat_id, user_id, text: str):
    pending = get_pending(user_id)
    msg_id = pending["msg_id"] if pending else None

    try:
        new_tg_id = int(text)
    except ValueError:
        if msg_id:
            safe_edit(
                chat_id, msg_id,
                "❌ Telegram ID должен быть числом\n\nПопробуйте ещё раз:",
                cancel_button("manage_users")
            )
        return

    set_pending(user_id, "add_user_name", {"telegram_id": new_tg_id}, msg_id)
    if msg_id:
        safe_edit(
            chat_id, msg_id,
            f"📝 Шаг 2/2: Введите имя пользователя\n\nID: {new_tg_id}\n\n(например: Иванов Иван)",
            cancel_button("manage_users")
        )


def process_add_user_name(chat_id, user_id, telegram_id: int, full_name: str):
    pending = get_pending(user_id)
    msg_id = pending["msg_id"] if pending else None
    clear_pending(user_id)

    if not full_name:
        if msg_id:
            safe_edit(chat_id, msg_id, "❌ Имя не может быть пустым", back_button("manage_users"))
        return

    db.add_user(telegram_id, full_name, role="user")
    text = (
        f"✅ Пользователь '{full_name}' добавлен!\n"
        f"Попросите его запустить бота командой /start"
    )
    if msg_id:
        show_manage_users(chat_id, msg_id, header=text + "\n\n")


def process_rename_user(chat_id, user_id, target_id: int, new_name: str):
    pending = get_pending(user_id)
    msg_id = pending["msg_id"] if pending else None
    clear_pending(user_id)

    if not new_name:
        if msg_id:
            safe_edit(chat_id, msg_id, "❌ Имя не может быть пустым", back_button())
        return

    if db.update_user(target_id, full_name=new_name):
        if msg_id:
            show_user_details(chat_id, msg_id, target_id)


# ========== FLASK ДЛЯ RAILWAY ==========

app = Flask(__name__)


@app.route('/')
def home():
    return "✅ Бот учёта инструментов работает!"


def run_bot():
    print("🚀 Бот запущен")
    bot.infinity_polling()


# ========== УСТАНОВКА КОМАНД В МЕНЮ TELEGRAM ==========

def setup_bot_commands():
    """Регистрирует команды чтобы они отображались в меню Telegram (синяя кнопка / )."""
    from telebot.types import BotCommand
    commands = [
        BotCommand("menu", "Главное меню"),
        BotCommand("tools", "Все инструменты"),
        BotCommand("categories", "Категории"),
        BotCommand("stats", "Статистика"),
        BotCommand("add", "Добавить инструмент (админ)"),
        BotCommand("users", "Пользователи (админ)"),
        BotCommand("cats", "Категории — управление (админ)"),
        BotCommand("cancel", "Отменить текущее действие"),
        BotCommand("help", "Справка"),
    ]
    try:
        bot.set_my_commands(commands)
        print("✅ Команды зарегистрированы в меню Telegram")
    except Exception as e:
        print(f"⚠️ Не удалось зарегистрировать команды: {e}")


# ========== ЗАПУСК ==========

if __name__ == "__main__":
    db.init_db()
    ensure_initial_admin()
    setup_bot_commands()

    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()

    port = int(os.environ.get("PORT", 5000))
    print(f"🌐 Веб-сервер запущен на порту {port}")
    app.run(host='0.0.0.0', port=port)
