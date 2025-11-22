# main.py (Финальная версия: Поиск + Похожие игры + Логирование)
import os
import json
import numpy as np
import faiss
import google.generativeai as genai
import sqlite3
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import List, Dict, Any
from enum import Enum
from collections import defaultdict
from datetime import datetime
import math
import logging
from fastapi.middleware.cors import CORSMiddleware 
import config

# --- Конфигурация ---
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=GOOGLE_API_KEY)

# --- ЛОГИРОВАНИЕ ---
if config.DEBUG_LOGGING:
    logger = logging.getLogger(__name__)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        file_handler = logging.FileHandler(config.LOG_FILE, mode='a', encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        logger.addHandler(file_handler)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(console_handler)
else:
    class DummyLogger:
        def info(self, msg, *args, **kwargs): pass
    logger = DummyLogger()

# Логгер запросов (всегда пишет в файл JSONL)
QUERY_LOG_FILE = config.QUERY_LOG_FILE
query_logger = logging.getLogger('user_queries')
query_logger.setLevel(logging.INFO)
query_logger.propagate = False
if not query_logger.handlers:
    query_handler = logging.FileHandler(QUERY_LOG_FILE, mode='a', encoding='utf-8')
    query_handler.setFormatter(logging.Formatter('%(message)s'))
    query_logger.addHandler(query_handler)

class SearchMode(str, Enum):
    mixed = "mixed"
    summary = "summary"
    text = "text"

app = FastAPI(title="CYOA Semantic Search API v6 (Similars)")

origins = [
    "https://cyoa.cafe",      
    "http://localhost:5173", 
    "http://127.0.0.1:5173",
    "http://localhost:8091", # Для Vite proxy
    "http://127.0.0.1:8091",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Глобальные переменные    
faiss_index = None
chunk_map = {}
game_to_faiss_map = {} # Обратный индекс: GameID -> Лучший VectorID

@app.on_event("startup")
def load_data():
    global faiss_index, chunk_map, game_to_faiss_map
    print("Загрузка индекса и карты...")
    if os.path.exists(config.INDEX_FILE) and os.path.exists(config.MAPPING_FILE):
        faiss_index = faiss.read_index(config.INDEX_FILE)
        with open(config.MAPPING_FILE, 'r', encoding='utf-8') as f:
            chunk_map = {int(k): v for k, v in json.load(f).items()}
        
        # Строим карту для поиска похожих игр
        print("Построение карты GameID -> VectorID...")
        for faiss_id, meta in chunk_map.items():
            g_id = meta['game_id']
            g_type = meta.get('type', 'text')
            
            # Логика: Сначала берем любой. Если встречаем summary - заменяем, так как он лучше описывает игру.
            if g_id not in game_to_faiss_map:
                game_to_faiss_map[g_id] = faiss_id
            
            if g_type == 'summary':
                game_to_faiss_map[g_id] = faiss_id
                
        print(f"Индекс загружен: {faiss_index.ntotal} векторов. Обратный индекс: {len(game_to_faiss_map)} игр.")
    else:
        print("WARN: Файлы индекса не найдены. Поиск не будет работать.")

def get_db_connection():
    # check_same_thread=False нужен для SQLite в многопоточном FastAPI
    connection = sqlite3.connect(config.DB_FILE, check_same_thread=False)
    try:
        yield connection
    finally:
        connection.close()

# --- ПОИСК (TEXT QUERY) ---
@app.get("/api/semantic-search")
async def search_games(
    q: str = Query(..., min_length=2),
    mode: SearchMode = Query(SearchMode.mixed),
    k: int = 200,
    threshold: float = 0.40, 
    conn: sqlite3.Connection = Depends(get_db_connection)
):
    if not faiss_index or not chunk_map:
        raise HTTPException(status_code=503, detail="Индекс не готов.")

    logger.info(f"\n{'='*25} НОВЫЙ ПОИСКОВЫЙ ЗАПРОС {'='*25}")
    logger.info(f"Query: '{q}' | Mode: {mode} | k: {k} | threshold: {threshold}")
    
    try:
        # 1. Эмбеддинг
        q_emb = genai.embed_content(
            model=f"models/{config.EMBEDDING_MODEL_NAME}",
            content=q,
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=config.OUTPUT_DIMENSION
        )['embedding']
        q_vec = np.array([q_emb]).astype('float32')
        faiss.normalize_L2(q_vec)

        # 2. Retrieval
        D, I = faiss_index.search(q_vec, k)
        indices = I[0]
        scores = D[0]
        logger.info(f"[Фаза 1] Поиск в Faiss. Найдено {len(indices)} потенциальных чанков.")

        # 3. Агрегация
        game_data = defaultdict(lambda: {"summary_chunks": [], "text_chunks": []})

        for idx, raw_score in zip(indices, scores):
            if idx == -1 or raw_score < threshold: continue
            chunk_info = chunk_map.get(int(idx))
            if not chunk_info: continue

            game_id = chunk_info['game_id']
            chunk_type = chunk_info.get('type', 'text')

            if mode == SearchMode.summary and chunk_type != 'summary': continue
            if mode == SearchMode.text and chunk_type != 'text': continue
            
            chunk_details = {"score": float(raw_score), "snippet": chunk_info.get('text_snippet', 'N/A')}

            if chunk_type == 'summary': game_data[game_id]["summary_chunks"].append(chunk_details)
            else: game_data[game_id]["text_chunks"].append(chunk_details)

        if not game_data:
            return {"results": [], "mode_used": mode}
        
        logger.info(f"\n--- [Фаза 2] Агрегация чанков по {len(game_data)} играм ---")

        # 4. Re-ranking
        logger.info("\n--- [Фаза 3] Расчет очков ---")
        final_game_scores = {}

        for game_id, data in game_data.items():
            summary_scores = [c['score'] for c in data['summary_chunks']]
            text_scores = [c['score'] for c in data['text_chunks']]
            
            summary_score = max(summary_scores or [0])
            
            text_score = 0
            sorted_text_scores = sorted(text_scores, reverse=True)
            for i, score in enumerate(sorted_text_scores):
                # Используем config.DECAY_FACTOR
                text_score += score * (config.DECAY_FACTOR ** i)
            
            normalizing_divisor = 5.0 
            normalized_text_score = math.log1p(text_score) / normalizing_divisor if text_score > 0 else 0

            # Используем веса из config
            final_score = (summary_score * config.SUMMARY_WEIGHT) + (normalized_text_score * config.TEXT_WEIGHT)
            
            final_game_scores[game_id] = {
                "score": final_score,
                "match_type": "summary" if summary_score > 0 else "text"
            }

        # 5. Сортировка
        sorted_games = sorted(final_game_scores.items(), key=lambda item: item[1]["score"], reverse=True)
        top_games = sorted_games[:20]
        top_game_ids = [g_id for g_id, data in top_games]

        if not top_game_ids: return {"results": [], "mode_used": mode}
        
        logger.info("\n--- [Фаза 4] Финальный топ-20 ---")
        for i, (game_id, score_data) in enumerate(top_games):
             logger.info(f"  #{i+1}: ID={game_id}, Final Score={score_data['score']:.4f}")

        # 6. Метаданные
        cursor = conn.cursor()
        placeholders = ','.join('?' * len(top_game_ids))
        # Запрашиваем 4 поля
        sql = f"SELECT pocketbase_id, title, summary, original_url FROM games WHERE pocketbase_id IN ({placeholders})"
        cursor.execute(sql, top_game_ids)
        rows = cursor.fetchall()

        # Исправлено: сохраняем все 3 значения в словарь
        game_meta_map = {row[0]: (row[1], row[2], row[3]) for row in rows}
        
        results = []
        for game_id, score_data in top_games:
            meta = game_meta_map.get(game_id)
            if meta:
                title, summary, original_url = meta # Распаковка 3 значений
                
                snippet = (summary[:200] + "...") if summary else ""
                display_score = min(int(score_data["score"] * 100), 100)

                results.append({
                    "id": game_id,
                    "title": title,
                    "url": original_url or f"{config.BASE_GAME_URL}{game_id}",
                    "score": display_score,
                    "match_type": score_data["match_type"],
                    "snippet": snippet
                })
        
        # Логирование запроса
        try:
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "query": q,
                "mode": mode.value,
                "results_count": len(results),
                "top_results": [{"id": r["id"], "title": r["title"], "score": r["score"]} for r in results[:3]]
            }
            query_logger.info(json.dumps(log_entry, ensure_ascii=False))
        except Exception: pass
        
        logger.info(f"{'='*28} КОНЕЦ ЗАПРОСА {'='*28}\n")
        return {"results": results, "mode_used": mode}

    except Exception as e:
        logger.info(f"КРИТИЧЕСКАЯ ОШИБКА: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- ПОХОЖИЕ ИГРЫ (VECTOR SEARCH) ---
@app.get("/api/similar-games/{game_id}")
async def find_similar_games(
    game_id: str,
    k: int = 21, 
    conn: sqlite3.Connection = Depends(get_db_connection)
):
    """Находит игры, похожие на указанную, используя её вектор."""
    if not faiss_index or not game_to_faiss_map:
         raise HTTPException(status_code=503, detail="Индекс не готов.")
    
    target_faiss_id = game_to_faiss_map.get(game_id)
    if target_faiss_id is None:
        raise HTTPException(status_code=404, detail="Game not found in index.")

    try:
        # Достаем вектор из индекса
        source_vector = faiss_index.reconstruct(target_faiss_id)
        source_vector = np.array([source_vector]).astype('float32')
        
        # Ищем соседей
        D, I = faiss_index.search(source_vector, k)
        indices = I[0]
        scores = D[0]
        
        similar_game_ids = []
        game_scores = {}
        
        for idx, score in zip(indices, scores):
            if idx == -1: continue
            match_info = chunk_map.get(int(idx))
            if not match_info: continue
            found_game_id = match_info['game_id']
            
            if found_game_id == game_id: continue # Пропускаем саму себя
            if found_game_id not in similar_game_ids:
                similar_game_ids.append(found_game_id)
                game_scores[found_game_id] = float(score)

        if not similar_game_ids: return {"results": []}

        # Метаданные для похожих
        cursor = conn.cursor()
        placeholders = ','.join('?' * len(similar_game_ids))
        sql = f"SELECT pocketbase_id, title, summary, original_url FROM games WHERE pocketbase_id IN ({placeholders})"
        cursor.execute(sql, similar_game_ids)
        rows = cursor.fetchall()
        
        meta_map = {row[0]: (row[1], row[2], row[3]) for row in rows}
        
        results = []
        for g_id in similar_game_ids:
            meta = meta_map.get(g_id)
            if meta:
                title, summary, url = meta
                results.append({
                    "id": g_id,
                    "title": title,
                    "score": int(game_scores[g_id] * 100),
                    "url": url or f"{config.BASE_GAME_URL}{g_id}",
                    "snippet": (summary[:150] + "...") if summary else ""
                })
                
        return {"results": results}

    except Exception as e:
        print(f"Similar search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- СТАТИКА И ВСПОМОГАТЕЛЬНЫЕ ---
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_root():
    return FileResponse("static/index.html")

@app.get("/stats")
async def get_stats(conn: sqlite3.Connection = Depends(get_db_connection)):
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    with_text = cur.execute("SELECT COUNT(*) FROM games WHERE full_text IS NOT NULL AND full_text != ''").fetchone()[0]
    with_summary = cur.execute("SELECT COUNT(*) FROM games WHERE summary IS NOT NULL AND summary != ''").fetchone()[0]
    indexed = cur.execute("SELECT COUNT(*) FROM games WHERE last_indexed_at IS NOT NULL").fetchone()[0]
    return {"total": total, "with_text": with_text, "with_summary": with_summary, "indexed": indexed}

@app.get("/games", response_model=List[Dict[str, Any]])
async def get_all_games(conn: sqlite3.Connection = Depends(get_db_connection)):
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT title, summary, last_indexed_at FROM games ORDER BY title ASC")
        rows = cursor.fetchall()
        return [{
            "title": row["title"],
            "summary": row["summary"],
            "has_summary": bool(row["summary"]),
            "is_indexed": row["last_indexed_at"] is not None
        } for row in rows]
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail="DB Error")