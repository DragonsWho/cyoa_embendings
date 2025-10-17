#!/bin/bash

# Файл, в который будет собран проект
OUTPUT_FILE="project_bundle.txt"
# Директории и файлы, которые нужно исключить (добавьте свои)
EXCLUDE_PATTERNS=("./.git/*" "./node_modules/*" "./dist/*" "./venv/*" "*.log")

# Создаем или очищаем выходной файл
> "$OUTPUT_FILE"

# Сначала добавим структуру проекта с помощью 'tree' (если установлено)
if command -v tree &> /dev/null
then
    echo "Project Structure:" >> "$OUTPUT_FILE"
    tree -a -I '.git|node_modules|dist|venv' >> "$OUTPUT_FILE"
    echo -e "\n\n============================================\n\n" >> "$OUTPUT_FILE"
fi

# Собираем параметры исключения для команды find
EXCLUDE_ARGS=()
for pattern in "${EXCLUDE_PATTERNS[@]}"; do
    EXCLUDE_ARGS+=(-not -path "$pattern")
done

# Находим все файлы, исключая ненужные, и добавляем их в один файл
find . -type f "${EXCLUDE_ARGS[@]}" | while read -r file; do
    if [[ -s "$file" ]]; then # Проверяем, что файл не пустой
        echo "--- FILE: $file ---" >> "$OUTPUT_FILE"
        cat "$file" >> "$OUTPUT_FILE"
        echo -e "\n\n" >> "$OUTPUT_FILE"
    fi
done

echo "Проект успешно собран в файл: $OUTPUT_FILE"