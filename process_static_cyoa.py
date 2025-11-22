# process_static_cyoa.py
import logging
# Устанавливаем уровень логирования для библиотек Google повыше, чтобы не шумели
logging.getLogger('google.api_core').setLevel(logging.WARNING)
logging.getLogger('google.auth').setLevel(logging.WARNING)
logging.getLogger('google.cloud').setLevel(logging.WARNING)

import sqlite3
import json
import requests
from datetime import datetime
from google.cloud import vision
import config  # <--- Используем центральный конфиг

def recognize_text_from_content(image_content: bytes):
    try:
        client = vision.ImageAnnotatorClient()
        image = vision.Image(content=image_content)
        response = client.document_text_detection(image=image)
        if response.error.message:
            raise Exception(f"Ошибка API: {response.error.message}")
        return response.full_text_annotation.text if response.full_text_annotation else ""
    except Exception as e:
        print(f"  [!] Ошибка Google Vision: {e}")
        return None

def process_static_games():
    """Находит необработанные статичные CYOA (image_urls) и распознает текст."""
    print("--- Обработка статичных CYOA (OCR) ---")
    
    # Проверка наличия ключа GCP
    if not os.path.exists("gcp-credentials.json") and not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
        print("[SKIP] Файл gcp-credentials.json не найден. Пропуск распознавания изображений.")
        return

    conn = sqlite3.connect(config.DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Ищем игры, у которых есть картинки, но нет статуса индексации
    cursor.execute("""
        SELECT pocketbase_id, title, image_urls FROM games
        WHERE (full_text IS NULL OR full_text = '') 
        AND image_urls IS NOT NULL 
        AND image_urls != '[]'
    """)
    games_to_process = cursor.fetchall()

    if not games_to_process:
        print("Нет новых статичных игр для распознавания.")
        conn.close()
        return

    print(f"Найдено {len(games_to_process)} игр для OCR.")

    for game in games_to_process:
        print(f"\nProcessing: '{game['title']}'")
        image_urls = json.loads(game['image_urls'])
        all_pages_text = []

        for i, url in enumerate(image_urls, 1):
            print(f"  > Стр. {i}/{len(image_urls)}...", end=" ", flush=True)
            try:
                resp = requests.get(url, timeout=30)
                if resp.status_code == 200:
                    text = recognize_text_from_content(resp.content)
                    if text:
                        all_pages_text.append(text)
                        print("[OK]")
                    else:
                        print("[Пусто]")
                else:
                    print(f"[Ошибка скачивания {resp.status_code}]")
            except Exception as e:
                print(f"[Error: {e}]")
        
        if all_pages_text:
            full_text = "\n\n--- PAGE BREAK ---\n\n".join(all_pages_text)
            # Сохраняем текст, но статус last_indexed_at пока не ставим (это сделает indexer.py)
            cursor.execute("UPDATE games SET full_text = ? WHERE pocketbase_id = ?", (full_text, game['pocketbase_id']))
            conn.commit()
            print(f"  -> Текст сохранен.")
        else:
            print(f"  -> Текст не удалось извлечь.")

    conn.close()