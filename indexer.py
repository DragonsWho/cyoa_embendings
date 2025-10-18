# indexer.py (Версия с поддержкой Summary и паузой между запросами)
import json
import os
import numpy as np
import faiss
import google.generativeai as genai
import sqlite3
import time
from dotenv import load_dotenv
from tqdm import tqdm
from datetime import datetime
# --- НОВЫЙ ИМПОРТ: Централизованная конфигурация ---
import config

# --- Конфигурация ---
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    raise ValueError("Не найден GOOGLE_API_KEY в .env файле")
genai.configure(api_key=GOOGLE_API_KEY)

def chunk_raw_text(text, chunk_size=500, overlap=50):
    """Разбивает сырой текст игры на чанки."""
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
    """Генерирует эмбеддинги батчами."""
    all_embeddings = []
    successful_indices = []
    
    if not texts: return [], []

    num_batches = (len(texts) + config.BATCH_SIZE - 1) // config.BATCH_SIZE
    for i in tqdm(range(0, len(texts), config.BATCH_SIZE), total=num_batches, desc="API Gemini (Embeddings)"):
        batch_texts = texts[i:i + config.BATCH_SIZE]
        retries = 0
        success = False
        while retries < config.MAX_RETRIES:
            try:
                result = genai.embed_content(
                    model=f"models/{config.EMBEDDING_MODEL_NAME}",
                    content=batch_texts,
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=config.OUTPUT_DIMENSION
                )
                # Gemini может вернуть None для некоторых текстов в батче, если сработают фильтры безопасности
                embeddings = result.get('embedding', [])
                
                # Проверяем, совпадает ли количество вернувшихся эмбеддингов с запрошенным
                if len(embeddings) != len(batch_texts):
                    # Это сложный кейс, для простоты пока пропустим батч
                    print(f"\nВнимание: Gemini вернул {len(embeddings)} векторов для {len(batch_texts)} текстов. Батч пропущен.")
                    break

                all_embeddings.extend(embeddings)
                successful_indices.extend(range(i, i + len(embeddings)))
                success = True
                break
            except Exception as e:
                retries += 1
                print(f"\nОшибка батча {i} (попытка {retries}): {e}")
                time.sleep(2 * retries)
        
        if not success:
             # Заполняем None, чтобы сохранить индексацию списка texts
             all_embeddings.extend([None] * len(batch_texts))

        # Добавляем паузу после обработки каждого батча, чтобы не превышать лимиты API.
        # Небольшая оптимизация: не ждем после самого последнего батча.
        if i + config.BATCH_SIZE < len(texts):
            time.sleep(config.API_REQUEST_DELAY)

    return all_embeddings, successful_indices

def main():
    # Мы всегда пересоздаем индекс целиком для простоты и надежности (Faiss FlatIP быстрый)
    print("Подготовка к полной переиндексации...")

    conn = sqlite3.connect(config.DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Берем ВСЕ игры, у которых есть хоть что-то (текст или саммари)
    cursor.execute("""
        SELECT pocketbase_id, title, full_text, summary 
        FROM games 
        WHERE (full_text IS NOT NULL AND full_text != '') OR (summary IS NOT NULL AND summary != '')
    """)
    all_games = cursor.fetchall()

    if not all_games:
        print("В базе нет данных для индексации.")
        conn.close()
        return

    print(f"Загружено {len(all_games)} игр. Подготовка чанков...")

    texts_to_embed = []
    temp_chunk_map = [] # Список словарей метаданных

    for game in tqdm(all_games, desc="Чанкинг"):
        game_id = game['pocketbase_id']
        game_title = game['title']
        
        # 1. Обработка SUMMARY (если есть)
        if game['summary']:
            # Описание добавляем как один большой, важный чанк.
            # Добавляем контекст в сам текст для лучшей семантики.
            enriched_summary = f"Summary/Description of CYOA game '{game_title}': {game['summary']}"
            texts_to_embed.append(enriched_summary)
            temp_chunk_map.append({
                "game_id": game_id,
                "type": "summary", # Метка типа
                "text_snippet": game['summary'][:300] + "..." # Для дебага в JSON
            })

        # 2. Обработка FULL_TEXT (если есть)
        if game['full_text']:
            raw_chunks = chunk_raw_text(game['full_text'])
            for chunk in raw_chunks:
                enriched_chunk = f"Text excerpt from CYOA game '{game_title}': {chunk}"
                texts_to_embed.append(enriched_chunk)
                temp_chunk_map.append({
                    "game_id": game_id,
                    "type": "text", # Метка типа
                    "text_snippet": chunk[:200] + "..."
                })

    print(f"Всего подготовлено {len(texts_to_embed)} чанков (Summary + Text).")

    # --- Генерация эмбеддингов ---
    raw_embeddings, successful_indices = generate_embeddings_in_batches(texts_to_embed)

    if not successful_indices:
        print("Не удалось сгенерировать эмбеддинги.")
        conn.close()
        return

    # Фильтруем и сопоставляем
    final_embeddings = []
    final_chunk_map = {}
    
    faiss_index_id = 0
    for original_idx in successful_indices:
        emb = raw_embeddings[original_idx]
        if emb is None: continue # Пропуск ошибок
        
        final_embeddings.append(emb)
        # Сохраняем метаданные под новым непрерывным ID для Faiss
        final_chunk_map[faiss_index_id] = temp_chunk_map[original_idx]
        faiss_index_id += 1

    # --- Создание индекса Faiss ---
    embeddings_np = np.array(final_embeddings).astype('float32')
    print("Нормализация векторов (L2) для Cosine Similarity...")
    faiss.normalize_L2(embeddings_np)

    print(f"Создание IndexFlatIP для {len(embeddings_np)} векторов...")
    index = faiss.IndexFlatIP(config.OUTPUT_DIMENSION)
    index.add(embeddings_np)

    # --- Сохранение результатов ---
    print("Сохранение индекса и карты...")
    faiss.write_index(index, config.INDEX_FILE)
    with open(config.MAPPING_FILE, 'w', encoding='utf-8') as f:
        json.dump(final_chunk_map, f, ensure_ascii=False, indent=2)

    # --- Обновление статусов в БД ---
    print("Обновление статуса индексации в базе данных...")
    processed_game_ids = set([info['game_id'] for info in final_chunk_map.values()])
    
    if processed_game_ids:
        current_time = datetime.now().isoformat()
        placeholders = ', '.join('?' for _ in processed_game_ids)
        cursor.execute(
            f"UPDATE games SET last_indexed_at = ? WHERE pocketbase_id IN ({placeholders})",
            (current_time, *processed_game_ids)
        )
        conn.commit()
        print(f"Обновлен статус для {len(processed_game_ids)} игр.")

    conn.close()
    print("\n--- Индексация полностью завершена ---")

if __name__ == "__main__":
    main()