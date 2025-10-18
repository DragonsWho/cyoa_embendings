# manage.py
import os
import subprocess
import sys

# --- Импортируем основные функции из других скриптов ---
from sync_with_pocketbase import sync_games
from fetch_game_text import main as fetch_texts
from generate_summary import run_summary_generation
from indexer import main as run_indexer
from clear_database import clear_all_games
from reset_index_status import reset_all_statuses


def print_menu():
    """Выводит красивое меню в консоль."""
    print("\n" + "="*40)
    print("     Интерактивный менеджер проекта CYOA     ")
    print("="*40)
    print("\n--- Основной пайплайн ---")
    print(" 1. Синхронизировать игры с PocketBase")
    print(" 2. Извлечь текст из игр (интерактивных и статичных)")
    print(" 3. Сгенерировать описания (summaries) для игр с текстом")
    print(" 4. Индексировать НОВЫЕ игры (инкрементальное обновление)")
    print(" 4a. [ДОЛГО] Полностью переиндексировать ВСЕ игры")
    print(" 5. [ВСЁ СРАЗУ] Выполнить полный пайплайн (шаги 1-4)")
    
    print("\n--- Веб-сервер ---")
    print(" 6. Запустить веб-сервер API (FastAPI)")

    print("\n--- Утилиты и обслуживание ---")
    print(" 7. Сбросить статус индексации для всех игр")
    print(" 8. [ОПАСНО] Очистить всю базу данных (удалить все игры)")

    print("\n 0. Выход")
    print("-"*40)


def run_server():
    """Запускает FastAPI сервер с помощью uvicorn."""
    print("\n--- Запуск веб-сервера FastAPI ---")
    print("Сервер будет доступен по адресу: http://127.0.0.1:8000")
    print("Для остановки сервера нажмите CTRL+C.")
    try:
        # Используем subprocess для запуска uvicorn, чтобы он корректно работал
        # в разных окружениях и правильно обрабатывал перезагрузку.
        subprocess.run([sys.executable, "-m", "uvicorn", "main:app", "--reload"])
    except KeyboardInterrupt:
        print("\nСервер остановлен.")
    except FileNotFoundError:
        print("\n[ОШИБКА] Команда 'uvicorn' не найдена.")
        print("Пожалуйста, убедитесь, что uvicorn установлен: pip install uvicorn")


def main():
    """Главный цикл для отображения меню и обработки выбора пользователя."""
    while True:
        print_menu()
        choice = input("Введите номер действия: ")

        if choice == '1':
            sync_games()
        elif choice == '2':
            fetch_texts()
        elif choice == '3':
            # Запускаем с настройками по умолчанию
            run_summary_generation()
        elif choice == '4':
            # Инкрементальная индексация (по умолчанию)
            run_indexer(full_reindex=False)
        elif choice == '4a':
            # Полная переиндексация
            print("\n--- Запуск ПОЛНОЙ переиндексации ---")
            run_indexer(full_reindex=True)
        elif choice == '5':
            print("\n--- Запуск полного пайплайна обработки ---")
            sync_games()
            print("\n--- Следующий шаг: извлечение текста ---")
            fetch_texts()
            print("\n--- Следующий шаг: генерация описаний ---")
            run_summary_generation()
            print("\n--- Финальный шаг: инкрементальная индексация ---")
            run_indexer(full_reindex=False)
            print("\n--- Полный пайплайн завершен! ---")
        elif choice == '6':
            run_server()
        elif choice == '7':
            reset_all_statuses()
        elif choice == '8':
            clear_all_games()
        elif choice == '0':
            print("Выход из программы.")
            break
        else:
            print("\n[!] Неверный ввод. Пожалуйста, выберите номер из меню.")
        
        input("\nНажмите Enter для продолжения...")


if __name__ == "__main__":
    # Проверяем, что все нужные файлы существуют в текущей директории
    required_files = [
        'sync_with_pocketbase.py', 'fetch_game_text.py', 'generate_summary.py',
        'indexer.py', 'main.py', 'clear_database.py', 'reset_index_status.py'
    ]
    missing_files = [f for f in required_files if not os.path.exists(f)]
    if missing_files:
        print("[КРИТИЧЕСКАЯ ОШИБКА] Не найдены необходимые файлы скриптов:")
        for f in missing_files:
            print(f" - {f}")
        sys.exit(1)

    main()