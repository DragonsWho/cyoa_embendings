# process_static_cyoa.py
import os
import sqlite3
import json
import requests # Для скачивания изображений
from datetime import datetime
from dotenv import load_dotenv
from google.cloud import vision

# --- Конфигурация ---
load_dotenv()
DB_FILE = "games.db"

def recognize_text_from_content(image_content: bytes):
    """
    Отправляет бинарное содержимое изображения в Google Cloud Vision API
    и возвращает распознанный текст.
    """
    try:
        client = vision.ImageAnnotatorClient()
        image = vision.Image(content=image_content)
        
        response = client.document_text_detection(image=image)

        if response.error.message:
            raise Exception(f"Ошибка API: {response.error.message}")

        return response.full_text_annotation.text if response.full_text_annotation else ""
    
    except Exception as e:
        print(f"  [!] Ошибка при распознавании: {e}")
        return None


def process_static_games():
    """
    Находит необработанные статичные CYOA в базе, распознает текст 
    с их изображений и сохраняет результат.
    """
    print("Начинаем обработку статичных CYOA...")
    conn = sqlite3.connect(DB_FILE)
    # Удобно получать результаты в виде словарей
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Выбираем игры, которые еще не проиндексированы и являются статичными (имеют image_urls)
    cursor.execute("""
        SELECT pocketbase_id, title, image_urls FROM games
        WHERE is_indexed = 0 AND image_urls IS NOT NULL AND image_urls != '[]'
    """)
    games_to_process = cursor.fetchall()

    if not games_to_process:
        print("Не найдено новых статичных CYOA для обработки.")
        conn.close()
        return

    print(f"Найдено {len(games_to_process)} статичных CYOA для обработки.")

    for game in games_to_process:
        print(f"\n--- Обрабатываем: '{game['title']}' (ID: {game['pocketbase_id']}) ---")
        
        # Загружаем список URL из JSON-строки
        image_urls = json.loads(game['image_urls'])
        all_pages_text = []

        for i, url in enumerate(image_urls, 1):
            print(f"  > Скачиваем и распознаем страницу {i}/{len(image_urls)}...")
            
            try:
                # Скачиваем изображение в память
                response = requests.get(url, timeout=30)
                response.raise_for_status() # Проверяем, что запрос успешен (код 2xx)
                image_bytes = response.content

                # Распознаем текст
                recognized_text = recognize_text_from_content(image_bytes)
                if recognized_text:
                    all_pages_text.append(recognized_text)

            except requests.exceptions.RequestException as e:
                print(f"  [!] Не удалось скачать изображение по URL: {url}. Ошибка: {e}")
                continue # Переходим к следующему изображению
        
        if all_pages_text:
            # Соединяем текст со всех страниц в один большой текстовый блок
            full_text = "\n\n--- PAGE BREAK ---\n\n".join(all_pages_text)
            
            # Обновляем запись в базе данных
            current_time_iso = datetime.now().isoformat()
            cursor.execute("""
                UPDATE games
                SET full_text = ?, is_indexed = 1, last_indexed_at = ?
                WHERE pocketbase_id = ?
            """, (full_text, current_time_iso, game['pocketbase_id']))
            conn.commit()
            print(f"  [OK] Текст успешно распознан и сохранен для '{game['title']}'.")
        else:
            print(f"  [!] Не удалось распознать текст ни на одной из страниц для '{game['title']}'.")

    conn.close()
    print("\nОбработка статичных CYOA завершена.")


if __name__ == "__main__":
    process_static_games()