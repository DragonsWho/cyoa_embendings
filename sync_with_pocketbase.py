# sync_with_pocketbase.py (обновленная версия)
import os
import sqlite3
import json
from dotenv import load_dotenv
# ИСПОЛЬЗУЕМ СТАРЫЙ, ПРОВЕРЕННЫЙ ИМПОРТ
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
        # ИСПОЛЬЗУЕМ СТАРЫЙ, РАБОЧИЙ СПОСОБ АУТЕНТИФИКАЦИИ
        client = PocketBase(POCKETBASE_URL)
        client.auth_with_password(ADMIN_EMAIL, ADMIN_PASSWORD)
        print("Успешная аутентификация в PocketBase.")
    except Exception as e:
        print(f"Ошибка аутентификации в PocketBase: {e}")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        all_pb_games = client.collection("games").get_full_list(batch=200, query_params={"sort": "-created"})
        print(f"Из PocketBase получено {len(all_pb_games)} игр.")
    except Exception as e:
        print(f"Ошибка при получении списка игр из PocketBase: {e}")
        conn.close()
        return

    added_count = 0
    updated_count = 0
    for game in all_pb_games:
        try:
            # Сначала добавляем только базовые поля для всех игр
            cursor.execute(
                "INSERT OR IGNORE INTO games (pocketbase_id, title) VALUES (?, ?)",
                (game.id, game.title)
            )
            if cursor.rowcount > 0:
                added_count += 1

            # НОВАЯ ЛОГИКА: Определяем тип и заполняем нужные поля
            # Тип 1: Интерактивная CYOA (ссылка)
            if game.img_or_link == 'link' and game.iframe_url:
                cursor.execute(
                    "UPDATE games SET original_url = ? WHERE pocketbase_id = ?",
                    (game.iframe_url, game.id)
                )
                if cursor.rowcount > 0: updated_count += 1
            
            # Тип 2: Статичная CYOA (картинки)
            elif game.img_or_link == 'img' and game.cyoa_pages:
                image_urls = []
                # Собираем полные URL для каждого файла, сохраняя порядок
                for filename in game.cyoa_pages:
                    url = f"{POCKETBASE_URL}/api/files/{game.collection_id}/{game.id}/{filename}"
                    image_urls.append(url)
                
                # Конвертируем список в JSON-строку и сохраняем
                image_urls_json = json.dumps(image_urls)
                cursor.execute(
                    "UPDATE games SET image_urls = ? WHERE pocketbase_id = ?",
                    (image_urls_json, game.id)
                )
                if cursor.rowcount > 0: updated_count += 1

        except Exception as e:
            print(f"Не удалось обработать игру {game.id} ({game.title}): {e}")

    conn.commit()
    conn.close()
    
    print("-" * 20)
    print("Синхронизация завершена.")
    print(f"Добавлено {added_count} новых игр.")
    print(f"Обновлено {updated_count} записей с URL-ами.")
    print("Теперь можно запускать скрипты обработки!")

if __name__ == "__main__":
    sync_games()