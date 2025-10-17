# main.py (Финальная версия с продвинутым ранжированием)
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
from collections import defaultdict # <--- НОВЫЙ ИМПОРТ
import math # <--- НОВЫЙ ИМПОРТ

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

# --- НОВЫЕ ПАРАМЕТРЫ ДЛЯ РАНЖИРОВАНИЯ ---
# Веса для финальной формулы. В сумме должны давать 1.0
SUMMARY_WEIGHT = 0.70 # Описание - самый важный сигнал
TEXT_WEIGHT = 0.30    # Плотность в тексте - вспомогательный сигнал

# Фактор затухания для очков текстовых чанков. 
# Чем ближе к 1, тем больше похоже на простое суммирование.
# Чем меньше, тем важнее только самые топовые чанки. 0.85 - хороший баланс.
DECAY_FACTOR = 0.85 

class SearchMode(str, Enum):
    mixed = "mixed"
    summary = "summary"
    text = "text"

app = FastAPI(title="CYOA Semantic Search API v4 (Advanced Ranking)")

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
    k: int = 200, # Фаза 1: Ищем больше кандидатов (было 100)
    threshold: float = 0.40 # Можно чуть снизить порог, т.к. re-ranking отсеет мусор
):
    if not faiss_index or not chunk_map:
        raise HTTPException(status_code=503, detail="Индекс не готов.")

    try:
        # 1. Эмбеддинг запроса (без изменений)
        q_emb = genai.embed_content(
            model=f"models/{EMBEDDING_MODEL_NAME}",
            content=q,
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=OUTPUT_DIMENSION
        )['embedding']
        q_vec = np.array([q_emb]).astype('float32')
        faiss.normalize_L2(q_vec)

        # 2. Фаза 1: Retrieval - Поиск K ближайших ЧАНКОВ в Faiss
        D, I = faiss_index.search(q_vec, k)
        
        indices = I[0]
        scores = D[0]

        # 3. Агрегация данных по играм для re-ranking'а
        # Вместо простого словаря, используем defaultdict для удобства
        # Структура: { game_id: {"summary_scores": [0.85], "text_scores": [0.7, 0.65, ...]} }
        game_data = defaultdict(lambda: {"summary_scores": [], "text_scores": [], "match_types": set()})

        for idx, raw_score in zip(indices, scores):
            if idx == -1 or raw_score < threshold: continue
            
            chunk_info = chunk_map.get(int(idx))
            if not chunk_info: continue

            game_id = chunk_info['game_id']
            chunk_type = chunk_info.get('type', 'text')

            # Фильтрация по режиму (если выбран не mixed)
            if mode == SearchMode.summary and chunk_type != 'summary': continue
            if mode == SearchMode.text and chunk_type != 'text': continue
            
            # Собираем все релевантные очки для каждой игры
            if chunk_type == 'summary':
                game_data[game_id]["summary_scores"].append(float(raw_score))
            else:
                game_data[game_id]["text_scores"].append(float(raw_score))
            
            game_data[game_id]["match_types"].add(chunk_type)

        if not game_data:
            return {"results": [], "mode_used": mode}

        # 4. Фаза 2: Re-ranking - Применяем "Золотую формулу"
        final_game_scores = {}

        for game_id, data in game_data.items():
            # Компонент A: Оценка по summary
            # Берем максимальную оценку, если summary нашлось несколько (хотя обычно одно)
            summary_score = max(data["summary_scores"] or [0])

            # Компонент B: Оценка по тексту с затуханием
            text_score = 0
            # Сортируем очки текстовых чанков по убыванию
            sorted_text_scores = sorted(data["text_scores"], reverse=True)
            # Применяем взвешенную сумму с затуханием
            for i, score in enumerate(sorted_text_scores):
                text_score += score * (DECAY_FACTOR ** i)
            
            # Нормализация text_score, чтобы он не "взорвался" на длинных играх
            # Используем гиперболический тангенс - он плавно сжимает любое число в диапазон [-1, 1]
            # (в нашем случае, т.к. text_score > 0, диапазон будет [0, 1))
            # Это не даст игре с 1000 упоминаний получить в 100 раз больше очков, чем игре с 10.
            normalized_text_score = math.tanh(text_score / len(sorted_text_scores)) if sorted_text_scores else 0

            # Финальная формула!
            final_score = (summary_score * SUMMARY_WEIGHT) + (normalized_text_score * TEXT_WEIGHT)
            
            final_game_scores[game_id] = {
                "score": final_score,
                # Определяем лучший тип совпадения для отображения в UI
                "match_type": "summary" if summary_score > 0 else "text"
            }
            
        # 5. Сортировка и выбор топ-результатов (теперь по final_score)
        sorted_games = sorted(final_game_scores.items(), key=lambda item: item[1]["score"], reverse=True)
        top_games = sorted_games[:20]
        top_game_ids = [g_id for g_id, data in top_games]

        if not top_game_ids:
            return {"results": [], "mode_used": mode}

        # 6. Получение метаданных из БД и формирование ответа (этот блок почти без изменений)
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        placeholders = ','.join('?' * len(top_game_ids))
        sql = f"SELECT pocketbase_id, title, summary FROM games WHERE pocketbase_id IN ({placeholders})"
        cursor.execute(sql, top_game_ids)
        rows = cursor.fetchall()
        conn.close()

        game_meta_map = {row[0]: (row[1], row[2]) for row in rows}
        
        # Строим ответ, сохраняя новый порядок сортировки
        results = []
        for game_id, score_data in top_games:
            if game_id in game_meta_map:
                title, summary = game_meta_map[game_id]
                summary_snippet = (summary[:200] + "...") if summary else ""
                
                # Нормализуем наш кастомный скор (который в диапазоне ~0-1) к 100-бальной шкале
                display_score = min(int(score_data["score"] * 100), 100)

                results.append({
                    "id": game_id,
                    "title": title,
                    "url": f"{BASE_GAME_URL}{game_id}",
                    "score": display_score,
                    "match_type": score_data["match_type"],
                    "snippet": summary_snippet
                })

        return {"results": results, "mode_used": mode}

    except Exception as e:
        print(f"Search Error: {e}")
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