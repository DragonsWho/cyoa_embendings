# add_missing_columns.py
import sqlite3

DB_FILE = "games.db"

def run_migration():
    """
    Добавляет недостающие колонки в таблицу 'games', если они не существуют.
    """
    print(f"Проверяем и обновляем схему базы данных '{DB_FILE}'...")
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Список колонок, которые мы хотим добавить.
    # Формат: (имя_колонки, тип_данных_и_параметры)
    columns_to_add = [
        ('summary', 'TEXT'),
        ('source_hash', 'TEXT'),
        ('last_indexed_at', 'TIMESTAMP'),
        ('is_indexed', 'BOOLEAN DEFAULT 0') 
        # DEFAULT 0 - очень важно, чтобы все старые записи считались необработанными
    ]
    
    added_count = 0
    for column_name, column_definition in columns_to_add:
        try:
            cursor.execute(f'ALTER TABLE games ADD COLUMN {column_name} {column_definition}')
            print(f"  [OK] Колонка '{column_name}' успешно добавлена.")
            added_count += 1
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print(f"  [INFO] Колонка '{column_name}' уже существует.")
            else:
                print(f"  [ERROR] Произошла ошибка SQLite при добавлении '{column_name}': {e}")

    conn.commit()
    conn.close()
    
    print("-" * 20)
    if added_count > 0:
        print(f"Схема базы данных успешно обновлена. Добавлено {added_count} новых колонок.")
    else:
        print("Схема базы данных уже в актуальном состоянии.")

if __name__ == "__main__":
    run_migration()