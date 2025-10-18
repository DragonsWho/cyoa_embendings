# reset_index_status.py
import sqlite3
import os
import config

def reset_all_statuses():
    """
    Сбрасывает статус индексации для ВСЕХ игр в базе данных,
    устанавливая last_indexed_at в NULL.
    Это заставит indexer.py переобработать их при следующем запуске.
    """
    if not os.path.exists(config.DB_FILE):
        print(f"Файл базы данных '{config.DB_FILE}' не найден. Нечего сбрасывать.")
        return

    try:
        conn = sqlite3.connect(config.DB_FILE)
        cursor = conn.cursor()

        # Получаем количество записей перед обновлением
        cursor.execute("SELECT COUNT(*) FROM games WHERE last_indexed_at IS NOT NULL")
        count_before = cursor.fetchone()[0]

        if count_before == 0:
            print("Все игры в базе уже готовы к переиндексации (статус сброшен).")
            conn.close()
            return
            
        print(f"Найдено {count_before} игр с отметкой об индексации.")
        confirm = input(f"Вы уверены, что хотите сбросить статус для этих игр? (y/n): ")
        
        if confirm.lower() == 'y':
            print("Сброс статусов индексации...")
            # Главная команда: установить last_indexed_at в NULL для всех записей
            cursor.execute("UPDATE games SET last_indexed_at = NULL")
            
            conn.commit()
            print(f"Статус для {cursor.rowcount} игр был успешно сброшен.")
            print("Теперь при следующем запуске `indexer.py` попытается обработать их все заново.")
        else:
            print("Операция отменена.")

        conn.close()
        
    except Exception as e:
        print(f"Произошла ошибка: {e}")

if __name__ == "__main__":
    reset_all_statuses()