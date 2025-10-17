# sync_with_pocketbase.py (обновленная версия)
import os
import sqlite3
from dotenv import load_dotenv
from pocketbase import PocketBase

# --- Конфигурация ---
load_dotenv()
DB_FILE = "games.db"
POCKETBASE_URL = "https://cyoa.cafe"
ADMIN_EMAIL = os.getenv('EMAIL')
ADMIN_PASSWORD = os.getenv('PASSWORD')

def sync_games():
    """Синхронизирует игры из PocketBase с локальной базой данных SQLite."""
    print("Начинаем синхронизацию с PocketBase...")

    try:
        client = PocketBase(POCKETBASE_URL)
        admin_data = client.admins.auth_with_password(ADMIN_EMAIL, ADMIN_PASSWORD)
        print("Успешная аутентификация в PocketBase.")
    except Exception as e:
        print(f"Ошибка аутентификации в PocketBase: {e}")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        all_pb_games = client.collection("games").get_full_list(batch=200)
        print(f"Из PocketBase получено {len(all_pb_games)} игр.")
    except Exception as e:
        print(f"Ошибка при получении списка игр из PocketBase: {e}")
        conn.close()
        return

    added_count = 0
    for game in all_pb_games:
        try:
            # ИЗМЕНЕНИЕ: Теперь мы вставляем и original_url, который берем из поля iframe_url
            cursor.execute(
                "INSERT OR IGNORE INTO games (pocketbase_id, title, original_url) VALUES (?, ?, ?)",
                (game.id, game.title, game.iframe_url)
            )
            if cursor.rowcount > 0:
                added_count += 1
        except Exception as e:
            print(f"Не удалось обработать игру {game.id} ({game.title}): {e}")

    conn.commit()
    conn.close()
    
    print("-" * 20)
    print("Синхронизация завершена.")
    if added_count > 0:
        print(f"Добавлено {added_count} новых игр в локальную базу с URL-оригиналами.")
        print("Теперь можно запустить fetch_game_text.py!")
    else:
        print("Новых игр не найдено.")

if __name__ == "__main__":
    sync_games()