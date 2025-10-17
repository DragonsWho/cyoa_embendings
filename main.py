# main.py (ФИНАЛЬНАЯ ИСПРАВЛЕННАЯ ВЕРСИЯ)
import os
import json
import numpy as np
import faiss
import google.generativeai as genai
import sqlite3
import math
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import List, Dict, Any
from pydantic import BaseModel
from typing import List


# --- Конфигурация ---
load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    raise ValueError("Не найден GOOGLE_API_KEY в .env файле")

genai.configure(api_key=GOOGLE_API_KEY)
MODEL_NAME = "gemini-embedding-001"
OUTPUT_DIMENSION = 256
DB_FILE = "games.db"
INDEX_FILE = "games.index"
MAPPING_FILE = "chunk_map.json"
BASE_GAME_URL = "https://cyoa.cafe/games/"

app = FastAPI(
    title="CYOA Semantic Search API",
    version="2.5.0 (Stable)",
    description="API для семантического поиска. Использует точный индекс Faiss IndexFlatIP."
)

# --- Глобальные переменные для хранения индекса и карты ---
faiss_index = None
chunk_map = {}

@app.on_event("startup")
def load_search_index():
    global faiss_index, chunk_map
    print("Загрузка индекса Faiss и карты чанков...")
    
    if not os.path.exists(INDEX_FILE) or not os.path.exists(MAPPING_FILE):
        print(f"ПРЕДУПРЕЖДЕНИЕ: Файлы индекса '{INDEX_FILE}' или карты '{MAPPING_FILE}' не найдены.")
        print("Поиск будет недоступен. Запустите indexer.py для их создания.")
        return

    try:
        faiss_index = faiss.read_index(INDEX_FILE)
        # --- ИЗМЕНЕНИЕ: nprobe больше не нужен для 'плоского' индекса ---
        # faiss_index.nprobe = 10 
        print(f"Точный индекс '{INDEX_FILE}' успешно загружен. Всего векторов: {faiss_index.ntotal}")

        with open(MAPPING_FILE, 'r', encoding='utf-8') as f:
            raw_map = json.load(f)
            chunk_map = {int(k): v for k, v in raw_map.items()}
        print(f"Карта чанков '{MAPPING_FILE}' успешно загружена. Записей: {len(chunk_map)}")

    except Exception as e:
        print(f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось загрузить индекс или карту чанков: {e}")
        faiss_index = None

@app.get("/search",
         summary="Поиск игр по текстовому запросу",
         response_description="Список найденных игр, отсортированных по релевантности")
async def search_games(
    q: str = Query(..., min_length=3, description="Текстовый поисковый запрос. Например, 'космические приключения с эльфами'"),
    k: int = Query(50, ge=1, le=100, description="Количество ближайших чанков для анализа."),
    # --- ИЗМЕНЕНИЕ: Устанавливаем более реалистичный порог по умолчанию ---
    threshold: float = Query(0.4, ge=0.0, le=1.0, description="Порог релевантности (косинусное сходство). Результаты с оценкой ниже этого значения будут отброшены.")
) -> Dict[str, List[Dict[str, Any]]]:
    if faiss_index is None or not chunk_map:
        raise HTTPException(
            status_code=503,
            detail="Сервис поиска временно недоступен: индекс не загружен."
        )

    try:
        query_embedding_result = genai.embed_content(
            model=f"models/{MODEL_NAME}",
            content=q,
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=OUTPUT_DIMENSION
        )
        query_vector = np.array([query_embedding_result['embedding']]).astype('float32')
        faiss.normalize_L2(query_vector)

        scores, indices = faiss_index.search(query_vector, k)
        
        game_scores = {}
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1: continue
            
            if score < threshold:
                # Так как результаты теперь отсортированы правильно,
                # можно прервать цикл, как только оценка стала слишком низкой.
                break 

            chunk_info = chunk_map.get(int(idx))
            if not chunk_info: continue
            
            game_id = chunk_info["game_id"]
            
            if game_id not in game_scores or score > game_scores[game_id]:
                game_scores[game_id] = float(score)
        
        if not game_scores:
            return {"results": []}

        sorted_game_ids = [
            item[0] for item in sorted(game_scores.items(), key=lambda item: item[1], reverse=True)
        ]
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        placeholders = ', '.join('?' for _ in sorted_game_ids)
        query_sql = f"""
            SELECT pocketbase_id, title FROM games WHERE pocketbase_id IN ({placeholders})
            ORDER BY CASE pocketbase_id {' '.join(f'WHEN ? THEN {i}' for i, _ in enumerate(sorted_game_ids))} END
        """
        params = sorted_game_ids * 2
        cursor.execute(query_sql, params)
        
        games_metadata = {row[0]: {"title": row[1]} for row in cursor.fetchall()}
        conn.close()

        results = []
        for game_id in sorted_game_ids[:10]:
            meta = games_metadata.get(game_id)
            if not meta: continue
            
            results.append({
                "id": game_id,
                "title": meta["title"],
                "url": f"{BASE_GAME_URL}{game_id}",
                "score": int(game_scores[game_id] * 100)
            })

        return {"results": results}
    except Exception as e:
        print(f"Ошибка при выполнении поиска для запроса '{q}': {e}")
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка сервера при обработке запроса: {e}")


# --- Остальная часть файла без изменений ---
class GameInfo(BaseModel):
    id: str
    title: str

@app.get("/stats", summary="Получить статистику по базе данных")
async def get_stats():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM games")
        total_games = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM games WHERE last_indexed_at IS NOT NULL")
        indexed_games = cursor.fetchone()[0]
        conn.close()
        return {"total_games": total_games, "indexed_games": indexed_games}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка чтения базы данных: {e}")

@app.get("/games", summary="Получить список всех игр", response_model=List[GameInfo])
async def get_all_games():
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row 
        cursor = conn.cursor()
        cursor.execute("SELECT pocketbase_id as id, title FROM games ORDER BY title ASC")
        games = cursor.fetchall()
        conn.close()
        return [dict(row) for row in games]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка чтения базы данных: {e}")
    
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=FileResponse, include_in_schema=False)
async def read_root():
    return "static/index.html"