# indexer.py (версия с тестовым режимом)
import json
import os
import numpy as np
import faiss
import google.generativeai as genai
import sqlite3
import time
from dotenv import load_dotenv
from tqdm import tqdm
import math
from datetime import datetime
import argparse # <-- 1. Импортируем argparse

# --- Конфигурация ---
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    raise ValueError("Не найден GOOGLE_API_KEY в .env файле")

genai.configure(api_key=GOOGLE_API_KEY)
MODEL_NAME = "gemini-embedding-001"

OUTPUT_DIMENSION = 256
BATCH_SIZE = 60
MAX_RETRIES = 3

# --- Пути к файлам ---
DB_FILE = "games.db"
OUTPUT_INDEX_FILE = "games.index"
OUTPUT_MAPPING_FILE = "chunk_map.json"

def chunk_text(text, chunk_size=200, overlap=50):
    """Нарезает текст на чанки с перекрытием."""
    words = text.split()
    if not words: return []
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk_words = words[start:end]
        chunks.append(" ".join(chunk_words))
        if end >= len(words): break
        start += chunk_size - overlap
    return chunks

def generate_embeddings_in_batches(texts):
    """
    Генерирует эмбеддинги, отслеживая успешные и неудачные операции.
    Возвращает список всех эмбеддингов (с None на месте сбоев) и
    список индексов успешно обработанных чанков.
    """
    all_embeddings = []
    successful_indices = []

    num_batches = (len(texts) + BATCH_SIZE - 1) // BATCH_SIZE

    for i in tqdm(range(0, len(texts), BATCH_SIZE), total=num_batches, desc="Генерация эмбеддингов"):
        batch_texts = texts[i:i + BATCH_SIZE]
        retries = 0
        success = False
        while retries < MAX_RETRIES:
            try:
                request_options = {'timeout': 300}
                result = genai.embed_content(
                    model=f"models/{MODEL_NAME}",
                    content=batch_texts,
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=OUTPUT_DIMENSION,
                    request_options=request_options
                )

                all_embeddings.extend(result['embedding'])
                successful_indices.extend(range(i, i + len(result['embedding'])))
                success = True
                break
            except Exception as e:
                retries += 1
                print(f"\nОшибка при обработке батча (попытка {retries}/{MAX_RETRIES}): {e}")
                if retries < MAX_RETRIES:
                    time.sleep(5 * retries)

        if not success:
            print(f"Превышено количество попыток для батча, начинающегося с индекса {i}. Пропускаем.")
            all_embeddings.extend([None] * len(batch_texts))

    return all_embeddings, successful_indices


def main():
    # --- 2. Добавляем парсер аргументов командной строки ---
    parser = argparse.ArgumentParser(description="Индексатор текстов игр для семантического поиска.")
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help="Ограничить индексацию указанным количеством игр (для тестирования)."
    )
    args = parser.parse_args()

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # --- 3. Изменяем SQL-запрос для поддержки лимита ---
    print("Поиск игр для индексации...")
    
    query = """
        SELECT pocketbase_id, title, full_text
        FROM games
        WHERE full_text IS NOT NULL AND full_text != '' AND last_indexed_at IS NULL
    """
    params = []
    
    if args.limit:
        print(f"\n--- РЕЖИМ ТЕСТИРОВАНИЯ: обрабатываем не более {args.limit} игр ---\n")
        query += " LIMIT ?"
        params.append(args.limit)

    cursor.execute(query, params)
    # --- Конец изменений ---

    games_to_index = [
        {"pocketbase_id": r[0], "title": r[1], "full_text": r[2]}
        for r in cursor.fetchall()
    ]

    if not games_to_index:
        print("Не найдено новых игр с текстом для индексации.")
        conn.close()
        return

    print(f"Найдено {len(games_to_index)} игр для индексации. Начинаем обработку...")

    # Для качественной тренировки индекса PQ, мы строим его на основе ВСЕХ игр,
    # у которых есть текст, включая уже проиндексированные.
    cursor.execute("SELECT pocketbase_id, title, full_text FROM games WHERE full_text IS NOT NULL AND full_text != ''")
    all_games_data = [
        {"pocketbase_id": r[0], "title": r[1], "full_text": r[2]}
        for r in cursor.fetchall()
    ]

    all_chunks_texts, chunk_map = [], {}
    current_chunk_index = 0
    print(f"Подготовка чанков для {len(all_games_data)} игр...")

    for game in tqdm(all_games_data, desc="Чанкинг игр"):
        chunks = chunk_text(game['full_text'])
        if not chunks: chunks = [game['full_text']]

        for chunk_text_content in chunks:
            enriched_chunk = f"Из игры '{game['title']}': {chunk_text_content}"
            all_chunks_texts.append(enriched_chunk)

            chunk_map[current_chunk_index] = {
                "game_id": game['pocketbase_id'],
                "text": chunk_text_content
            }
            current_chunk_index += 1

    all_embeddings, successful_indices = generate_embeddings_in_batches(all_chunks_texts)

    if not successful_indices:
        print("Не удалось сгенерировать ни одного эмбеддинга. Проверьте API ключ и квоты.")
        conn.close()
        return

    final_embeddings = [all_embeddings[i] for i in successful_indices]
    final_embeddings_np = np.array(final_embeddings).astype('float32')

    final_chunk_map = {}
    new_idx = 0
    for original_idx in successful_indices:
        final_chunk_map[new_idx] = chunk_map[original_idx]
        new_idx += 1

    num_vectors, dim = final_embeddings_np.shape
    print(f"Успешно сгенерировано {num_vectors} векторов размерностью {dim}.")

    nlist = int(math.sqrt(num_vectors))
    print(f"Выбрано {nlist} кластеров для индекса IVF.")
    m = 16
    quantizer = faiss.IndexFlatL2(dim)
    index = faiss.IndexIVFPQ(quantizer, dim, nlist, m, 8)

    print("Тренировка индекса... (это может занять некоторое время)")
    index.train(final_embeddings_np)

    print("Добавление векторов в индекс...")
    index.add(final_embeddings_np)

    print(f"Оптимизированный индекс создан. Всего векторов: {index.ntotal}")

    faiss.write_index(index, OUTPUT_INDEX_FILE)
    with open(OUTPUT_MAPPING_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_chunk_map, f, ensure_ascii=False, indent=2)

    print("\nИндексация успешно завершена! Обновление статусов в базе данных...")

    game_chunk_counts = {}
    for game in tqdm(games_to_index, desc="Подсчет исходных чанков"):
        chunks = chunk_text(game['full_text'])
        if not chunks: chunks = [game['full_text']]
        game_chunk_counts[game['pocketbase_id']] = len(chunks)

    successful_chunk_counts = {}
    game_ids_to_index_set = {g['pocketbase_id'] for g in games_to_index}

    for chunk_info in final_chunk_map.values():
        game_id = chunk_info['game_id']
        if game_id in game_ids_to_index_set:
            successful_chunk_counts[game_id] = successful_chunk_counts.get(game_id, 0) + 1

    ids_to_update = []
    partially_indexed_count = 0
    for game_id, total_chunks in game_chunk_counts.items():
        successful_chunks = successful_chunk_counts.get(game_id, 0)

        if total_chunks > 0 and total_chunks == successful_chunks:
            ids_to_update.append(game_id)
        elif successful_chunks < total_chunks:
            partially_indexed_count += 1
            print(f"INFO: Игра {game_id}: проиндексировано {successful_chunks}/{total_chunks} чанков. Статус не обновлен, будет повторная попытка.")

    if ids_to_update:
        placeholders = ', '.join('?' for _ in ids_to_update)
        current_time = datetime.now().isoformat()
        cursor.execute(
            f"UPDATE games SET last_indexed_at = ? WHERE pocketbase_id IN ({placeholders})",
            (current_time, *ids_to_update)
        )
        conn.commit()
        print(f"\n{cursor.rowcount} игр помечены как ПОЛНОСТЬЮ проиндексированные.")
    else:
        print("\nНи одна из новых игр не была полностью проиндексирована в этот раз.")

    if partially_indexed_count > 0:
        print(f"{partially_indexed_count} игр были проиндексированы частично и будут обработаны в следующий раз.")

    conn.close()

if __name__ == "__main__":
    main()