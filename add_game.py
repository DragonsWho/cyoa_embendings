# add_game.py
import sqlite3
import sys

DB_FILE = "games.db"

def add_new_game():
    """Интерактивно добавляет новую игру в базу данных."""
    try:
        # Запрашиваем название игры
        title = input("Введите название игры: ")
        if not title:
            print("Название не может быть пустым.")
            return

        # Запрашиваем многострочное описание
        print("Введите полное описание игры. По завершении нажмите Ctrl+D (Linux/macOS) или Ctrl+Z и Enter (Windows).")
        description = sys.stdin.read().strip()
        if not description:
            print("Описание не может быть пустым.")
            return
            
        # Подключаемся к базе и добавляем запись
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute("INSERT INTO games (title, description) VALUES (?, ?)", (title, description))
        
        conn.commit()
        conn.close()
        
        print(f"\nИгра '{title}' успешно добавлена в базу данных!")
        print("Не забудьте запустить 'python indexer.py', чтобы обновить поисковый индекс.")

    except KeyboardInterrupt:
        print("\nОперация отменена.")
    except Exception as e:
        print(f"\nПроизошла ошибка: {e}")

if __name__ == "__main__":
    add_new_game()