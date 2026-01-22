import os
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class BotConfig:
    token: str
    managers_json: str
    designer_catalogs: List[str]
    designer_panel_sizes: List[str]
    background_catalogs: List[str]
    background_materials: List[str]
    background_heights_velour: List[int]
    background_heights_colore: List[int]
    freski_materials: List[str]
    delivery_default_city: str
    admin_ids: List[int]
    forward_to_admins: bool


def load_config() -> BotConfig:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is required")

    managers_json = os.getenv("MANAGERS_JSON", "app/managers.json")

    # Данные из questions.json - designer_wallpapers
    designer_catalogs = [
        "Labirint",
        "Wallpaper I",
        "Wallpaper II",
        "Wallpaper III",
        "Favorite Art",
        "Line Art",
        "Emotion Art",
        "Fantasy",
        "Fluid",
        "Rio",
        "Atmosphere",
        "Exclusive",
        "Сказки Affresco",
        "Fine Art",
        "Trend Art",
        "New Art",
        "Re-Space",
        "Art Fabric",
    ]

    designer_panel_sizes = [
        "10.0 x 20.0",
        "12.0 x 20",
        "15.0 x 30.0",
    ]

    # Данные из questions.json - background_wallpapers
    background_catalogs = [
        "Dream Forest",
        "Exclusive",
        "Affresco Colore",
        "Botanika",
        "Ethno",
    ]

    background_materials = ["Велюр", "Колоре"]

    background_heights_velour = [200, 220, 240, 260, 280, 300, 315]
    background_heights_colore = [220, 240, 260, 280, 300]

    # Данные из questions.json - freski
    freski_materials = [
        "Велюр",
        "Сатин",
        "Саванна",
        "Безе",
        "Велатура",
        "Саббия",
        "Саббия Фасад",
        "Пиетра",
        "Кракелюр средняя степень",
        "Кракелюр без старения",
        "Фабриз X",
        "Фабриз Y",
        "Колоре",
        "Колоре Лайт",
    ]

    # Данные из questions.json - delivery
    delivery_default_city = "Нижний Новгород"

    # Админы
    admin_ids_str = os.getenv("ADMIN_IDS", "").strip()
    admin_ids = []
    if admin_ids_str:
        try:
            # Разделяем по запятой и обрабатываем каждый ID
            parts = admin_ids_str.split(",")
            for part in parts:
                part = part.strip()
                if part:
                    admin_ids.append(int(part))
        except ValueError as e:
            import logging
            logging.error(f"Error parsing ADMIN_IDS: {e}, value: {admin_ids_str}")
            admin_ids = []
    
    import logging
    logging.info(f"Loaded admin_ids: {admin_ids} from ADMIN_IDS='{admin_ids_str}'")

    # Пересылка заявок админам
    forward_to_admins = os.getenv("FORWARD_TO_ADMINS", "true").strip().lower() in ("true", "1", "yes")

    return BotConfig(
        token=token,
        managers_json=managers_json,
        designer_catalogs=designer_catalogs,
        designer_panel_sizes=designer_panel_sizes,
        background_catalogs=background_catalogs,
        background_materials=background_materials,
        background_heights_velour=background_heights_velour,
        background_heights_colore=background_heights_colore,
        freski_materials=freski_materials,
        delivery_default_city=delivery_default_city,
        admin_ids=admin_ids,
        forward_to_admins=forward_to_admins,
    )

