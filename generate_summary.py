# generate_summary.py
import sqlite3
import os
import time
import argparse
from dotenv import load_dotenv
from openai import OpenAI # <--- ИЗМЕНЕНИЕ: Используем библиотеку OpenAI
from tqdm import tqdm

# --- Конфигурация ---
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY") # <--- ИЗМЕНЕНИЕ: Ищем ключ OpenRouter
if not OPENROUTER_API_KEY:
    raise ValueError("Не найден OPENROUTER_API_KEY в .env файле")

# --- ИЗМЕНЕНИЕ: Укажите модель в формате OpenRouter ---
# Вы можете выбрать любую подходящую модель из каталога OpenRouter
# Например: 'google/gemini-1.5-pro-latest', 'google/gemini-flash-1.5', 
# 'mistralai/mistral-large', 'anthropic/claude-3-haiku'
GENERATION_MODEL_NAME = "deepseek/deepseek-v3.2-exp" 

DB_FILE = "games.db"
PROMPT_FILE = "summary_prompt.txt"

def load_prompt():
    """Загружает системный промпт из файла."""
    if not os.path.exists(PROMPT_FILE):
        raise FileNotFoundError(f"Не найден файл промпта: {PROMPT_FILE}")
    with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
        return f.read().strip()

def generate_summary_with_openrouter(client, model_name, base_prompt, game_text):
    """Отправляет текст игры в OpenRouter и получает описание."""
    try:
        # Обрежем совсем гигантские тексты для экономии и стабильности
        # Разные модели имеют разные лимиты, но 1М символов - разумный предел
        max_chars = 1000000 
        truncated_text = game_text[:max_chars]
        
        # --- ИЗМЕНЕНИЕ: Формируем запрос в формате OpenAI Chat Completions ---
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": base_prompt
                },
                {
                    "role": "user",
                    "content": f"Input Game Text:\n{truncated_text}"
                }
            ],
            temperature=0.2, # Низкая температура для более фактологичного описания
        )
        # --- ИЗМЕНЕНИЕ: Извлекаем ответ из структуры OpenAI ---
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"\nОшибка API OpenRouter при генерации описания: {e}")
        return None

def main():
    parser = argparse.ArgumentParser(description="Генератор описаний игр с помощью OpenRouter.")
    parser.add_argument('--limit', type=int, default=None, help="Количество игр для обработки за один запуск.")
    args = parser.parse_args()

    base_prompt = load_prompt()

    # --- ИЗМЕНЕНИЕ: Инициализация клиента для OpenRouter ---
    client = OpenAI(
      base_url="https://openrouter.ai/api/v1",
      api_key=OPENROUTER_API_KEY,
    )

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Запрос к БД остался без изменений
    query = """
        SELECT pocketbase_id, title, full_text 
        FROM games 
        WHERE full_text IS NOT NULL AND full_text != '' AND (summary IS NULL OR summary = '')
    """
    
    params = ()
    if args.limit:
        query += " LIMIT ?"
        params = (args.limit,)
        print(f"--- Тестовый режим: обработка не более {args.limit} игр ---")

    cursor.execute(query, params)
    games_to_process = cursor.fetchall()

    if not games_to_process:
        print("Нет игр, требующих генерации описания.")
        conn.close()
        return

    print(f"Найдено {len(games_to_process)} игр для генерации описаний с помощью {GENERATION_MODEL_NAME} через OpenRouter.")
    
    success_count = 0
    
    for pb_id, title, full_text in tqdm(games_to_process, desc="Генерация описаний"):
        tqdm.write(f"Обработка: {title}...")
        
        # --- ИЗМЕНЕНИЕ: Вызываем новую функцию ---
        summary = generate_summary_with_openrouter(client, GENERATION_MODEL_NAME, base_prompt, full_text)
        
        if summary:
            # Логика сохранения в БД осталась без изменений
            cursor.execute(
                "UPDATE games SET summary = ?, last_indexed_at = NULL WHERE pocketbase_id = ?",
                (summary, pb_id)
            )
            conn.commit()
            success_count += 1
            # Пауза, чтобы не попасть под rate limit. 
            # Для бесплатных аккаунтов OpenRouter это может быть актуально.
            time.sleep(2) 
        else:
            tqdm.write(f"  [FAIL] Не удалось сгенерировать описание для '{title}'")

    conn.close()
    print(f"\nЗавершено. Успешно сгенерировано описаний: {success_count}/{len(games_to_process)}.")
    if success_count > 0:
        print("Теперь запустите 'python indexer.py', чтобы добавить новые описания в поисковый индекс.")

if __name__ == "__main__":
    main()