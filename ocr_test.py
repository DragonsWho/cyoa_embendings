import os
from dotenv import load_dotenv
from google.cloud import vision

def recognize_cyoa_text(image_path: str):
    """
    Отправляет изображение в Google Cloud Vision API и возвращает распознанный текст.
    Использует режим распознавания текста в документах (DOCUMENT_TEXT_DETECTION),
    который лучше всего подходит для CYOA с плотным текстом.
    """
    # Загружаем переменные окружения (включая путь к ключу аутентификации)
    load_dotenv()

    try:
        # Убедимся, что файл изображения существует
        if not os.path.exists(image_path):
            print(f"Ошибка: Файл изображения не найден по пути: {image_path}")
            return

        # Инициализируем клиент Vision API
        # Библиотека автоматически использует учетные данные из переменной
        # окружения GOOGLE_APPLICATION_CREDENTIALS
        client = vision.ImageAnnotatorClient()

        print(f"Отправляем '{image_path}' на распознавание...")

        # Читаем файл изображения в бинарном режиме
        with open(image_path, "rb") as image_file:
            content = image_file.read()

        # Готовим объект изображения для API
        image = vision.Image(content=content)

        # Выполняем запрос на распознавание текста
        # DOCUMENT_TEXT_DETECTION лучше подходит для плотного текста, как в CYOA
        response = client.document_text_detection(image=image)

        if response.error.message:
            raise Exception(
                f"Ошибка API: {response.error.message}\n"
                "Проверьте, включен ли Vision API в вашем проекте Google Cloud "
                "и правильно ли настроены права у сервисного аккаунта."
            )

        if response.full_text_annotation:
            print("\n--- РАСПОЗНАННЫЙ ТЕКСТ ---")
            print(response.full_text_annotation.text)
            print("---------------------------\n")
            return response.full_text_annotation.text
        else:
            print("Текст на изображении не был распознан.")
            return None

    except Exception as e:
        print(f"\nПроизошла критическая ошибка: {e}")
        print("Убедитесь, что у вас установлен пакет 'google-cloud-vision' и настроен файл .env")


if __name__ == "__main__":
    # Укажите здесь имя вашего тестового файла
    IMAGE_FILE = "cyoa_test.jpg"
    recognize_cyoa_text(IMAGE_FILE)