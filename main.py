# main.py (Финальная версия с продвинутым ранжированием и ЛОГИРОВАНИЕМ ЗАПРОСОВ)
import os
import json
import numpy as np
import faiss
import google.generativeai as genai
import sqlite3
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import List, Dict, Any
from enum import Enum
from collections import defaultdict
from datetime import datetime # <--- НОВЫЙ ИМПОРТ
import math
import logging

# --- Конфигурация ---
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=GOOGLE_API_KEY)

EMBEDDING_MODEL_NAME = "gemini-embedding-001"
OUTPUT_DIMENSION = 256
DB_FILE = "games.db"
INDEX_FILE = "games.index"
MAPPING_FILE = "chunk_map.json"
BASE_GAME_URL = "https://cyoa.cafe/game/"

# --- ПАРАМЕТРЫ ДЛЯ РАНЖИРОВАНИЯ ---
SUMMARY_WEIGHT = 0.70 
TEXT_WEIGHT = 0.30    
DECAY_FACTOR = 0.85 

# --- СЕКЦИЯ: КОНФИГУРАЦИЯ ЛОГИРОВАНИЯ ---
# --- ИЗМЕНЕНИЕ: Отключаем детальное логгирование для продакшена ---
DEBUG_LOGGING = False
LOG_FILE = "search_debug.log"

# Настраиваем логгер только если логирование включено
if DEBUG_LOGGING:
    # Используем getLogger, чтобы избежать проблем с uvicorn --reload
    logger = logging.getLogger(__name__)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        # Убираем все предыдущие обработчики
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        
        # Создаем обработчик для файла
        file_handler = logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        logger.addHandler(file_handler)

        # Создаем обработчик для консоли (для удобства)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter('%(message)s')) # Формат покороче для консоли
        logger.addHandler(console_handler)
else:
    # Если логирование выключено, создаем "пустышку", чтобы код не падал
    class DummyLogger:
        def info(self, msg, *args, **kwargs): pass
    logger = DummyLogger()

# --- НОВЫЙ БЛОК: ЛОГИРОВАНИЕ ЗАПРОСОВ ПОЛЬЗОВАТЕЛЕЙ ДЛЯ АНАЛИТИКИ ---
QUERY_LOG_FILE = "user_queries.jsonl"

# Настраиваем специальный логгер для сохранения запросов в виде JSON
query_logger = logging.getLogger('user_queries')
query_logger.setLevel(logging.INFO)

# Убираем обработчики по умолчанию, чтобы избежать дублирования вывода в консоль
query_logger.propagate = False

# Добавляем файловый обработчик, если его еще нет
if not query_logger.handlers:
    # Используем mode='a' для дозаписи в файл
    query_handler = logging.FileHandler(QUERY_LOG_FILE, mode='a', encoding='utf-8')
    # Форматтер выводит только само сообщение, т.к. мы передаем готовую JSON-строку
    query_handler.setFormatter(logging.Formatter('%(message)s'))
    query_logger.addHandler(query_handler)
# --- КОНЕЦ НОВОГО БЛОКА ---
# --- КОНЕЦ СЕКЦИИ ЛОГИРОВАНИЯ ---


class SearchMode(str, Enum):
    mixed = "mixed"
    summary = "summary"
    text = "text"

app = FastAPI(title="CYOA Semantic Search API v5 (User Query Logging)")

# Глобальные переменные
faiss_index = None
chunk_map = {}

@app.on_event("startup")
def load_data():
    global faiss_index, chunk_map
    print("Загрузка индекса и карты...")
    if os.path.exists(INDEX_FILE) and os.path.exists(MAPPING_FILE):
        faiss_index = faiss.read_index(INDEX_FILE)
        with open(MAPPING_FILE, 'r', encoding='utf-8') as f:
            chunk_map = {int(k): v for k, v in json.load(f).items()}
        print(f"Индекс загружен: {faiss_index.ntotal} векторов.")
    else:
        print("WARN: Файлы индекса не найдены. Поиск не будет работать.")

@app.get("/search")
async def search_games(
    q: str = Query(..., min_length=2),
    mode: SearchMode = Query(SearchMode.mixed, description="Режим поиска: по тексту, по описанию или смешанный"),
    k: int = 200, 
    threshold: float = 0.40 
):
    if not faiss_index or not chunk_map:
        raise HTTPException(status_code=503, detail="Индекс не готов.")

    logger.info(f"\n{'='*25} НОВЫЙ ПОИСКОВЫЙ ЗАПРОС {'='*25}")
    logger.info(f"Query: '{q}' | Mode: {mode} | k: {k} | threshold: {threshold}")
    
    try:
        # 1. Эмбеддинг запроса
        q_emb = genai.embed_content(
            model=f"models/{EMBEDDING_MODEL_NAME}",
            content=q,
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=OUTPUT_DIMENSION
        )['embedding']
        q_vec = np.array([q_emb]).astype('float32')
        faiss.normalize_L2(q_vec)

        # 2. Фаза 1: Retrieval - Поиск K ближайших ЧАНКОВ
        D, I = faiss_index.search(q_vec, k)
        
        indices = I[0]
        scores = D[0]
        logger.info(f"[Фаза 1] Поиск в Faiss. Найдено {len(indices)} потенциальных чанков-кандидатов.")

        # 3. Агрегация данных по играм
        game_data = defaultdict(lambda: {"summary_chunks": [], "text_chunks": []})

        for idx, raw_score in zip(indices, scores):
            if idx == -1 or raw_score < threshold: continue
            
            chunk_info = chunk_map.get(int(idx))
            if not chunk_info: continue

            game_id = chunk_info['game_id']
            chunk_type = chunk_info.get('type', 'text')

            if mode == SearchMode.summary and chunk_type != 'summary': continue
            if mode == SearchMode.text and chunk_type != 'text': continue
            
            chunk_details = {
                "score": float(raw_score),
                "snippet": chunk_info.get('text_snippet', 'N/A')
            }

            if chunk_type == 'summary':
                game_data[game_id]["summary_chunks"].append(chunk_details)
            else:
                game_data[game_id]["text_chunks"].append(chunk_details)

        if not game_data:
            logger.info("Порог релевантности не пройден ни одним чанком. Результатов нет.")
            return {"results": [], "mode_used": mode}
        
        logger.info(f"\n--- [Фаза 2] Агрегация чанков по {len(game_data)} играм ---")
        for game_id, data in game_data.items():
            logger.info(f"Игра ID: {game_id}")
            for chunk in data['summary_chunks']:
                logger.info(f"  [SUMMARY] Score: {chunk['score']:.4f} | Snippet: {chunk['snippet']}")
            for chunk in data['text_chunks']:
                logger.info(f"  [TEXT]    Score: {chunk['score']:.4f} | Snippet: {chunk['snippet']}")

        # 4. Фаза 2: Re-ranking - Применяем "Золотую формулу"
        logger.info("\n--- [Фаза 3] Переранжирование и расчет 'Волшебной формулы' ---")
        final_game_scores = {}

        for game_id, data in game_data.items():
            summary_scores = [c['score'] for c in data['summary_chunks']]
            text_scores = [c['score'] for c in data['text_chunks']]
            
            summary_score = max(summary_scores or [0])
            
            text_score = 0
            sorted_text_scores = sorted(text_scores, reverse=True)
            for i, score in enumerate(sorted_text_scores):
                text_score += score * (DECAY_FACTOR ** i)
            
            normalizing_divisor = 5.0 
            normalized_text_score = math.log1p(text_score) / normalizing_divisor if text_score > 0 else 0

            final_score = (summary_score * SUMMARY_WEIGHT) + (normalized_text_score * TEXT_WEIGHT)
            
            final_game_scores[game_id] = {
                "score": final_score,
                "match_type": "summary" if summary_score > 0 else "text"
            }
            
            log_msg = (
                f"Расчет для игры ID: {game_id}\n"
                f"  - Summary Scores: {[f'{s:.4f}' for s in summary_scores]}\n"
                f"  - -> Max Summary Score (A): {summary_score:.4f}\n"
                f"  - Text Scores (sorted): {[f'{s:.4f}' for s in sorted_text_scores]}\n"
                f"  - -> Raw Text Score (decayed sum): {text_score:.4f}\n"
                f"  - -> Normalized Text Score (B): {normalized_text_score:.4f}\n"
                f"  >>> ИТОГОВАЯ ФОРМУЛА: (A * {SUMMARY_WEIGHT}) + (B * {TEXT_WEIGHT})\n"
                f"  >>> РЕЗУЛЬТАТ: ({summary_score:.4f} * {SUMMARY_WEIGHT}) + ({normalized_text_score:.4f} * {TEXT_WEIGHT}) = {final_score:.4f}"
            )
            logger.info(log_msg)
            
        # 5. Сортировка и выбор топ-результатов
        sorted_games = sorted(final_game_scores.items(), key=lambda item: item[1]["score"], reverse=True)
        top_games = sorted_games[:20]
        top_game_ids = [g_id for g_id, data in top_games]

        if not top_game_ids:
            return {"results": [], "mode_used": mode}
        
        logger.info("\n--- [Фаза 4] Финальный топ-20 ---")
        for i, (game_id, score_data) in enumerate(top_games):
             logger.info(f"  #{i+1}: ID={game_id}, Final Score={score_data['score']:.4f}")

        # 6. Получение метаданных из БД и формирование ответа
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        placeholders = ','.join('?' * len(top_game_ids))
        sql = f"SELECT pocketbase_id, title, summary FROM games WHERE pocketbase_id IN ({placeholders})"
        cursor.execute(sql, top_game_ids)
        rows = cursor.fetchall()
        conn.close()

        game_meta_map = {row[0]: (row[1], row[2]) for row in rows}
        
        results = []
        for game_id, score_data in top_games:
            if game_id in game_meta_map:
                title, summary = game_meta_map[game_id]
                summary_snippet = (summary[:200] + "...") if summary else ""
                
                display_score = min(int(score_data["score"] * 100), 100)

                results.append({
                    "id": game_id,
                    "title": title,
                    "url": f"{BASE_GAME_URL}{game_id}",
                    "score": display_score,
                    "match_type": score_data["match_type"],
                    "snippet": summary_snippet
                })
        
        # --- НОВЫЙ БЛОК: Компактное логирование запроса и результатов ---
        try:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "query": q,
                "mode": mode.value,
                "results_count": len(results),
                "top_results": [
                    {"id": r["id"], "title": r["title"], "score": r["score"]} 
                    for r in results[:3]
                ]
            }
            # Преобразуем в JSON и записываем в лог
            query_logger.info(json.dumps(log_entry, ensure_ascii=False))
        except Exception as log_e:
            # Не ломаем ответ пользователю, если логирование упало.
            print(f"ERROR: Could not write user query to log: {log_e}")
        # --- КОНЕЦ НОВОГО БЛОКА ---
        
        logger.info(f"{'='*28} КОНЕЦ ЗАПРОСА {'='*28}\n")
        return {"results": results, "mode_used": mode}

    except Exception as e:
        logger.info(f"КРИТИЧЕСКАЯ ОШИБКА ПОИСКА: {e}")
        # --- НОВЫЙ БЛОК: Логируем также и ошибку в файл запросов ---
        try:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "query": q,
                "mode": mode.value,
                "error": str(e)
            }
            query_logger.info(json.dumps(log_entry, ensure_ascii=False))
        except Exception as log_e:
             print(f"ERROR: Could not write user query error to log: {log_e}")
        # --- КОНЕЦ НОВОГО БЛОКА ---
        raise HTTPException(status_code=500, detail=str(e))

# --- Статика и вспомогательные роуты (без изменений) ---
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_root():
    return FileResponse("static/index.html")

@app.get("/stats")
async def get_stats():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    with_text = cur.execute("SELECT COUNT(*) FROM games WHERE full_text IS NOT NULL AND full_text != ''").fetchone()[0]
    with_summary = cur.execute("SELECT COUNT(*) FROM games WHERE summary IS NOT NULL AND summary != ''").fetchone()[0]
    indexed = cur.execute("SELECT COUNT(*) FROM games WHERE last_indexed_at IS NOT NULL").fetchone()[0]
    conn.close()
    return {"total": total, "with_text": with_text, "with_summary": with_summary, "indexed": indexed}

@app.get("/games", response_model=List[Dict[str, Any]])
async def get_all_games():
    """Возвращает список всех игр в базе данных с их статусами."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                title, 
                summary, 
                last_indexed_at 
            FROM games 
            ORDER BY title ASC
        """)
        rows = cursor.fetchall()
        conn.close()

        games_list = []
        for row in rows:
            games_list.append({
                "title": row["title"],
                "summary": row["summary"],
                "has_summary": bool(row["summary"]),
                "is_indexed": row["last_indexed_at"] is not None
            })
        
        return games_list

    except Exception as e:
        print(f"Error fetching all games: {e}")
        raise HTTPException(status_code=500, detail="Could not fetch game list from database.")