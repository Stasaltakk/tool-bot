import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import json
import os
import time
from flask import Flask
import threading

# ========== ПРОКСИ ЧЕРЕЗ CLOUDFLARE WORKER (ОПЦИОНАЛЬНО) ==========
# Если не используешь прокси - закомментируй следующую строку
# telebot.apihelper.API_URL = "https://tg-proxy.kkotleta464.workers.dev/bot{0}/{1}"

# ========== ТОКЕН ==========
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    print("❌ Ошибка: BOT_TOKEN не найден!")
    exit(1)

bot = telebot.TeleBot(TOKEN)

# ========== НАСТРОЙКИ ==========
ADMINS = [1610947558, 134827143]  # Твой Telegram ID

# ========== ХРАНИЛИЩЕ ==========
tools = {}
# ========== ХРАНИЛИЩЕ ==========
# Определяем папку для данных (используем Railway volume или локальную папку)
DATA_DIR = os.environ.get("DATA_DIR", "/app/data" if os.path.exists("/app/data") else ".")
os.makedirs(DATA_DIR, exist_ok=True)
DATA_FILE = os.path.join(DATA_DIR, "tools_data.json")

tools = {}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(tools, f, ensure_ascii=False, indent=2)

def load_data():
    global tools
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            tools = json.load(f)

load_data()

def is_admin(user_id):
    return user_id in ADMINS

def main_menu():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("➕ Добавить инструмент (админ)", callback_data="add"))
    markup.add(InlineKeyboardButton("✏️ Редактировать инструмент (админ)", callback_data="edit"))
    markup.add(InlineKeyboardButton("🗑️ Удалить инструмент (админ)", callback_data="delete"))
    markup.add(InlineKeyboardButton("🔄 Передать инструмент", callback_data="transfer"))
    markup.add(InlineKeyboardButton("👤 У кого инструмент?", callback_data="who_has"))
    markup.add(InlineKeyboardButton("📋 Список всех инструментов", callback_data="list"))
    markup.add(InlineKeyboardButton("📜 История передач", callback_data="history"))
    markup.add(InlineKeyboardButton("📊 Статистика", callback_data="stats"))
    return markup

def tools_list_menu(action, message):
    if not tools:
        return None
    markup = InlineKeyboardMarkup(row_width=1)
    for tool_name in tools.keys():
        markup.add(InlineKeyboardButton(f"🔧 {tool_name}", callback_data=f"{action}_{tool_name}"))
    markup.add(InlineKeyboardButton("◀️ Назад в меню", callback_data="back_to_menu"))
    return markup

@bot.message_handler(commands=['старт', 'start'])
def start(message):
    user_id = message.from_user.id
    admin_status = "✅ Вы АДМИНИСТРАТОР" if is_admin(user_id) else "❌ Вы обычный пользователь"
    bot.send_message(
        message.chat.id,
        f"🔧 Привет! Я бот для учёта инструментов.\n\n"
        f"👤 Ваш статус: {admin_status}\n\n"
        f"Выбери действие:",
        reply_markup=main_menu()
    )

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    if call.data == "add":
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "⛔ Только администратор!", show_alert=True)
            return
        msg = bot.send_message(call.message.chat.id, "🔧 Введи название инструмента:")
        bot.register_next_step_handler(msg, add_tool)
        bot.answer_callback_query(call.id)
    
    elif call.data == "edit":
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "⛔ Только администратор!", show_alert=True)
            return
        if not tools:
            bot.answer_callback_query(call.id, "📭 Список пуст!", show_alert=True)
            return
        markup = InlineKeyboardMarkup(row_width=1)
        for tool_name in tools.keys():
            markup.add(InlineKeyboardButton(f"🔧 {tool_name}", callback_data=f"edit_select_{tool_name}"))
        markup.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu"))
        bot.edit_message_text("✏️ Выбери инструмент для редактирования:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        bot.answer_callback_query(call.id)
    
    elif call.data == "delete":
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "⛔ Только администратор!", show_alert=True)
            return
        if not tools:
            bot.answer_callback_query(call.id, "📭 Список пуст!", show_alert=True)
            return
        markup = InlineKeyboardMarkup(row_width=1)
        for tool_name in tools.keys():
            markup.add(InlineKeyboardButton(f"🔧 {tool_name}", callback_data=f"delete_select_{tool_name}"))
        markup.add(InlineKeyboardButton("◀️ Назад", callback_data="back_to_menu"))
        bot.edit_message_text("🗑️ Выбери инструмент для удаления:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        bot.answer_callback_query(call.id)
    
    elif call.data == "transfer":
        if not tools:
            bot.answer_callback_query(call.id, "📭 Список пуст!", show_alert=True)
            return
        markup = tools_list_menu("transfer", call.message)
        bot.edit_message_text("🔧 Выбери инструмент для передачи:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        bot.answer_callback_query(call.id)
    
    elif call.data == "who_has":
        if not tools:
            bot.answer_callback_query(call.id, "📭 Список пуст!", show_alert=True)
            return
        markup = tools_list_menu("who", call.message)
        bot.edit_message_text("🔧 Выбери инструмент:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        bot.answer_callback_query(call.id)
    
    elif call.data == "list":
        show_all_tools(call.message)
        bot.answer_callback_query(call.id)
    
    elif call.data == "history":
        if not tools:
            bot.answer_callback_query(call.id, "📭 Список пуст!", show_alert=True)
            return
        markup = tools_list_menu("history", call.message)
        bot.edit_message_text("🔧 Выбери инструмент для истории:", call.message.chat.id, call.message.message_id, reply_markup=markup)
        bot.answer_callback_query(call.id)
    
    elif call.data == "stats":
        show_statistics(call.message)
        bot.answer_callback_query(call.id)
    
    elif call.data == "back_to_menu":
        bot.edit_message_text("🔧 Главное меню:", call.message.chat.id, call.message.message_id, reply_markup=main_menu())
        bot.answer_callback_query(call.id)
    
    elif call.data.startswith("transfer_"):
        tool_name = call.data.replace("transfer_", "")
        if tool_name not in tools:
            bot.answer_callback_query(call.id, "❌ Инструмент не найден!", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, f"📝 Кому передаёшь '{tool_name}'? (Введи имя/ФИО)")
        bot.register_next_step_handler(msg, lambda m: complete_transfer(m, tool_name))
    
    elif call.data.startswith("who_"):
        tool_name = call.data.replace("who_", "")
        who_has_tool(call.message, tool_name)
        bot.answer_callback_query(call.id)
    
    elif call.data.startswith("history_"):
        tool_name = call.data.replace("history_", "")
        show_history(call.message, tool_name)
        bot.answer_callback_query(call.id)
    
    elif call.data.startswith("edit_select_"):
        tool_name = call.data.replace("edit_select_", "")
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, f"✏️ Введи НОВОЕ название для '{tool_name}':")
        bot.register_next_step_handler(msg, lambda m: edit_tool(m, tool_name))
    
    elif call.data.startswith("delete_select_"):
        tool_name = call.data.replace("delete_select_", "")
        confirm_delete(call.message, tool_name)
        bot.answer_callback_query(call.id)
    
    elif call.data.startswith("confirm_delete_"):
        tool_name = call.data.replace("confirm_delete_", "")
        delete_tool(call.message, tool_name)
        bot.answer_callback_query(call.id)

def add_tool(message):
    tool_name = message.text.strip()
    if not tool_name:
        bot.send_message(message.chat.id, "❌ Название не может быть пустым!")
        bot.send_message(message.chat.id, "Выбери действие:", reply_markup=main_menu())
        return
    if tool_name in tools:
        bot.send_message(message.chat.id, f"⚠️ Инструмент '{tool_name}' уже есть!")
        bot.send_message(message.chat.id, "Выбери действие:", reply_markup=main_menu())
        return
    tools[tool_name] = {
        "current_owner": "на складе",
        "history": ["➕ Добавлен на склад"]
    }
    save_data()
    bot.send_message(message.chat.id, f"✅ Инструмент '{tool_name}' добавлен!")
    bot.send_message(message.chat.id, "Выбери действие:", reply_markup=main_menu())

def edit_tool(message, old_name):
    new_name = message.text.strip()
    if not new_name:
        bot.send_message(message.chat.id, "❌ Название не может быть пустым!")
        bot.send_message(message.chat.id, "Выбери действие:", reply_markup=main_menu())
        return
    if old_name not in tools:
        bot.send_message(message.chat.id, f"❌ Инструмент '{old_name}' не найден!")
        bot.send_message(message.chat.id, "Выбери действие:", reply_markup=main_menu())
        return
    if new_name == old_name:
        bot.send_message(message.chat.id, "⚠️ Новое название совпадает со старым.")
        bot.send_message(message.chat.id, "Выбери действие:", reply_markup=main_menu())
        return
    if new_name in tools:
        bot.send_message(message.chat.id, f"⚠️ '{new_name}' уже существует!")
        bot.send_message(message.chat.id, "Выбери действие:", reply_markup=main_menu())
        return
    
    tool_data = tools.pop(old_name)
    tool_data["history"].append(f"✏️ Переименован из '{old_name}' в '{new_name}'")
    tools[new_name] = tool_data
    save_data()
    bot.send_message(message.chat.id, f"✅ Переименован!\n'{old_name}' → '{new_name}'")
    bot.send_message(message.chat.id, "Выбери действие:", reply_markup=main_menu())

def confirm_delete(message, tool_name):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ ДА, удалить", callback_data=f"confirm_delete_{tool_name}"))
    markup.add(InlineKeyboardButton("❌ НЕТ, отмена", callback_data="back_to_menu"))
    bot.send_message(message.chat.id, f"⚠️ Удалить '{tool_name}'?\nЭто НЕЛЬЗЯ отменить!", reply_markup=markup)

def delete_tool(message, tool_name):
    if tool_name not in tools:
        bot.send_message(message.chat.id, f"❌ Инструмент '{tool_name}' не найден!")
    else:
        del tools[tool_name]
        save_data()
        bot.send_message(message.chat.id, f"🗑️ Инструмент '{tool_name}' УДАЛЁН!")
    bot.send_message(message.chat.id, "Выбери действие:", reply_markup=main_menu())

def complete_transfer(message, tool_name):
    new_owner = message.text.strip()
    if not new_owner:
        bot.send_message(message.chat.id, "❌ Имя не может быть пустым!")
        bot.send_message(message.chat.id, "Выбери действие:", reply_markup=main_menu())
        return
    if tool_name not in tools:
        bot.send_message(message.chat.id, f"❌ Инструмент '{tool_name}' не найден!")
        bot.send_message(message.chat.id, "Выбери действие:", reply_markup=main_menu())
        return
    
    old_owner = tools[tool_name]["current_owner"]
    tools[tool_name]["current_owner"] = new_owner
    tools[tool_name]["history"].append(f"🔄 Передан от '{old_owner}' к '{new_owner}'")
    save_data()
    bot.send_message(message.chat.id, f"✅ '{tool_name}' передан {new_owner}")
    bot.send_message(message.chat.id, "Выбери действие:", reply_markup=main_menu())

def who_has_tool(message, tool_name):
    if tool_name not in tools:
        bot.send_message(message.chat.id, f"❌ Инструмент '{tool_name}' не найден!")
    else:
        owner = tools[tool_name]["current_owner"]
        bot.send_message(message.chat.id, f"🔧 '{tool_name}' у: **{owner}**", parse_mode="Markdown")
    bot.send_message(message.chat.id, "Выбери действие:", reply_markup=main_menu())

def show_all_tools(message):
    if not tools:
        bot.send_message(message.chat.id, "📭 Склад пуст")
    else:
        text = "📋 **Все инструменты:**\n\n"
        for name, data in tools.items():
            owner = "📦 на складе" if data['current_owner'] == "на складе" else f"👤 {data['current_owner']}"
            text += f"🔧 {name}\n   📍 {owner}\n\n"
        bot.send_message(message.chat.id, text, parse_mode="Markdown")
    bot.send_message(message.chat.id, "Выбери действие:", reply_markup=main_menu())

def show_history(message, tool_name):
    if tool_name not in tools:
        bot.send_message(message.chat.id, f"❌ Инструмент '{tool_name}' не найден!")
    else:
        history = tools[tool_name]["history"]
        if not history:
            bot.send_message(message.chat.id, f"📜 У '{tool_name}' нет истории")
        else:
            text = f"📜 **История '{tool_name}':**\n\n"
            for i, event in enumerate(history[-10:], 1):
                text += f"{i}. {event}\n"
            bot.send_message(message.chat.id, text, parse_mode="Markdown")
    bot.send_message(message.chat.id, "Выбери действие:", reply_markup=main_menu())

def show_statistics(message):
    if not tools:
        bot.send_message(message.chat.id, "📭 Нет данных")
    else:
        total = len(tools)
        on_warehouse = sum(1 for t in tools.values() if t['current_owner'] == "на складе")
        with_workers = total - on_warehouse
        transfers = sum(len([h for h in t['history'] if h.startswith('🔄')]) for t in tools.values())
        text = f"📊 **Статистика:**\n\n🔧 Всего: {total}\n📦 На складе: {on_warehouse}\n👤 У работников: {with_workers}\n🔄 Передач: {transfers}"
        bot.send_message(message.chat.id, text, parse_mode="Markdown")
    bot.send_message(message.chat.id, "Выбери действие:", reply_markup=main_menu())

# ========== FLASK ВЕБ-СЕРВЕР ДЛЯ RAILWAY ==========
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Бот для учёта инструментов работает!"

def run_bot():
    print("🚀 Бот запущен и готов к работе!")
    bot.infinity_polling()

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    # Запускаем бота в отдельном потоке
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()
    
    # Запускаем Flask сервер для Railway
    port = int(os.environ.get("PORT", 5000))
    print(f"🌐 Веб-сервер запущен на порту {port}")
    app.run(host='0.0.0.0', port=port)