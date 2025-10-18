# clear_database.py
import sqlite3
import os
import config

def clear_all_games():
    """Удаляет все записи из таблицы 'games', не удаляя саму таблицу."""
    if not os.path.exists(config.DB_FILE):
        print(f"Файл базы данных '{config.DB_FILE}' не найден. Нечего очищать.")
        return

    try:
        conn = sqlite3.connect(config.DB_FILE)
        cursor = conn.cursor()

        # Получаем количество записей перед удалением
        cursor.execute("SELECT COUNT(*) FROM games")
        count_before = cursor.fetchone()[0]

        if count_before == 0:
            print("База данных уже пуста.")
            conn.close()
            return
            
        # Запрашиваем подтверждение у пользователя
        confirm = input(f"Вы уверены, что хотите удалить {count_before} игр из базы? Это действие необратимо. (y/n): ")
        
        if confirm.lower() == 'y':
            print("Удаление всех записей...")
            # Главная команда: удалить все из таблицы games
            cursor.execute("DELETE FROM games")
            # Сбрасываем счетчик автоинкремента, чтобы ID снова начинались с 1
            cursor.execute("DELETE FROM sqlite_sequence WHERE name='games'")
            conn.commit()
            print("Все игры были успешно удалены. База данных очищена.")
        else:
            print("Операция отменена.")

        conn.close()
        
    except Exception as e:
        print(f"Произошла ошибка: {e}")

if __name__ == "__main__":
    clear_all_games()