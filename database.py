"""
Модуль работы с PostgreSQL.
Все функции для пользователей, категорий, инструментов и истории.
"""
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from datetime import datetime


DATABASE_URL = os.environ.get("DATABASE_URL")


@contextmanager
def get_connection():
    """Контекстный менеджер для соединения с БД."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_cursor():
    """Контекстный менеджер для курсора с авто-коммитом."""
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            yield cur
        finally:
            cur.close()


def init_db():
    """Инициализация БД — создаёт таблицы если их нет."""
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    with get_cursor() as cur:
        cur.execute(schema_sql)
    print("✅ База данных инициализирована")


# ========== ПОЛЬЗОВАТЕЛИ ==========

def add_user(telegram_id: int, full_name: str, role: str = "user") -> dict:
    """Добавить пользователя. Если уже существует — обновляет имя и снимает флаг is_deleted."""
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO users (telegram_id, full_name, role)
            VALUES (%s, %s, %s)
            ON CONFLICT (telegram_id) DO UPDATE
                SET full_name = EXCLUDED.full_name,
                    is_deleted = FALSE
            RETURNING *
        """, (telegram_id, full_name, role))
        return dict(cur.fetchone())


def get_user_by_telegram_id(telegram_id: int) -> dict | None:
    """Получить пользователя по telegram_id (только активного)."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM users WHERE telegram_id = %s AND is_deleted = FALSE",
            (telegram_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    """Получить пользователя по внутреннему id (включая удалённых — для истории)."""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_all_users(include_deleted: bool = False) -> list:
    """Получить список всех пользователей."""
    with get_cursor() as cur:
        if include_deleted:
            cur.execute("SELECT * FROM users ORDER BY full_name")
        else:
            cur.execute("SELECT * FROM users WHERE is_deleted = FALSE ORDER BY full_name")
        return [dict(r) for r in cur.fetchall()]


def update_user(user_id: int, full_name: str = None, role: str = None) -> bool:
    """Обновить имя и/или роль пользователя."""
    fields = []
    values = []
    if full_name is not None:
        fields.append("full_name = %s")
        values.append(full_name)
    if role is not None:
        fields.append("role = %s")
        values.append(role)
    if not fields:
        return False
    values.append(user_id)
    with get_cursor() as cur:
        cur.execute(
            f"UPDATE users SET {', '.join(fields)} WHERE id = %s",
            values
        )
        return cur.rowcount > 0


def soft_delete_user(user_id: int) -> bool:
    """Мягкое удаление — ставит флаг is_deleted, история сохраняется."""
    with get_cursor() as cur:
        cur.execute(
            "UPDATE users SET is_deleted = TRUE WHERE id = %s",
            (user_id,)
        )
        return cur.rowcount > 0


def is_admin(telegram_id: int) -> bool:
    """Проверка что пользователь — админ."""
    user = get_user_by_telegram_id(telegram_id)
    return user is not None and user["role"] == "admin"


def is_registered(telegram_id: int) -> bool:
    """Проверка что пользователь зарегистрирован в системе."""
    return get_user_by_telegram_id(telegram_id) is not None


# ========== КАТЕГОРИИ ==========

def add_category(name: str) -> dict | None:
    """Добавить категорию. Возвращает None если уже существует."""
    with get_cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO categories (name) VALUES (%s) RETURNING *",
                (name,)
            )
            return dict(cur.fetchone())
        except psycopg2.IntegrityError:
            return None


def get_category_by_id(category_id: int) -> dict | None:
    with get_cursor() as cur:
        cur.execute("SELECT * FROM categories WHERE id = %s", (category_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_all_categories() -> list:
    """Список категорий с количеством активных инструментов в каждой."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT c.*, COUNT(t.id) FILTER (WHERE t.status = 'active') AS tools_count
            FROM categories c
            LEFT JOIN tools t ON t.category_id = c.id
            GROUP BY c.id
            ORDER BY c.name
        """)
        return [dict(r) for r in cur.fetchall()]


def rename_category(category_id: int, new_name: str) -> bool:
    with get_cursor() as cur:
        cur.execute(
            "UPDATE categories SET name = %s WHERE id = %s",
            (new_name, category_id)
        )
        return cur.rowcount > 0


def delete_category(category_id: int) -> bool:
    """Удалить категорию. Инструменты остаются, но без категории."""
    with get_cursor() as cur:
        cur.execute("DELETE FROM categories WHERE id = %s", (category_id,))
        return cur.rowcount > 0


# ========== ИНСТРУМЕНТЫ ==========

def add_tool(name: str, category_id: int, owner_id: int) -> dict:
    """Добавить инструмент с категорией и начальным владельцем."""
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO tools (name, category_id, current_owner_id)
            VALUES (%s, %s, %s)
            RETURNING *
        """, (name, category_id, owner_id))
        tool = dict(cur.fetchone())
        # запись в историю
        cur.execute("""
            INSERT INTO transfers (tool_id, to_user_id, event_type, status, note)
            VALUES (%s, %s, 'created', 'confirmed', %s)
        """, (tool["id"], owner_id, "Инструмент добавлен на склад"))
        return tool


def get_tool_by_id(tool_id: int) -> dict | None:
    with get_cursor() as cur:
        cur.execute("""
            SELECT t.*, c.name AS category_name, u.full_name AS owner_name, u.telegram_id AS owner_telegram_id
            FROM tools t
            LEFT JOIN categories c ON c.id = t.category_id
            LEFT JOIN users u ON u.id = t.current_owner_id
            WHERE t.id = %s
        """, (tool_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_tools_by_category(category_id: int, only_active: bool = True) -> list:
    """Все инструменты в категории."""
    with get_cursor() as cur:
        query = """
            SELECT t.*, u.full_name AS owner_name
            FROM tools t
            LEFT JOIN users u ON u.id = t.current_owner_id
            WHERE t.category_id = %s
        """
        if only_active:
            query += " AND t.status = 'active'"
        query += " ORDER BY t.name"
        cur.execute(query, (category_id,))
        return [dict(r) for r in cur.fetchall()]


def get_all_tools(only_active: bool = True) -> list:
    with get_cursor() as cur:
        query = """
            SELECT t.*, c.name AS category_name, u.full_name AS owner_name
            FROM tools t
            LEFT JOIN categories c ON c.id = t.category_id
            LEFT JOIN users u ON u.id = t.current_owner_id
        """
        if only_active:
            query += " WHERE t.status = 'active'"
        query += " ORDER BY c.name, t.name"
        cur.execute(query)
        return [dict(r) for r in cur.fetchall()]


def rename_tool(tool_id: int, new_name: str) -> bool:
    with get_cursor() as cur:
        cur.execute("SELECT name FROM tools WHERE id = %s", (tool_id,))
        old = cur.fetchone()
        if not old:
            return False
        old_name = old["name"]
        cur.execute(
            "UPDATE tools SET name = %s WHERE id = %s",
            (new_name, tool_id)
        )
        cur.execute("""
            INSERT INTO transfers (tool_id, event_type, status, note)
            VALUES (%s, 'renamed', 'confirmed', %s)
        """, (tool_id, f"Переименован из '{old_name}' в '{new_name}'"))
        return True


def write_off_tool(tool_id: int, reason: str) -> bool:
    """Списать инструмент с указанием причины."""
    with get_cursor() as cur:
        cur.execute("""
            UPDATE tools
            SET status = 'written_off',
                write_off_reason = %s,
                written_off_at = CURRENT_TIMESTAMP
            WHERE id = %s AND status = 'active'
        """, (reason, tool_id))
        if cur.rowcount == 0:
            return False
        cur.execute("""
            INSERT INTO transfers (tool_id, event_type, status, note)
            VALUES (%s, 'written_off', 'confirmed', %s)
        """, (tool_id, f"Списан. Причина: {reason}"))
        return True


# ========== ПЕРЕДАЧИ ==========

def create_transfer_request(tool_id: int, from_user_id: int, to_user_id: int) -> dict:
    """Создать запрос на передачу — статус pending, ждёт подтверждения получателя."""
    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO transfers (tool_id, from_user_id, to_user_id, event_type, status)
            VALUES (%s, %s, %s, 'transfer', 'pending')
            RETURNING *
        """, (tool_id, from_user_id, to_user_id))
        return dict(cur.fetchone())


def get_transfer_by_id(transfer_id: int) -> dict | None:
    with get_cursor() as cur:
        cur.execute("""
            SELECT t.*,
                   tl.name AS tool_name,
                   uf.full_name AS from_name, uf.telegram_id AS from_telegram_id,
                   ut.full_name AS to_name, ut.telegram_id AS to_telegram_id
            FROM transfers t
            LEFT JOIN tools tl ON tl.id = t.tool_id
            LEFT JOIN users uf ON uf.id = t.from_user_id
            LEFT JOIN users ut ON ut.id = t.to_user_id
            WHERE t.id = %s
        """, (transfer_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def confirm_transfer(transfer_id: int) -> bool:
    """Получатель подтвердил передачу — меняем владельца инструмента."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT tool_id, to_user_id, status
            FROM transfers WHERE id = %s
        """, (transfer_id,))
        tr = cur.fetchone()
        if not tr or tr["status"] != "pending":
            return False
        cur.execute("""
            UPDATE transfers
            SET status = 'confirmed', confirmed_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (transfer_id,))
        cur.execute("""
            UPDATE tools SET current_owner_id = %s WHERE id = %s
        """, (tr["to_user_id"], tr["tool_id"]))
        return True


def reject_transfer(transfer_id: int) -> bool:
    """Получатель отказал — статус rejected, владелец не меняется."""
    with get_cursor() as cur:
        cur.execute("""
            UPDATE transfers
            SET status = 'rejected', confirmed_at = CURRENT_TIMESTAMP
            WHERE id = %s AND status = 'pending'
        """, (transfer_id,))
        return cur.rowcount > 0


def get_tool_history(tool_id: int, limit: int = 10) -> list:
    """Последние N событий по инструменту."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT t.*,
                   uf.full_name AS from_name,
                   ut.full_name AS to_name
            FROM transfers t
            LEFT JOIN users uf ON uf.id = t.from_user_id
            LEFT JOIN users ut ON ut.id = t.to_user_id
            WHERE t.tool_id = %s
            ORDER BY t.created_at DESC
            LIMIT %s
        """, (tool_id, limit))
        return [dict(r) for r in cur.fetchall()]


# ========== СТАТИСТИКА ==========

def get_statistics() -> dict:
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total FROM tools WHERE status = 'active'")
        total = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS cnt FROM tools WHERE status = 'written_off'")
        written_off = cur.fetchone()["cnt"]

        cur.execute("""
            SELECT COUNT(*) AS cnt FROM transfers
            WHERE event_type = 'transfer' AND status = 'confirmed'
        """)
        transfers = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) AS cnt FROM users WHERE is_deleted = FALSE")
        users = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) AS cnt FROM categories")
        categories = cur.fetchone()["cnt"]

        return {
            "total_tools": total,
            "written_off": written_off,
            "transfers": transfers,
            "users": users,
            "categories": categories,
        }
