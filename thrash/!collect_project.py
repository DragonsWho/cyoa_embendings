import os

# --- НАСТРОЙКИ ---
OUTPUT_FILE = "FULL_PROJECT_DUMP.txt"

# Папки, которые мы ПОЛНОСТЬЮ пропускаем
IGNORE_DIRS = {
    'venv', 
    '__pycache__', 
    '.git', 
    '.idea', 
    '.vscode',
    'OTHER',                 # Папка с мусором
    'semantic-search-deploy' # Старая папка деплоя
}

# Файлы, которые мы точно НЕ читаем (секреты, базы, большие данные)
IGNORE_FILES = {
    '.env',                  # СЕКРЕТЫ
    'gcp-credentials.json',  # СЕКРЕТЫ
    'games.db',              # База данных
    'games.index',           # Индекс Faiss (бинарный)
    'chunk_map.json',        # Карта чанков (слишком большая)
    'search_debug.log',      # Логи
    'user_queries.jsonl',    # Логи запросов
    OUTPUT_FILE,             # Сам этот файл
    'collect_project.py',    # Сам скрипт
    '.DS_Store'
}

# Расширения файлов, которые мы хотим прочитать (код и текст)
ALLOWED_EXTENSIONS = {
    '.py', '.txt', '.md', '.sh', 
    '.html', '.css', '.js', 
    '.json', '.xml', '.yaml', '.yml'
}

def is_ignored(path, names):
    """Фильтр для os.walk, чтобы пропускать ненужные папки"""
    return {n for n in names if n in IGNORE_DIRS}

def generate_tree(startpath):
    """Генерирует красивое дерево каталогов для заголовка"""
    tree_str = "PROJECT STRUCTURE:\n"
    for root, dirs, files in os.walk(startpath):
        # Фильтрация папок "на лету"
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        
        level = root.replace(startpath, '').count(os.sep)
        indent = ' ' * 4 * (level)
        tree_str += f"{indent}{os.path.basename(root)}/\n"
        subindent = ' ' * 4 * (level + 1)
        for f in files:
            if f not in IGNORE_FILES:
                tree_str += f"{subindent}{f}\n"
    return tree_str

def main():
    print(f"Start collecting project files into {OUTPUT_FILE}...")
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as outfile:
        # 1. Записываем структуру папок
        outfile.write("="*60 + "\n")
        outfile.write(generate_tree("."))
        outfile.write("="*60 + "\n\n")

        # 2. Проходим по файлам и читаем содержимое
        for root, dirs, files in os.walk("."):
            # Фильтрация папок
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

            for file in files:
                if file in IGNORE_FILES:
                    continue
                
                # Проверка расширения
                _, ext = os.path.splitext(file)
                if ext.lower() not in ALLOWED_EXTENSIONS:
                    continue

                file_path = os.path.join(root, file)
                
                # Красивый разделитель
                outfile.write(f"\n\n{'='*60}\n")
                outfile.write(f"FILE PATH: {file_path}\n")
                outfile.write(f"{'='*60}\n")

                try:
                    with open(file_path, 'r', encoding='utf-8', errors='replace') as infile:
                        content = infile.read()
                        outfile.write(content)
                except Exception as e:
                    outfile.write(f"\n[ERROR READING FILE: {e}]\n")

    print(f"Done! File saved as: {OUTPUT_FILE}")
    print("⚠️  PLEASE CHECK THE FILE BEFORE SENDING TO ENSURE NO SECRETS ARE INSIDE! ⚠️")

if __name__ == "__main__":
    main()