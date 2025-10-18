# config.py

"""
Центральный файл конфигурации для всего проекта.
Все общие константы и параметры должны храниться здесь.
"""

# --- Пути к файлам ---
DB_FILE = "games.db"
INDEX_FILE = "games.index"
MAPPING_FILE = "chunk_map.json"
SUMMARY_PROMPT_FILE = "summary_prompt.txt"

# --- Логирование ---
DEBUG_LOGGING = False # Включает/выключает детальное логгирование в main.py
LOG_FILE = "search_debug.log"
QUERY_LOG_FILE = "user_queries.jsonl"

# --- Модели ---
EMBEDDING_MODEL_NAME = "gemini-embedding-001"
GENERATION_MODEL_NAME = "deepseek/deepseek-v3.2-exp"

# --- API и Сервисы ---
BASE_GAME_URL = "https://cyoa.cafe/game/"

# --- Параметры обработки и индексации ---
OUTPUT_DIMENSION = 256
BATCH_SIZE = 100
API_REQUEST_DELAY = 3 # Пауза в секундах между API запросами в indexer.py
MAX_RETRIES = 3

# --- Параметры ранжирования в main.py ---
SUMMARY_WEIGHT = 0.70 
TEXT_WEIGHT = 0.30    
DECAY_FACTOR = 0.85 