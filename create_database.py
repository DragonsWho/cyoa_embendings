# create_database.py
import sqlite3
import os

DB_FILE = "games.db"

def create_database():
    """Создает файл базы данных и таблицу 'games' с новой схемой."""
    if os.path.exists(DB_FILE):
        print(f"Файл базы данных '{DB_FILE}' уже существует.")
        print("Если вы хотите пересоздать схему, удалите файл вручную.")
        return

    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        cursor.execute('''
        CREATE TABLE games (
            pocketbase_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            original_url TEXT, -- Для интерактивных CYOA (iframe_url)
            image_urls TEXT,   -- НОВОЕ ПОЛЕ: для JSON-списка URL-ов статичных CYOA
            full_text TEXT,
            summary TEXT,
            source_hash TEXT,
            last_indexed_at TIMESTAMP,
            is_indexed BOOLEAN DEFAULT 0
        )
        ''')

        conn.commit()
        conn.close()
        print(f"База данных '{DB_FILE}' успешно создана с колонкой 'image_urls'.")

    except Exception as e:
        print(f"Произошла ошибка при создании базы данных: {e}")

if __name__ == "__main__":
    # Перед первым запуском новых скриптов, удалите старый games.db
    # и выполните этот файл, чтобы создать базу с новой структурой.
    create_database()