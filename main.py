# main.py (Версия с поддержкой режимов поиска и Summary)
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

# --- Конфигурация ---
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=GOOGLE_API_KEY)

EMBEDDING_MODEL_NAME = "gemini-embedding-001"
OUTPUT_DIMENSION = 256
DB_FILE = "games.db"
INDEX_FILE = "games.index"
MAPPING_FILE = "chunk_map.json"
BASE_GAME_URL = "https://cyoa.cafe/games/"

# Настройка смешанного режима
SUMMARY_BONUS_MULTIPLIER = 1.25  # +25% к скору, если совпадение найдено в описании

class SearchMode(str, Enum):
    mixed = "mixed"
    summary = "summary"
    text = "text"

app = FastAPI(title="CYOA Semantic Search API v3 (with Summary)")

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
            # Ключи JSON - строки, конвертируем в int
            chunk_map = {int(k): v for k, v in json.load(f).items()}
        print(f"Индекс загружен: {faiss_index.ntotal} векторов.")
    else:
        print("WARN: Файлы индекса не найдены. Поиск не будет работать.")

@app.get("/search")
async def search_games(
    q: str = Query(..., min_length=2),
    mode: SearchMode = Query(SearchMode.mixed, description="Режим поиска: по тексту, по описанию или смешанный"),
    k: int = 100, # Ищем больше чанков, так как будем фильтровать и агрегировать
    threshold: float = 0.45 # Базовый порог отсечения (Cosine Similarity)
):
    if not faiss_index or not chunk_map:
        raise HTTPException(status_code=503, detail="Индекс не готов.")

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

        # 2. Поиск в Faiss (Inner Product = Cosine Similarity для норм. векторов)
        # D - scores, I - indices
        D, I = faiss_index.search(q_vec, k)

        # 3. Агрегация и фильтрация результатов
        game_scores = {} # {game_id: best_score}
        game_match_reasons = {} # {game_id: "summary" or "text"} для дебага в UI

        indices = I[0]
        scores = D[0]

        for idx, raw_score in zip(indices, scores):
            if idx == -1: continue
            
            idx = int(idx)
            chunk_info = chunk_map.get(idx)
            if not chunk_info: continue

            game_id = chunk_info['game_id']
            chunk_type = chunk_info.get('type', 'text') # 'summary' or 'text'

            # Фильтрация по режиму
            if mode == SearchMode.summary and chunk_type != 'summary': continue
            if mode == SearchMode.text and chunk_type != 'text': continue

            # Расчет финального скора
            final_score = float(raw_score)
            
            # Применяем бонус в смешанном режиме
            if mode == SearchMode.mixed and chunk_type == 'summary':
                final_score *= SUMMARY_BONUS_MULTIPLIER
            
            # Базовый порог отсечения (применяем к сырому скору, чтобы не вытягивать мусор бонусами)
            if raw_score < threshold: continue

            # Агрегация: берем лучший скор для игры
            if game_id not in game_scores or final_score > game_scores[game_id]:
                game_scores[game_id] = final_score
                game_match_reasons[game_id] = chunk_type

        # 4. Сортировка и выбор топ-результатов
        # Сортируем по убыванию скора
        sorted_games = sorted(game_scores.items(), key=lambda x: x[1], reverse=True)
        top_game_ids = [g_id for g_id, score in sorted_games[:20]] # Берем топ-20

        if not top_game_ids:
            return {"results": [], "mode_used": mode}

        # 5. Получение метаданных из БД (включая summary для отображения)
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        placeholders = ','.join('?' * len(top_game_ids))
        # Трюк с ORDER BY CASE для сохранения порядка сортировки
        sql = f"""
            SELECT pocketbase_id, title, summary 
            FROM games 
            WHERE pocketbase_id IN ({placeholders})
            ORDER BY CASE pocketbase_id
        """
        for i, g_id in enumerate(top_game_ids):
            sql += f" WHEN ? THEN {i}"
        sql += " END"
        
        params = top_game_ids + top_game_ids
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()

        # 6. Формирование ответа
        results = []
        game_meta_map = {row[0]: (row[1], row[2]) for row in rows}

        for game_id in top_game_ids:
            if game_id in game_meta_map:
                title, summary = game_meta_map[game_id]
                score = game_scores[game_id]
                
                # Делаем краткое превью саммари, если оно есть
                summary_snippet = ""
                if summary:
                    summary_snippet = summary[:200] + "..."

                # Нормализуем скор для отображения (max 100%, даже с бонусом)
                display_score = min(int(score * 100), 100) 

                results.append({
                    "id": game_id,
                    "title": title,
                    "url": f"{BASE_GAME_URL}{game_id}",
                    "score": display_score,
                    "match_type": game_match_reasons[game_id], # text/summary
                    "snippet": summary_snippet
                })

        return {"results": results, "mode_used": mode}

    except Exception as e:
        print(f"Search Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- Статика и вспомогательные роуты ---
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

# ======== НОВЫЙ ЭНДПОИНТ ДЛЯ ПОЛУЧЕНИЯ СПИСКА ИГР ========
@app.get("/games", response_model=List[Dict[str, Any]])
async def get_all_games():
    """Возвращает список всех игр в базе данных с их статусами."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row  # Позволяет обращаться к колонкам по имени
        cursor = conn.cursor()

        # Выбираем все необходимые поля
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

        # Формируем список для ответа в формате, который ожидает фронтенд
        games_list = []
        for row in rows:
            games_list.append({
                "title": row["title"],
                "summary": row["summary"],
                "has_summary": bool(row["summary"]), # True, если summary не None и не пустая строка
                "is_indexed": row["last_indexed_at"] is not None
            })
        
        return games_list

    except Exception as e:
        print(f"Error fetching all games: {e}")
        raise HTTPException(status_code=500, detail="Could not fetch game list from database.")
# ==========================================================