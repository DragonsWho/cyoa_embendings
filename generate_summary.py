# generate_summary.py
import sqlite3
import os
import argparse
import concurrent.futures
from dotenv import load_dotenv
from openai import OpenAI
from tqdm import tqdm

# --- Конфигурация ---
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
if not OPENROUTER_API_KEY:
    raise ValueError("Не найден OPENROUTER_API_KEY в .env файле")

GENERATION_MODEL_NAME = "deepseek/deepseek-v3.2-exp"

DB_FILE = "games.db"
PROMPT_FILE = "summary_prompt.txt"

def load_prompt():
    """Загружает системный промпт из файла."""
    if not os.path.exists(PROMPT_FILE):
        raise FileNotFoundError(f"Не найден файл промпта: {PROMPT_FILE}")
    with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
        return f.read().strip()

# <--- ИЗМЕНЕНИЕ: Добавили 'game_title' для логирования ошибок --->
def generate_summary_with_openrouter(client, model_name, base_prompt, game_title, game_text):
    """Отправляет текст игры в OpenRouter и получает описание."""
    try:
        # <--- ИЗМЕНЕНИЕ: Уменьшаем лимит символов, чтобы вписаться в лимит токенов модели --->
        # Лимит модели ~163k токенов. 500k символов это ~125k токенов, что безопасно.
        max_chars = 500000
        
        if len(game_text) > max_chars:
             # Логируем, что текст был обрезан
             tqdm.write(f"  [INFO] Текст для '{game_title}' слишком длинный ({len(game_text)} симв.), обрезается до {max_chars}.")
        
        truncated_text = game_text[:max_chars]
        
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
            temperature=0.2,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        # Возвращаем ошибку, чтобы ее можно было обработать в главном потоке
        return f"API_ERROR: {e}"

def process_game(game_data, client, model_name, base_prompt):
    """
    Функция-обработчик для одной игры. Вызывается в отдельном потоке.
    """
    pb_id, title, full_text = game_data
    # <--- ИЗМЕНЕНИЕ: Передаем 'title' в функцию генерации --->
    summary = generate_summary_with_openrouter(client, model_name, base_prompt, title, full_text)
    return pb_id, title, summary

def run_summary_generation(limit=None, workers=5):
    """
    Основная логика генерации описаний. Может быть вызвана из других скриптов.
    """
    base_prompt = load_prompt()
    client = OpenAI(
      base_url="https://openrouter.ai/api/v1",
      api_key=OPENROUTER_API_KEY,
    )

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    query = """
        SELECT pocketbase_id, title, full_text 
        FROM games 
        WHERE full_text IS NOT NULL AND full_text != '' AND (summary IS NULL OR summary = '')
    """
    
    params = ()
    if limit:
        query += " LIMIT ?"
        params = (limit,)
        print(f"--- Режим ограничения: обработка не более {limit} игр ---")

    cursor.execute(query, params)
    games_to_process = cursor.fetchall()

    if not games_to_process:
        print("Нет игр, требующих генерации описания.")
        conn.close()
        return

    print(f"Найдено {len(games_to_process)} игр для генерации описаний с помощью {GENERATION_MODEL_NAME} через OpenRouter.")
    print(f"Запускаем обработку в {workers} параллельных потоков...")
    
    success_count = 0
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_game = {
            executor.submit(process_game, game, client, GENERATION_MODEL_NAME, base_prompt): game
            for game in games_to_process
        }
        
        progress_bar = tqdm(concurrent.futures.as_completed(future_to_game), total=len(games_to_process), desc="Генерация описаний")
        
        for future in progress_bar:
            pb_id, title, summary = future.result()
            
            if summary and not summary.startswith("API_ERROR:"):
                cursor.execute(
                    "UPDATE games SET summary = ?, last_indexed_at = NULL WHERE pocketbase_id = ?",
                    (summary, pb_id)
                )
                conn.commit()
                success_count += 1
            else:
                tqdm.write(f"\n[FAIL] Не удалось сгенерировать описание для '{title}'. Ошибка: {summary}")

    conn.close()
    print(f"\nЗавершено. Успешно сгенерировано описаний: {success_count}/{len(games_to_process)}.")
    if success_count > 0:
        print("Теперь запустите 'python indexer.py', чтобы добавить новые описания в поисковый индекс.")

def main():
    """
    Точка входа при запуске скрипта напрямую. Парсит аргументы командной строки.
    """
    parser = argparse.ArgumentParser(description="Генератор описаний игр с помощью OpenRouter.")
    parser.add_argument('--limit', type=int, default=None, help="Количество игр для обработки за один запуск.")
    parser.add_argument('--workers', type=int, default=5, help="Количество параллельных потоков для запросов к API.")
    args = parser.parse_args()
    run_summary_generation(limit=args.limit, workers=args.workers)

if __name__ == "__main__":
    main()