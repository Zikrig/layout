import os
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class BotConfig:
    token: str
    managers_json: str
    texts_json: str
    freski_catalogs: List[str]
    freski_library_catalogs: List[str]
    designer_catalogs: List[str]
    designer_panel_sizes: List[str]
    background_catalogs: List[str]
    background_materials: List[str]
    background_heights_velour: List[int]
    background_heights_colore: List[int]
    freski_materials: List[str]
    delivery_carriers: List[str]
    delivery_default_city: str
    admin_ids: List[int]
    forward_to_admins: bool


def load_config() -> BotConfig:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is required")

    managers_json = os.getenv("MANAGERS_JSON", "app/managers.json")
    texts_json = os.getenv("TEXTS_JSON", "app/texts.json")

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

    freski_catalogs = [
        "Библиотека Affresco",
        "Индивидуальная отрисовка",
    ]
    freski_library_catalogs = [
        *designer_catalogs,
        "Фрески фотообои",
    ]

    designer_panel_sizes = [
        "67 x 200",
        "73 x 220",
        "80 x 240",
        "87 x 260",
        "93 x 280",
        "100 x 300",
        "105 x 315",
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
        "Кракелюр",
        "Фабриз X",
        "Фабриз Y",
        "Колоре",
        "Колоре Лайт",
    ]

    delivery_carriers = [
        "Курьерская Москва",
        "Самовывоз",
        "БайкалСервис",
        "ВЕРА-1",
        "Глобал логистик",
        "Деловые линии",
        "Диком",
        "Мегатранссервис",
        "Мейджик Транс",
        "Новая линия",
        "Пегас ТЭК",
        "ПЭК",
        "СДЭК",
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
        texts_json=texts_json,
        freski_catalogs=freski_catalogs,
        freski_library_catalogs=freski_library_catalogs,
        designer_catalogs=designer_catalogs,
        designer_panel_sizes=designer_panel_sizes,
        background_catalogs=background_catalogs,
        background_materials=background_materials,
        background_heights_velour=background_heights_velour,
        background_heights_colore=background_heights_colore,
        freski_materials=freski_materials,
        delivery_carriers=delivery_carriers,
        delivery_default_city=delivery_default_city,
        admin_ids=admin_ids,
        forward_to_admins=forward_to_admins,
    )

