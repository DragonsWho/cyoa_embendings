# manage.py
import os
import subprocess
import sys

# --- Импорты ---
from sync_with_pocketbase import sync_games
from fetch_game_text import main as fetch_texts
from process_static_cyoa import process_static_games # <--- Подключили OCR
from generate_summary import run_summary_generation
from indexer import main as run_indexer
from clear_database import clear_all_games
from reset_index_status import reset_all_statuses

def print_menu():
    print("\n" + "="*40)
    print("     CYOA SEARCH MANAGER v2.0     ")
    print("="*40)
    print(" 1. Синхронизация (PocketBase -> DB)")
    print(" 2. Скачать текст (Selenium / HTML)")
    print(" 3. Распознать текст с картинок (Google OCR) [Нужен gcp-credentials.json]")
    print(" 4. Сгенерировать AI описания (Summaries)")
    print(" 5. Индексация (Faiss) - Только новые")
    print(" 5a. Индексация (Faiss) - ПОЛНАЯ ПЕРЕСБОРКА")
    print("-" * 40)
    print(" 9. [AUTO] ПОЛНЫЙ ПАЙПЛАЙН (Шаги 1->2->3->4->5)")
    print("-" * 40)
    print(" S. Запустить сервер (Start Server)")
    print(" R. Сбросить статус индексации (Reset Status)")
    print(" C. Очистить базу данных (Clear DB)")
    print(" 0. Выход")
    print("="*40)

def run_server():
    subprocess.run([sys.executable, "-m", "uvicorn", "main:app", "--reload", "--port", "8100"])

def main():
    while True:
        print_menu()
        choice = input("Выбор: ").strip().upper()

        if choice == '1': sync_games()
        elif choice == '2': fetch_texts()
        elif choice == '3': process_static_games()
        elif choice == '4': run_summary_generation()
        elif choice == '5': run_indexer(full_reindex=False)
        elif choice == '5A': run_indexer(full_reindex=True)
        
        elif choice == '9':
            print("\n🚀 ЗАПУСК ПОЛНОГО ЦИКЛА ОБНОВЛЕНИЯ...")
            sync_games()
            fetch_texts()
            process_static_games()
            run_summary_generation()
            run_indexer(full_reindex=False)
            print("\n✅ Полный цикл завершен!")

        elif choice == 'S': run_server()
        elif choice == 'R': reset_all_statuses()
        elif choice == 'C': clear_all_games()
        elif choice == '0': break
        else: print("Неверный ввод.")
        
        if choice != 'S': input("\nНажмите Enter...")

if __name__ == "__main__":
    main()