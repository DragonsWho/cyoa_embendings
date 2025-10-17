# fetch_game_text.py (финальная, исправленная версия)
import os
import re
import json
import sqlite3
import time
import requests
from urllib.parse import urljoin
from tqdm import tqdm
import chardet

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

# --- Конфигурация ---
DB_FILE = "games.db"

# --- Функция json_to_text остается без изменений ---
def json_to_text(data):
    # ... (код этой функции не меняется)
    texts = []
    if not isinstance(data, dict): return ""
    if 'rows' in data:
        for row in data.get('rows', []):
            if isinstance(row, dict):
                if row.get('titleText'): texts.append(row['titleText'])
                for obj in row.get('objects', []):
                     if isinstance(obj, dict) and obj.get('text'): texts.append(obj['text'])
    elif 'sections' in data:
        for section in data.get('sections', []):
            if isinstance(section, dict):
                if section.get('title'): texts.append(section['title'])
                if section.get('text'): texts.append(section['text'])
    elif 'content' in data:
         texts.append(data.get('content', ''))
    return "\n\n".join(filter(None, texts))

# --- Класс GameTextFetcher остается почти без изменений ---
class GameTextFetcher: 
    def __init__(self):
        self.session = requests.Session()
        self.driver = None
        self.js_json_pattern = re.compile(r'Store\(\{state:\{app:(.*?)\},getters:', re.DOTALL)
    def _init_driver(self):
        if self.driver is None:
            print("    Инициализация headless-браузера (Selenium)...")
            options = Options()
            options.add_argument('--headless'); options.add_argument('--disable-gpu'); options.add_argument('--log-level=3')
            options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
            try:
                self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            except Exception as e:
                print(f"    КРИТИЧЕСКАЯ ОШИБКА: Не удалось запустить WebDriver: {e}"); raise
    def _try_direct_project_json(self, base_url):
        """Стратегия 1: Пытается напрямую скачать project.json с автоопределением кодировки."""
        project_url = urljoin(base_url, 'project.json')
        try:
            with self.session.get(project_url, timeout=60, stream=True) as response:
                if response.status_code == 200:
                    content_length = response.headers.get('content-length')
                    size_info = f"({int(content_length) / 1024 / 1024:.2f} MB)" if content_length else ""
                    print(f"    [OK] Найден project.json. Начинаем загрузку {size_info}...")
                    
                    content = response.content
                    
                    # --- ГЛАВНОЕ ИЗМЕНЕНИЕ ---
                    # 1. Определяем кодировку с помощью chardet
                    detected_encoding = chardet.detect(content)['encoding']
                    if not detected_encoding:
                        detected_encoding = 'utf-8' # Запасной вариант
                    print(f"    [INFO] Обнаружена кодировка: {detected_encoding}")
                    
                    # 2. Декодируем байты в строку с правильной кодировкой
                    text_content = content.decode(detected_encoding, errors='replace')
                    
                    # 3. Парсим уже строку, а не байты
                    json_data = json.loads(text_content)
                    
                    print(f"    [OK] project.json успешно загружен и распарсен.")
                    return json_data
        except requests.exceptions.Timeout:
            print(f"    [FAIL] Таймаут при скачивании {project_url}."); return None
        except requests.RequestException as e:
            print(f"    [INFO] Запрос к project.json не удался (возможно, его нет): {e.__class__.__name__}"); return None
        except json.JSONDecodeError:
            print(f"    [FAIL] Файл project.json скачан, но содержит некорректный JSON."); return None
        except UnicodeDecodeError as e:
            print(f"    [FAIL] Ошибка декодирования файла, даже после chardet: {e}")
            return None
        return None
    def _try_selenium_extraction(self, game_url):
        self._init_driver()
        self.driver.get(game_url)
        time.sleep(7)
        logs = self.driver.get_log('performance')
        json_urls, js_urls = set(), set()
        for log in logs:
            try:
                message = json.loads(log['message'])['message']
                if message['method'] == 'Network.responseReceived':
                    url = message['params']['response']['url']
                    if url.endswith('.json'): json_urls.add(url)
                    elif url.endswith('.js'): js_urls.add(url)
            except (KeyError, json.JSONDecodeError): continue
        if json_urls:
            print(f"    [INFO] Анализ трафика: найдено {len(json_urls)} JSON-файлов.")
            for url in json_urls:
                try:
                    response = self.session.get(url, timeout=30)
                    if response.status_code == 200:
                        print(f"    [OK] Успешно скачан JSON из трафика: {os.path.basename(url)}"); return response.json()
                except requests.RequestException: continue
        if js_urls:
            print(f"    [INFO] Глубокий анализ: найдено {len(js_urls)} JS-файлов.")
            for url in js_urls:
                try:
                    response = self.session.get(url, timeout=30)
                    if response.status_code != 200: continue
                    match = self.js_json_pattern.search(response.text)
                    if match:
                        json_str = match.group(1).strip()
                        print(f"    [OK] Найдены встроенные данные в JS-файле: {os.path.basename(url)}"); return json.loads(json_str)
                except (requests.RequestException, json.JSONDecodeError): continue
        return None
    def fetch(self, game_url):
        if game_url.endswith('index.html'): game_url = game_url[:-10]
        print("  - Попытка 1: Прямой запрос к project.json...")
        json_data = self._try_direct_project_json(game_url)
        if json_data:
            text = json_to_text(json_data)
            if text: print("    [SUCCESS] Текст успешно извлечен из project.json!"); return text
            else: print("    [WARN] project.json найден, но не содержит текста. Переходим к анализу страницы...")
        print("  - Попытка 2: Анализ страницы через Selenium...")
        try:
            json_data_selenium = self._try_selenium_extraction(game_url)
            if json_data_selenium:
                text = json_to_text(json_data_selenium)
                if text: print("    [SUCCESS] Текст успешно извлечен со страницы!"); return text
                else: print("    [WARN] Данные со страницы получены, но не содержат текста.")
        except Exception as e:
            print(f"    [ERROR] Ошибка при анализе Selenium: {e}"); return None
        print("    [FAIL] Не удалось извлечь текст ни одним из методов."); return None
    def close(self):
        if self.driver: print("Закрытие headless-браузера..."); self.driver.quit(); self.driver = None


def main():
    """
    Основной процесс: найти игры без текста и запустить для них Fetcher.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # ИЗМЕНЕНИЕ: Теперь мы выбираем и original_url
    cursor.execute("SELECT pocketbase_id, title, original_url FROM games WHERE full_text IS NULL OR full_text = ''")
    games_to_process = cursor.fetchall()

    if not games_to_process:
        print("Все игры уже имеют текст. Нечего обрабатывать.")
        conn.close()
        return

    print(f"Найдено {len(games_to_process)} игр для извлечения текста.")
    
    fetcher = GameTextFetcher()
    success_count = 0
    fail_count = 0
    
    try:
        # ИЗМЕНЕНИЕ: В цикле теперь есть и original_url
        for pb_id, title, original_url in tqdm(games_to_process, desc="Обработка игр"):
            
            # ИЗМЕНЕНИЕ: Главная проверка. Если URL нет, мы не можем ничего сделать.
            try:
                if not original_url:
                    tqdm.write(f"\n-> [SKIP] Пропуск '{title}', так как отсутствует URL оригинала.")
                    fail_count += 1
                    continue

                tqdm.write(f"\n-> Обработка: '{title}' ({original_url})")
                
                text_content = fetcher.fetch(original_url)

                if text_content:
                    cursor.execute(
                        "UPDATE games SET full_text = ? WHERE pocketbase_id = ?",
                        (text_content, pb_id)
                    )
                    conn.commit()
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                # Логируем ошибку, но продолжаем работу
                tqdm.write(f"\n!!! КРИТИЧЕСКАЯ ОШИБКА при обработке '{title}': {e}")
                fail_count += 1
                continue # Переходим к следующей игре

    finally:
        fetcher.close()
        conn.close()
        print("\n--- Отчет ---")
        print(f"Успешно обработано: {success_count}")
        print(f"Не удалось/пропущено: {fail_count}")
        print("Процесс завершен. Теперь можно запустить indexer.py для обновления поискового индекса.")


if __name__ == "__main__":
    main()