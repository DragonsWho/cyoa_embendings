# migrate_database.py
import sqlite3

DB_FILE = "games.db"

def migrate():
    """Добавляет колонку 'is_indexed' в таблицу 'games'."""
    print(f"Применяем миграцию к базе данных '{DB_FILE}'...")
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Проверяем, существует ли уже колонка, чтобы избежать ошибок при повторном запуске
        cursor.execute("PRAGMA table_info(games)")
        columns = [info[1] for info in cursor.fetchall()]
        
        if 'is_indexed' in columns:
            print("Колонка 'is_indexed' уже существует. Миграция не требуется.")
        else:
            # Добавляем колонку is_indexed
            # BOOLEAN, DEFAULT 0 - логический тип, по умолчанию 'false' (не проиндексировано)
            cursor.execute("ALTER TABLE games ADD COLUMN is_indexed BOOLEAN DEFAULT 0")
            print("Колонка 'is_indexed' успешно добавлена.")

        # Сбрасываем флаг для всех существующих игр, чтобы они переиндексировались в первый раз
        cursor.execute("UPDATE games SET is_indexed = 0")
        print("Все существующие игры помечены как 'непроиндексированные' для полной переиндексации.")
        
        conn.commit()
        conn.close()
        print("Миграция успешно завершена.")

    except Exception as e:
        print(f"Произошла ошибка при миграции: {e}")

if __name__ == "__main__":
    migrate()