# indexer.py (новая, более надежная версия)
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
    
    # i - это глобальный индекс начала батча в исходном списке `texts`
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
                # Записываем глобальные индексы успешно обработанных чанков
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
            # Добавляем "пустышки" (None) для сбойных батчей, чтобы сохранить структуру
            all_embeddings.extend([None] * len(batch_texts))

    return all_embeddings, successful_indices


def main():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Запрашиваем игры, которые еще не индексированы и у которых есть текст
    print("Поиск игр для индексации...")
    cursor.execute("""
        SELECT pocketbase_id, title, full_text
        FROM games
        WHERE full_text IS NOT NULL AND full_text != '' AND last_indexed_at IS NULL
    """)
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

    # --- Генерация эмбеддингов с обработкой ошибок ---
    all_embeddings, successful_indices = generate_embeddings_in_batches(all_chunks_texts)

    if not successful_indices:
        print("Не удалось сгенерировать ни одного эмбеддинга. Проверьте API ключ и квоты.")
        conn.close()
        return
        
    # --- Фильтруем данные, оставляя только успешные результаты ---
    final_embeddings = [all_embeddings[i] for i in successful_indices]
    final_embeddings_np = np.array(final_embeddings).astype('float32')
    
    final_chunk_map = {}
    new_idx = 0
    for original_idx in successful_indices:
        final_chunk_map[new_idx] = chunk_map[original_idx]
        new_idx += 1
    
    num_vectors, dim = final_embeddings_np.shape
    print(f"Успешно сгенерировано {num_vectors} векторов размерностью {dim}.")

    # --- Создание и тренировка индекса Faiss ---
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
    
    # --- Сохранение результатов ---
    faiss.write_index(index, OUTPUT_INDEX_FILE)
    with open(OUTPUT_MAPPING_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_chunk_map, f, ensure_ascii=False, indent=2)

    # --- Умное обновление статусов в базе данных ---
    print("\nИндексация успешно завершена! Обновление статусов в базе данных...")
    
    # 1. Собираем ID всех игр, чьи чанки попали в финальный индекс
    game_ids_in_index = set(item['game_id'] for item in final_chunk_map.values())
    
    # 2. Помечаем как проиндексированные только те игры, что были в списке "к индексации"
    #    И которые при этом попали в индекс.
    ids_to_update = [
        game['pocketbase_id'] for game in games_to_index 
        if game['pocketbase_id'] in game_ids_in_index
    ]
    
    if ids_to_update:
        placeholders = ', '.join('?' for _ in ids_to_update)
        # Используем `DeprecationWarning` для совместимости с Python 3.12+
        # Для старых версий можно оставить как было.
        current_time = datetime.now().isoformat()
        cursor.execute(
            f"UPDATE games SET last_indexed_at = ? WHERE pocketbase_id IN ({placeholders})",
            (current_time, *ids_to_update)
        )
        conn.commit()
        print(f"{cursor.rowcount} игр помечены как проиндексированные.")
    else:
        print("Ни одна из новых игр не была проиндексирована из-за ошибок API.")

    conn.close()

if __name__ == "__main__":
    main()