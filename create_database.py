# create_database.py (обновленная версия)
import sqlite3
import os

DB_FILE = "games.db"

def create_database():
    """Создает файл базы данных и таблицу 'games' с новой схемой."""
    if os.path.exists(DB_FILE):
        print(f"Файл базы данных '{DB_FILE}' уже существует.")
        # Для чистоты эксперимента, лучше удалить старый файл перед запуском
        # os.remove(DB_FILE)
        # print(f"Старый файл '{DB_FILE}' удален.")
        return

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # ИЗМЕНЕНИЕ: Добавили поле original_url
        cursor.execute('''
        CREATE TABLE games (
            pocketbase_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            original_url TEXT, 
            full_text TEXT,
            source_hash TEXT,
            last_indexed_at TIMESTAMP
        )
        ''')

        conn.commit()
        conn.close()
        print(f"База данных '{DB_FILE}' и таблица 'games' успешно созданы с полем 'original_url'.")

    except Exception as e:
        print(f"Произошла ошибка при создании базы данных: {e}")

if __name__ == "__main__":
    create_database()