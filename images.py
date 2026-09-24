import os
import re
import random
from typing import Optional, Tuple
from aiogram import types
from aiogram.types import FSInputFile

# Базовая папка с изображениями
IMAGES_DIR = "images"

# Разрешённые форматы
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# Маппинг категорий на папки (можно расширять)
CATEGORY_FOLDERS = {
    "congratulations": "congratulations",
    "support": "support",
    "cute": "cute",
    "memes": "memes",
    "thinking": "thinking",
}

# Регулярка для маркера [IMAGE:category] или [IMAGE:category|caption]
IMAGE_MARKER_PATTERN = re.compile(
    r'\[IMAGE:\s*([a-zA-Zа-яА-Я_-]+)(?:\|([^\]]+))?\]',
    re.IGNORECASE
)


def extract_image_marker(text: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Извлекает маркер изображения из текста.
    Возвращает: (очищенный текст, категория, подпись/капшн или None)
    """
    match = IMAGE_MARKER_PATTERN.search(text)
    if match:
        category = match.group(1).lower().strip()
        caption = match.group(2)
        if caption:
            caption = caption.strip()
        clean_text = IMAGE_MARKER_PATTERN.sub('', text).strip()
        return clean_text, category, caption
    return text, None, None


def pick_random_image(category: str) -> Optional[str]:
    """
    Берёт случайное изображение из папки категории.
    Возвращает путь к файлу или None, если ничего не найдено.
    """
    folder_name = CATEGORY_FOLDERS.get(category)
    if not folder_name:
        print(f"[Image] Неизвестная категория: {category}")
        return None

    folder_path = os.path.join(IMAGES_DIR, folder_name)
    if not os.path.isdir(folder_path):
        print(f"[Image] Папка не найдена: {folder_path}")
        return None

    # Собираем все подходящие файлы
    files = [
        f for f in os.listdir(folder_path)
        if os.path.isfile(os.path.join(folder_path, f))
           and os.path.splitext(f)[1].lower() in ALLOWED_EXTENSIONS
    ]

    if not files:
        print(f"[Image] Папка '{folder_name}' пуста")
        return None

    chosen = random.choice(files)
    return os.path.join(folder_path, chosen)


async def send_image_from_category(
        message: types.Message,
        category: str,
        caption: Optional[str] = None
) -> bool:
    """
    Отправляет случайное изображение из указанной категории.
    Возвращает True, если изображение было отправлено.
    """
    image_path = pick_random_image(category)
    if not image_path:
        return False

    try:
        photo = FSInputFile(image_path)
        await message.answer_photo(photo, caption=caption)
        print(f"[Image] Отправлено: {image_path}")
        return True
    except Exception as e:
        print(f"[Image] Ошибка отправки {image_path}: {e}")
        return False