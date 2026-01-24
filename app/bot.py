import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import load_config


logging.basicConfig(level=logging.INFO)


class OrderFlow(StatesGroup):
    # Фрески
    ask_freski = State()
    freski_catalog = State()
    freski_article = State()
    freski_width = State()
    freski_height = State()
    freski_material = State()
    freski_humidity = State()
    freski_crackle_aging = State()
    freski_color_sample = State()
    freski_note = State()
    # Дизайнерские обои
    ask_designer_wallpapers = State()
    designer_catalog = State()
    designer_article = State()
    designer_panel_size = State()
    designer_panel_order = State()
    designer_production_type = State()
    designer_color_sample = State()
    designer_mirror = State()
    # Фоновые обои
    ask_background_wallpapers = State()
    background_material = State()
    background_catalog = State()
    background_article = State()
    background_height = State()
    background_width = State()
    background_color_sample = State()
    # Картины
    ask_paintings = State()
    paintings_article = State()
    paintings_canvas_width = State()
    paintings_canvas_height = State()
    paintings_visible_width = State()
    paintings_visible_height = State()
    # Доставка
    ask_delivery_needed = State()
    delivery_type = State()
    delivery_carrier = State()
    delivery_crate = State()
    # Финальные данные
    ask_legal_entity = State()
    ask_city = State()
    ask_phone = State()
    ask_email = State()
    ask_region = State()
    # Админские команды
    admin_edit_manager_region = State()
    admin_edit_manager_name = State()
    admin_edit_manager_chat_id = State()


@dataclass(frozen=True)
class ManagerInfo:
    name: str | None
    chat_id: int


def yes_no_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да", callback_data="yes"),
                InlineKeyboardButton(text="Нет", callback_data="no"),
            ]
        ]
    )


def list_kb(items: list[str], prefix: str = "item") -> InlineKeyboardMarkup:
    buttons = []
    for idx, item in enumerate(items):
        buttons.append([InlineKeyboardButton(text=item, callback_data=f"{prefix}:{idx}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def normalize_yes_no(text: str) -> str | None:
    value = text.strip().lower()
    if value in {"да", "yes", "y", "д"}:
        return "Да"
    if value in {"нет", "no", "n", "н"}:
        return "Нет"
    return None


def load_managers(path: str) -> dict[str, list[ManagerInfo]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    result: dict[str, list[ManagerInfo]] = {}

    if isinstance(raw, dict) and "regions" in raw:
        regions = raw["regions"]
    elif isinstance(raw, dict):
        regions = [{"region": k, "managers": v} for k, v in raw.items()]
    elif isinstance(raw, list):
        regions = raw
    else:
        raise ValueError("Unsupported managers.json format")

    for item in regions:
        region = str(item.get("region", "")).strip()
        if not region:
            continue
        managers = item.get("managers", [])
        normalized: list[ManagerInfo] = []
        for manager in managers:
            if isinstance(manager, dict):
                chat_id = int(manager.get("chat_id"))
                normalized.append(
                    ManagerInfo(
                        name=manager.get("name"),
                        chat_id=chat_id,
                    )
                )
            else:
                normalized.append(ManagerInfo(name=None, chat_id=int(manager)))
        result[region] = normalized
    return result


def save_managers(path: str, managers_map: dict[str, list[ManagerInfo]]) -> None:
    """Сохраняет менеджеров в JSON файл"""
    regions_list = []
    for region, managers_list in managers_map.items():
        managers_data = []
        for manager in managers_list:
            manager_dict = {"chat_id": manager.chat_id}
            if manager.name:
                manager_dict["name"] = manager.name
            managers_data.append(manager_dict)
        regions_list.append({"region": region, "managers": managers_data})
    
    data = {"regions": regions_list}
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def is_admin(user_id: int, admin_ids: list[int]) -> bool:
    """Проверяет, является ли пользователь админом"""
    return user_id in admin_ids


def safe_value(value: Any) -> str:
    if value is None:
        return "-"
    text = str(value).strip()
    return text if text else "-"


def format_user_summary(order: dict[str, Any]) -> str:
    """Форматирует заявку для пользователя - без tg id и без разделов 'Нет'"""
    legal_entity = order["client"].get("legal_entity", "-")
    city = order["client"].get("city", "-")
    phone = order["client"].get("phone", "-")
    email = order["client"].get("email", "-")
    region = order["client"].get("region", "-")

    lines = [
        f"Юрлицо: {legal_entity}",
        f"Город: {city}",
        f"Телефон: {phone}",
        f"Email: {email}",
        f"Регион доставки: {region}",
        "",
    ]

    # Фрески - только если enabled
    freski = order.get("freski", {})
    if freski.get("enabled"):
        size = freski.get("size_cm", {})
        lines.extend(
            [
                "ФРЕСКИ",
                f"Каталог: {safe_value(freski.get('catalog_name'))}",
                f"Артикул: {safe_value(freski.get('article'))}",
                f"Ширина, см: {safe_value(size.get('width'))}",
                f"Высота, см: {safe_value(size.get('height'))}",
                f"Материал: {safe_value(freski.get('material'))}",
                f"Цветопроба: {safe_value(freski.get('color_sample'))}",
                f"Гидроизоляция: {safe_value(freski.get('hydro_insulation'))}",
                f"Старение: {safe_value(freski.get('crackle_aging'))}",
                f"Примечание: {safe_value(freski.get('note'))}",
                "",
            ]
        )

    # Дизайнерские обои - только если enabled
    designer = order.get("designer_wallpapers", {})
    if designer.get("enabled"):
        color_sample = designer.get("color_sample", {})
        lines.extend(
            [
                "ДИЗАЙНЕРСКИЕ ОБОИ",
                f"Каталог: {safe_value(designer.get('catalog_name'))}",
                f"Артикул: {safe_value(designer.get('article'))}",
                f"Материал: Велюр",
                f"Размер панели: {safe_value(designer.get('panel_size_cm'))}",
                f"Порядок панелей: {safe_value(designer.get('panels_order_left_to_right'))}",
                f"Тип производства: {safe_value(designer.get('production_type'))}",
                f"Цветопроба нужна: {safe_value(color_sample.get('required'))}",
                f"Отзеркалить: {safe_value(designer.get('mirror'))}",
                "",
            ]
        )

    # Фоновые обои - только если enabled
    background = order.get("background_wallpapers", {})
    if background.get("enabled"):
        bg_color_sample = background.get("color_sample", {})
        bg_size = background.get("size_cm", {})
        lines.extend(
            [
                "ФОНОВЫЕ ОБОИ",
                f"Каталог: {safe_value(background.get('catalog_name'))}",
                f"Артикул: {safe_value(background.get('article'))}",
                f"Материал: {safe_value(background.get('material_type'))}",
                f"Ширина, см: {safe_value(bg_size.get('width'))}",
                f"Высота, см: {safe_value(bg_size.get('height'))}",
                f"Цветопроба нужна: {safe_value(bg_color_sample.get('required'))}",
                "",
            ]
        )

    # Картины - только если enabled
    paintings = order.get("paintings", {})
    if paintings.get("enabled"):
        canvas_size = paintings.get("canvas_total_size_cm", {})
        visible_size = paintings.get("visible_image_size_cm", {})
        lines.extend(
            [
                "КАРТИНЫ ИЗ КАТАЛОГА ФРЕСКИ И ИНДИВИДУАЛЬНЫЕ ИЗОБРАЖЕНИЯ",
                f"Материал: Итальянский холст",
                f"Макс. размер, см: 450 x 140",
                f"Артикул: {safe_value(paintings.get('article'))}",
                f"Полный размер холста, см:",
                f"  Ширина: {safe_value(canvas_size.get('width'))}",
                f"  Высота: {safe_value(canvas_size.get('height'))}",
                f"Видимый размер изображения, см:",
                f"  Ширина: {safe_value(visible_size.get('width'))}",
                f"  Высота: {safe_value(visible_size.get('height'))}",
                "",
            ]
        )

    delivery = order.get("delivery", {})
    if delivery.get("needed") is not None:
        lines.extend(
            [
                "ДОСТАВКА",
                f"Нужна: {safe_value(delivery.get('needed'))}",
                f"Тип: {safe_value(delivery.get('type'))}",
                f"ТК/Самовывоз: {safe_value(delivery.get('carrier'))}",
                f"Обрешетка: {safe_value(delivery.get('crate'))}",
                "",
            ]
        )

    return "\n".join(lines)


def format_summary(order: dict[str, Any]) -> str:
    tg = order["client"].get("telegram", "-")
    legal_entity = order["client"].get("legal_entity", "-")
    city = order["client"].get("city", "-")
    phone = order["client"].get("phone", "-")
    email = order["client"].get("email", "-")
    region = order["client"].get("region", "-")

    lines = [
        "Новая заявка",
        f"Пользователь: {tg}",
        f"Юрлицо: {legal_entity}",
        f"Город: {city}",
        f"Телефон: {phone}",
        f"Email: {email}",
        f"Регион доставки: {region}",
        "",
    ]

    # Фрески
    freski = order.get("freski", {})
    if freski.get("enabled"):
        size = freski.get("size_cm", {})
        lines.extend(
            [
                "ФРЕСКИ: Да",
                f"Каталог: {safe_value(freski.get('catalog_name'))}",
                f"Артикул: {safe_value(freski.get('article'))}",
                f"Ширина, см: {safe_value(size.get('width'))}",
                f"Высота, см: {safe_value(size.get('height'))}",
                f"Материал: {safe_value(freski.get('material'))}",
                f"Цветопроба: {safe_value(freski.get('color_sample'))}",
                f"Гидроизоляция: {safe_value(freski.get('hydro_insulation'))}",
                f"Старение: {safe_value(freski.get('crackle_aging'))}",
                f"Примечание: {safe_value(freski.get('note'))}",
                "",
            ]
        )
    else:
        lines.extend(["ФРЕСКИ: Нет", ""])

    # Дизайнерские обои
    designer = order.get("designer_wallpapers", {})
    if designer.get("enabled"):
        color_sample = designer.get("color_sample", {})
        lines.extend(
            [
                "ДИЗАЙНЕРСКИЕ ОБОИ: Да",
                f"Каталог: {safe_value(designer.get('catalog_name'))}",
                f"Артикул: {safe_value(designer.get('article'))}",
                f"Материал: Велюр",
                f"Размер панели: {safe_value(designer.get('panel_size_cm'))}",
                f"Порядок панелей: {safe_value(designer.get('panels_order_left_to_right'))}",
                f"Тип производства: {safe_value(designer.get('production_type'))}",
                f"Цветопроба нужна: {safe_value(color_sample.get('required'))}",
                f"Отзеркалить: {safe_value(designer.get('mirror'))}",
                "",
            ]
        )
    else:
        lines.extend(["ДИЗАЙНЕРСКИЕ ОБОИ: Нет", ""])

    # Фоновые обои
    background = order.get("background_wallpapers", {})
    if background.get("enabled"):
        bg_color_sample = background.get("color_sample", {})
        bg_size = background.get("size_cm", {})
        lines.extend(
            [
                "ФОНОВЫЕ ОБОИ: Да",
                f"Каталог: {safe_value(background.get('catalog_name'))}",
                f"Артикул: {safe_value(background.get('article'))}",
                f"Материал: {safe_value(background.get('material_type'))}",
                f"Ширина, см: {safe_value(bg_size.get('width'))}",
                f"Высота, см: {safe_value(bg_size.get('height'))}",
                f"Цветопроба нужна: {safe_value(bg_color_sample.get('required'))}",
                "",
            ]
        )
    else:
        lines.extend(["ФОНОВЫЕ ОБОИ: Нет", ""])

    # Картины
    paintings = order.get("paintings", {})
    if paintings.get("enabled"):
        canvas_size = paintings.get("canvas_total_size_cm", {})
        visible_size = paintings.get("visible_image_size_cm", {})
        lines.extend(
            [
                "КАРТИНЫ ИЗ КАТАЛОГА ФРЕСКИ И ИНДИВИДУАЛЬНЫЕ ИЗОБРАЖЕНИЯ: Да",
                f"Материал: Итальянский холст",
                f"Макс. размер, см: 450 x 140",
                f"Артикул: {safe_value(paintings.get('article'))}",
                f"Полный размер холста, см:",
                f"  Ширина: {safe_value(canvas_size.get('width'))}",
                f"  Высота: {safe_value(canvas_size.get('height'))}",
                f"Видимый размер изображения, см:",
                f"  Ширина: {safe_value(visible_size.get('width'))}",
                f"  Высота: {safe_value(visible_size.get('height'))}",
                "",
            ]
        )

    delivery = order.get("delivery", {})
    if delivery.get("needed") is not None:
        lines.extend(
            [
                "ДОСТАВКА",
                f"Нужна: {safe_value(delivery.get('needed'))}",
                f"Тип: {safe_value(delivery.get('type'))}",
                f"ТК/Самовывоз: {safe_value(delivery.get('carrier'))}",
                f"Обрешетка: {safe_value(delivery.get('crate'))}",
                "",
            ]
        )
    else:
        lines.extend(["КАРТИНЫ: Нет", ""])

    return "\n".join(lines)


def telegram_label(message: Message | CallbackQuery) -> str:
    if isinstance(message, CallbackQuery):
        user = message.from_user
    else:
        user = message.from_user
    username = f"@{user.username}" if user and user.username else "без username"
    return f"{username} (id {user.id})"


async def ensure_user_profile(
    message: Message | CallbackQuery,
) -> dict | None:
    if isinstance(message, CallbackQuery):
        user = message.from_user
    else:
        user = message.from_user
    if not user:
        return None
    return {
        "user_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": None,
        "region": None,
    }


def build_empty_order(telegram: str) -> dict[str, Any]:
    return {
        "client": {
            "telegram": telegram,
            "legal_entity": None,
            "city": None,
            "phone": None,
            "email": None,
            "region": None,
        },
        "freski": {
            "enabled": False,
            "catalog_name": None,
            "article": None,
            "size_cm": {"width": None, "height": None},
            "material": None,
            "color_sample": None,
            "hydro_insulation": None,
            "crackle_aging": None,
            "note": None,
        },
        "designer_wallpapers": {
            "enabled": False,
            "catalog_name": None,
            "article": None,
            "panel_size_cm": None,
            "panels_order_left_to_right": None,
            "production_type": None,
            "color_sample": {"required": None, "agreed_without_sample": None},
            "mirror": None,
        },
        "background_wallpapers": {
            "enabled": False,
            "catalog_name": None,
            "article": None,
            "material_type": None,
            "size_cm": {"width": None, "height": None},
            "color_sample": {"required": None, "agreed_without_sample": None},
        },
        "paintings": {
            "enabled": False,
            "article": None,
            "canvas_total_size_cm": {"width": None, "height": None},
            "visible_image_size_cm": {"width": None, "height": None},
        },
        "delivery": {
            "needed": None,
            "type": None,
            "carrier": None,
            "crate": None,
        },
    }


async def run_bot() -> None:
    config = load_config()
    managers_map = load_managers(config.managers_json)
    router = Router()
    
    def reload_managers():
        nonlocal managers_map
        managers_map = load_managers(config.managers_json)
        return managers_map

    @router.message(CommandStart())
    async def start(message: Message, state: FSMContext) -> None:
        await state.clear()
        await ensure_user_profile(message)
        order = build_empty_order(telegram_label(message))
        await state.update_data(order=order)
        await state.set_state(OrderFlow.ask_freski)
        await message.answer("Добрый день.")
        await message.answer("Хотите фрески?", reply_markup=yes_no_kb())

    # Админские команды
    async def admin_menu(msg: Message | CallbackQuery, state: FSMContext) -> None:
        if isinstance(msg, CallbackQuery):
            message = msg.message
            user_id = msg.from_user.id
        else:
            message = msg
            user_id = msg.from_user.id
        
        if not is_admin(user_id, config.admin_ids):
            await message.answer("У вас нет прав доступа.")
            return
        
        await state.clear()
        current_managers = reload_managers()
        regions_list = list(current_managers.keys())
        if not regions_list:
            await message.answer("Нет регионов.")
            return
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"Редактировать: {region}", callback_data=f"admin_edit:{region}")]
                for region in regions_list
            ]
        )
        await message.answer("Выберите регион для редактирования менеджеров:", reply_markup=kb)

    @router.message(Command("admin"))
    async def admin_command(message: Message, state: FSMContext) -> None:
        await admin_menu(message, state)

    @router.callback_query(F.data.startswith("admin_edit:"))
    async def admin_edit_region(callback: CallbackQuery, state: FSMContext) -> None:
        if not is_admin(callback.from_user.id, config.admin_ids):
            await callback.answer("У вас нет прав доступа.", show_alert=True)
            return
        
        await callback.answer()
        region = callback.data.split(":", 1)[1]
        current_managers = reload_managers()
        region_managers = current_managers.get(region, [])
        
        if not region_managers:
            await callback.message.edit_text(f"Регион: {region}\n\nМенеджеров нет. Добавить менеджера?", reply_markup=yes_no_kb())
            await state.update_data(admin_edit_region=region, admin_edit_manager_index=None)
            await state.set_state(OrderFlow.admin_edit_manager_region)
            return
        
        buttons = []
        for idx, manager in enumerate(region_managers):
            name = manager.name or "Без имени"
            buttons.append([InlineKeyboardButton(
                text=f"{name} (ID: {manager.chat_id})",
                callback_data=f"admin_manager:{region}:{idx}"
            )])
        buttons.append([InlineKeyboardButton(text="Добавить менеджера", callback_data=f"admin_add_manager:{region}")])
        buttons.append([InlineKeyboardButton(text="Назад", callback_data="admin_back")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await callback.message.edit_text(f"Регион: {region}\n\nВыберите менеджера для редактирования:", reply_markup=kb)

    @router.callback_query(F.data.startswith("admin_manager:"))
    async def admin_edit_manager(callback: CallbackQuery, state: FSMContext) -> None:
        if not is_admin(callback.from_user.id, config.admin_ids):
            await callback.answer("У вас нет прав доступа.", show_alert=True)
            return
        
        await callback.answer()
        parts = callback.data.split(":")
        region = parts[1]
        manager_idx = int(parts[2])
        current_managers = reload_managers()
        manager = current_managers[region][manager_idx]
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Изменить имя", callback_data=f"admin_change_name:{region}:{manager_idx}")],
                [InlineKeyboardButton(text="Изменить ID", callback_data=f"admin_change_id:{region}:{manager_idx}")],
                [InlineKeyboardButton(text="Удалить", callback_data=f"admin_delete:{region}:{manager_idx}")],
                [InlineKeyboardButton(text="Назад", callback_data=f"admin_edit:{region}")],
            ]
        )
        name = manager.name or "Без имени"
        await callback.message.edit_text(
            f"Менеджер:\nИмя: {name}\nID: {manager.chat_id}\n\nЧто изменить?",
            reply_markup=kb
        )

    @router.callback_query(F.data.startswith("admin_add_manager:"))
    async def admin_add_manager(callback: CallbackQuery, state: FSMContext) -> None:
        if not is_admin(callback.from_user.id, config.admin_ids):
            await callback.answer("У вас нет прав доступа.", show_alert=True)
            return
        
        await callback.answer()
        region = callback.data.split(":", 1)[1]
        await state.update_data(admin_edit_region=region, admin_edit_manager_index=None)
        await state.set_state(OrderFlow.admin_edit_manager_name)
        await callback.message.edit_text(f"Регион: {region}\n\nВведите имя нового менеджера:")

    @router.callback_query(F.data.startswith("admin_change_name:"))
    async def admin_change_name_start(callback: CallbackQuery, state: FSMContext) -> None:
        if not is_admin(callback.from_user.id, config.admin_ids):
            await callback.answer("У вас нет прав доступа.", show_alert=True)
            return
        
        await callback.answer()
        parts = callback.data.split(":")
        region = parts[1]
        manager_idx = int(parts[2])
        await state.update_data(admin_edit_region=region, admin_edit_manager_index=manager_idx)
        await state.set_state(OrderFlow.admin_edit_manager_name)
        await callback.message.edit_text(f"Введите новое имя менеджера:")

    @router.message(OrderFlow.admin_edit_manager_name, F.text)
    async def admin_change_name(message: Message, state: FSMContext) -> None:
        if not is_admin(message.from_user.id, config.admin_ids):
            await message.answer("У вас нет прав доступа.")
            return
        
        data = await state.get_data()
        region = data.get("admin_edit_region")
        manager_idx = data.get("admin_edit_manager_index")
        new_name = message.text.strip()
        
        current_managers = reload_managers()
        if manager_idx is None:
            # Добавляем нового менеджера
            await state.set_state(OrderFlow.admin_edit_manager_chat_id)
            await message.answer(f"Имя: {new_name}\n\nВведите chat_id менеджера:")
            await state.update_data(admin_new_name=new_name)
        else:
            # Изменяем существующего
            manager = current_managers[region][manager_idx]
            current_managers[region][manager_idx] = ManagerInfo(name=new_name, chat_id=manager.chat_id)
            save_managers(config.managers_json, current_managers)
            await state.clear()
            await message.answer(f"Имя менеджера изменено на: {new_name}")
            await admin_menu(message, state)

    @router.callback_query(F.data.startswith("admin_change_id:"))
    async def admin_change_id_start(callback: CallbackQuery, state: FSMContext) -> None:
        if not is_admin(callback.from_user.id, config.admin_ids):
            await callback.answer("У вас нет прав доступа.", show_alert=True)
            return
        
        await callback.answer()
        parts = callback.data.split(":")
        region = parts[1]
        manager_idx = int(parts[2])
        await state.update_data(admin_edit_region=region, admin_edit_manager_index=manager_idx)
        await state.set_state(OrderFlow.admin_edit_manager_chat_id)
        await callback.message.edit_text(f"Введите новый chat_id менеджера:")

    @router.message(OrderFlow.admin_edit_manager_chat_id, F.text)
    async def admin_change_chat_id(message: Message, state: FSMContext) -> None:
        if not is_admin(message.from_user.id, config.admin_ids):
            await message.answer("У вас нет прав доступа.")
            return
        
        try:
            new_chat_id = int(message.text.strip())
        except ValueError:
            await message.answer("Ошибка: chat_id должен быть числом. Попробуйте снова:")
            return
        
        data = await state.get_data()
        region = data.get("admin_edit_region")
        manager_idx = data.get("admin_edit_manager_index")
        new_name = data.get("admin_new_name")
        
        current_managers = reload_managers()
        if manager_idx is None:
            # Добавляем нового менеджера
            if region not in current_managers:
                current_managers[region] = []
            current_managers[region].append(ManagerInfo(name=new_name, chat_id=new_chat_id))
            save_managers(config.managers_json, current_managers)
            await state.clear()
            await message.answer(f"Менеджер добавлен:\nИмя: {new_name}\nID: {new_chat_id}")
            await admin_menu(message, state)
        else:
            # Изменяем существующего
            manager = current_managers[region][manager_idx]
            current_managers[region][manager_idx] = ManagerInfo(name=manager.name, chat_id=new_chat_id)
            save_managers(config.managers_json, current_managers)
            await state.clear()
            await message.answer(f"Chat ID менеджера изменен на: {new_chat_id}")
            await admin_menu(message, state)

    @router.callback_query(F.data.startswith("admin_delete:"))
    async def admin_delete_manager(callback: CallbackQuery, state: FSMContext) -> None:
        if not is_admin(callback.from_user.id, config.admin_ids):
            await callback.answer("У вас нет прав доступа.", show_alert=True)
            return
        
        await callback.answer()
        parts = callback.data.split(":")
        region = parts[1]
        manager_idx = int(parts[2])
        
        current_managers = reload_managers()
        manager = current_managers[region][manager_idx]
        name = manager.name or "Без имени"
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Да, удалить", callback_data=f"admin_confirm_delete:{region}:{manager_idx}")],
                [InlineKeyboardButton(text="Отмена", callback_data=f"admin_edit:{region}")],
            ]
        )
        await callback.message.edit_text(
            f"Вы уверены, что хотите удалить менеджера:\nИмя: {name}\nID: {manager.chat_id}?",
            reply_markup=kb
        )

    @router.callback_query(F.data.startswith("admin_confirm_delete:"))
    async def admin_confirm_delete(callback: CallbackQuery, state: FSMContext) -> None:
        if not is_admin(callback.from_user.id, config.admin_ids):
            await callback.answer("У вас нет прав доступа.", show_alert=True)
            return
        
        await callback.answer()
        parts = callback.data.split(":")
        region = parts[1]
        manager_idx = int(parts[2])
        
        current_managers = reload_managers()
        manager = current_managers[region].pop(manager_idx)
        if not current_managers[region]:
            del current_managers[region]
        
        save_managers(config.managers_json, current_managers)
        await callback.message.edit_text("Менеджер удален.")
        await admin_menu(callback, state)

    @router.callback_query(F.data == "admin_back")
    async def admin_back(callback: CallbackQuery, state: FSMContext) -> None:
        if not is_admin(callback.from_user.id, config.admin_ids):
            await callback.answer("У вас нет прав доступа.", show_alert=True)
            return
        
        await callback.answer()
        await admin_menu(callback, state)

    @router.callback_query(OrderFlow.admin_edit_manager_region, F.data.in_(["yes", "no"]))
    async def admin_add_manager_confirm(callback: CallbackQuery, state: FSMContext) -> None:
        if not is_admin(callback.from_user.id, config.admin_ids):
            await callback.answer("У вас нет прав доступа.", show_alert=True)
            return
        
        await callback.answer()
        if callback.data == "yes":
            data = await state.get_data()
            region = data.get("admin_edit_region")
            await state.set_state(OrderFlow.admin_edit_manager_name)
            await callback.message.edit_text(f"Регион: {region}\n\nВведите имя нового менеджера:")
        else:
            await state.clear()
            await admin_menu(callback, state)

    @router.callback_query(OrderFlow.ask_designer_wallpapers, F.data.in_(["yes", "no"]))
    async def ask_designer_wallpapers(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        order = data["order"]
        if callback.data == "yes":
            order["designer_wallpapers"]["enabled"] = True
            await state.update_data(order=order)
            await state.set_state(OrderFlow.designer_catalog)
            await callback.message.edit_text("Хотите дизайнерские обои? Да\n\nКаталог:", reply_markup=list_kb(config.designer_catalogs, "catalog"))
        else:
            order["designer_wallpapers"]["enabled"] = False
            await state.update_data(order=order)
            await state.set_state(OrderFlow.ask_background_wallpapers)
            await callback.message.edit_text("Хотите дизайнерские обои? Нет\n\nХотите фоновые обои?", reply_markup=yes_no_kb())

    @router.callback_query(OrderFlow.designer_catalog, F.data.startswith("catalog:"))
    async def designer_catalog(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        idx = int(callback.data.split(":", 1)[1])
        catalog_name = config.designer_catalogs[idx]
        data = await state.get_data()
        order = data["order"]
        order["designer_wallpapers"]["catalog_name"] = catalog_name
        await state.update_data(order=order)
        await state.set_state(OrderFlow.designer_article)
        await callback.message.edit_text(f"Каталог: {catalog_name}\n\nАртикул:")

    @router.message(OrderFlow.designer_article, F.text)
    async def designer_article(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        article = message.text.strip()
        order["designer_wallpapers"]["article"] = article
        await state.update_data(order=order)
        if article.upper().startswith("ID-"):
            await message.answer("Похоже, это фреска. Проверьте, пожалуйста, раздел.")
        await state.set_state(OrderFlow.designer_panel_size)
        await message.answer("Материал: Велюр.\n\nРазмер панели:", reply_markup=list_kb(config.designer_panel_sizes, "panel_size"))

    @router.callback_query(OrderFlow.designer_panel_size, F.data.startswith("panel_size:"))
    async def designer_panel_size(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        idx = int(callback.data.split(":", 1)[1])
        panel_size = config.designer_panel_sizes[idx]
        data = await state.get_data()
        order = data["order"]
        order["designer_wallpapers"]["panel_size_cm"] = panel_size
        await state.update_data(order=order)
        await state.set_state(OrderFlow.designer_panel_order)
        await callback.message.edit_text(f"Размер панели: {panel_size}\n\nПорядок панелей слева направо:")

    @router.message(OrderFlow.designer_panel_order, F.text)
    async def designer_panel_order(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["designer_wallpapers"]["panels_order_left_to_right"] = message.text.strip()
        await state.update_data(order=order)
        await state.set_state(OrderFlow.designer_production_type)
        await message.answer(
            "Тип производства:",
            reply_markup=list_kb(["Единым полотном", "Порезать на полотна"], "production_type"),
        )

    @router.callback_query(OrderFlow.designer_production_type, F.data.startswith("production_type:"))
    async def designer_production_type(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        idx = int(callback.data.split(":", 1)[1])
        production_type = ["Единым полотном", "Порезать на полотна"][idx]
        data = await state.get_data()
        order = data["order"]
        order["designer_wallpapers"]["production_type"] = production_type
        await state.update_data(order=order)
        await state.set_state(OrderFlow.designer_color_sample)
        await callback.message.edit_text(f"Тип производства: {production_type}\n\nНужна цветопроба?", reply_markup=yes_no_kb())

    @router.callback_query(OrderFlow.designer_color_sample, F.data.in_(["yes", "no"]))
    async def designer_color_sample(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        order = data["order"]
        order["designer_wallpapers"]["color_sample"]["required"] = callback.data == "yes"
        await state.update_data(order=order)
        sample_text = "Да" if callback.data == "yes" else "Нет"
        await state.set_state(OrderFlow.designer_mirror)
        await callback.message.edit_text(
            f"Цветопроба нужна: {sample_text}\n\nОтзеркалить?",
            reply_markup=yes_no_kb(),
        )

    @router.callback_query(OrderFlow.designer_mirror, F.data.in_(["yes", "no"]))
    async def designer_mirror(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        order = data["order"]
        mirror_value = "Да" if callback.data == "yes" else "Нет"
        order["designer_wallpapers"]["mirror"] = mirror_value
        await state.update_data(order=order)
        await state.set_state(OrderFlow.ask_background_wallpapers)
        await callback.message.edit_text(
            f"Отзеркалить: {mirror_value}\n\nХотите фоновые обои?",
            reply_markup=yes_no_kb(),
        )

    @router.callback_query(OrderFlow.ask_freski, F.data.in_(["yes", "no"]))
    async def ask_freski(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        order = data["order"]
        if callback.data == "yes":
            order["freski"]["enabled"] = True
            await state.update_data(order=order)
            await state.set_state(OrderFlow.freski_catalog)
            await callback.message.edit_text(
                "Хотите фрески? Да\n\nКаталог:",
                reply_markup=list_kb(config.freski_catalogs, "freski_catalog"),
            )
        else:
            order["freski"]["enabled"] = False
            await state.update_data(order=order)
            await state.set_state(OrderFlow.ask_designer_wallpapers)
            await callback.message.edit_text("Хотите фрески? Нет\n\nХотите дизайнерские обои?", reply_markup=yes_no_kb())

    @router.callback_query(OrderFlow.freski_catalog, F.data.startswith("freski_catalog:"))
    async def freski_catalog(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        idx = int(callback.data.split(":", 1)[1])
        catalog_name = config.freski_catalogs[idx]
        data = await state.get_data()
        order = data["order"]
        order["freski"]["catalog_name"] = catalog_name
        await state.update_data(order=order)
        await state.set_state(OrderFlow.freski_article)
        await callback.message.edit_text(f"Каталог: {catalog_name}\n\nАртикул:")

    @router.message(OrderFlow.freski_article, F.text)
    async def freski_article(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["freski"]["article"] = message.text.strip()
        await state.update_data(order=order)
        await state.set_state(OrderFlow.freski_width)
        await message.answer(f"Артикул: {message.text.strip()}\n\nШирина, см:")

    @router.message(OrderFlow.freski_width, F.text)
    async def freski_width(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["freski"]["size_cm"]["width"] = message.text.strip()
        await state.update_data(order=order)
        await state.set_state(OrderFlow.freski_height)
        await message.answer(f"Ширина, см: {message.text.strip()}\n\nВысота, см:")

    @router.message(OrderFlow.freski_height, F.text)
    async def freski_height(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["freski"]["size_cm"]["height"] = message.text.strip()
        await state.update_data(order=order)
        await state.set_state(OrderFlow.freski_material)
        await message.answer(
            f"Высота, см: {message.text.strip()}\n\nМатериал:",
            reply_markup=list_kb(config.freski_materials, "freski_material"),
        )

    @router.callback_query(OrderFlow.freski_material, F.data.startswith("freski_material:"))
    async def freski_material(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        idx = int(callback.data.split(":", 1)[1])
        material = config.freski_materials[idx]
        data = await state.get_data()
        order = data["order"]
        order["freski"]["material"] = material
        await state.update_data(order=order)

        if material in {"Саббия", "Саббия Фасад", "Пиетра"}:
            await state.set_state(OrderFlow.freski_humidity)
            await callback.message.edit_text(
                f"Материал: {material}\n\nПомещение влажное?",
                reply_markup=yes_no_kb(),
            )
            return

        if material == "Кракелюр":
            await state.set_state(OrderFlow.freski_crackle_aging)
            await callback.message.edit_text(
                "Кракелюр выбран.\n\nНужна средняя степень старения?",
                reply_markup=yes_no_kb(),
            )
            return

        if material in {"Колоре", "Колоре Лайт"}:
            order["freski"]["color_sample"] = "Да"
            await state.update_data(order=order)
            await state.set_state(OrderFlow.freski_note)
            skip_kb = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Пропустить", callback_data="skip_note")]]
            )
            await callback.message.edit_text(
                f"Материал: {material}\n\nЦветопроба: Да\n\nПримечание:",
                reply_markup=skip_kb,
            )
            return

        await state.set_state(OrderFlow.freski_color_sample)
        await callback.message.edit_text(
            f"Материал: {material}\n\nНужна цветопроба?",
            reply_markup=yes_no_kb(),
        )

    @router.callback_query(OrderFlow.freski_humidity, F.data.in_(["yes", "no"]))
    async def freski_humidity(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        order = data["order"]
        humidity = "Да" if callback.data == "yes" else "Нет"
        order["freski"]["hydro_insulation"] = "Да" if callback.data == "yes" else "Нет"
        await state.update_data(order=order)
        await state.set_state(OrderFlow.freski_color_sample)
        await callback.message.edit_text(
            f"Помещение влажное: {humidity}\n\nНужна цветопроба?",
            reply_markup=yes_no_kb(),
        )

    @router.callback_query(OrderFlow.freski_crackle_aging, F.data.in_(["yes", "no"]))
    async def freski_crackle_aging(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        order = data["order"]
        if callback.data == "yes":
            order["freski"]["material"] = "Кракелюр средняя степень"
            order["freski"]["crackle_aging"] = "Да"
        else:
            order["freski"]["material"] = "Кракелюр без старения"
            order["freski"]["crackle_aging"] = "Нет"
        await state.update_data(order=order)
        await state.set_state(OrderFlow.freski_color_sample)
        await callback.message.edit_text(
            "Нужна цветопроба?",
            reply_markup=yes_no_kb(),
        )

    @router.callback_query(OrderFlow.freski_color_sample, F.data.in_(["yes", "no"]))
    async def freski_color_sample(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        order = data["order"]
        color_sample = "Да" if callback.data == "yes" else "Нет"
        order["freski"]["color_sample"] = color_sample
        await state.update_data(order=order)
        await state.set_state(OrderFlow.freski_note)
        skip_kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Пропустить", callback_data="skip_note")]]
        )
        await callback.message.edit_text(
            f"Цветопроба: {color_sample}\n\nПримечание:",
            reply_markup=skip_kb,
        )

    @router.callback_query(OrderFlow.freski_note, F.data == "skip_note")
    async def freski_note_skip(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        order = data["order"]
        order["freski"]["note"] = None
        await state.update_data(order=order)
        await state.set_state(OrderFlow.ask_designer_wallpapers)
        await callback.message.edit_text("Примечание: пропущено\n\nХотите дизайнерские обои?", reply_markup=yes_no_kb())

    @router.message(OrderFlow.freski_note, F.text)
    async def freski_note(message: Message, state: FSMContext) -> None:
        note_text = message.text.strip()
        if note_text.lower() in {"пропустить", "пропуск", "skip"}:
            note_text = None
            display_text = "пропущено"
        else:
            display_text = note_text
        
        data = await state.get_data()
        order = data["order"]
        order["freski"]["note"] = note_text
        await state.update_data(order=order)
        await state.set_state(OrderFlow.ask_designer_wallpapers)
        await message.answer(f"Примечание: {display_text}\n\nХотите дизайнерские обои?", reply_markup=yes_no_kb())

    # Фоновые обои
    @router.callback_query(OrderFlow.ask_background_wallpapers, F.data.in_(["yes", "no"]))
    async def ask_background_wallpapers(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        order = data["order"]
        if callback.data == "yes":
            order["background_wallpapers"]["enabled"] = True
            await state.update_data(order=order)
            await state.set_state(OrderFlow.background_material)
            await callback.message.edit_text(
                "Хотите фоновые обои? Да\n\nФактура (velure/colore):",
                reply_markup=list_kb(config.background_materials, "bg_material"),
            )
        else:
            order["background_wallpapers"]["enabled"] = False
            await state.update_data(order=order)
            await state.set_state(OrderFlow.ask_paintings)
            await callback.message.edit_text(
                "Хотите фоновые обои? Нет\n\nХотите картины из каталога фрески и индивидуальные изображения?",
                reply_markup=yes_no_kb(),
            )

    @router.callback_query(OrderFlow.background_material, F.data.startswith("bg_material:"))
    async def background_material(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        idx = int(callback.data.split(":", 1)[1])
        material = config.background_materials[idx]
        data = await state.get_data()
        order = data["order"]
        order["background_wallpapers"]["material_type"] = material
        await state.update_data(order=order)
        await state.set_state(OrderFlow.background_catalog)
        await callback.message.edit_text(
            f"Фактура: {material}\n\nКаталог:",
            reply_markup=list_kb(config.background_catalogs, "bg_catalog"),
        )

    @router.callback_query(OrderFlow.background_catalog, F.data.startswith("bg_catalog:"))
    async def background_catalog(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        idx = int(callback.data.split(":", 1)[1])
        catalog_name = config.background_catalogs[idx]
        data = await state.get_data()
        order = data["order"]
        order["background_wallpapers"]["catalog_name"] = catalog_name
        await state.update_data(order=order)
        await state.set_state(OrderFlow.background_article)
        await callback.message.edit_text(f"Каталог: {catalog_name}\n\nАртикул:")

    @router.message(OrderFlow.background_article, F.text)
    async def background_article(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["background_wallpapers"]["article"] = message.text.strip()
        await state.update_data(order=order)
        await state.set_state(OrderFlow.background_height)
        material = order["background_wallpapers"].get("material_type", "")
        heights = config.background_heights_velour if material == "Велюр" else config.background_heights_colore
        heights_str = [str(h) for h in heights]
        await message.answer(
            f"Артикул: {message.text.strip()}\n\nВысота, см:",
            reply_markup=list_kb(heights_str, "bg_height"),
        )

    @router.callback_query(OrderFlow.background_height, F.data.startswith("bg_height:"))
    async def background_height(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        idx = int(callback.data.split(":", 1)[1])
        data = await state.get_data()
        order = data["order"]
        material = order["background_wallpapers"].get("material_type", "")
        heights = config.background_heights_velour if material == "Велюр" else config.background_heights_colore
        height = str(heights[idx])
        order["background_wallpapers"]["size_cm"]["height"] = height
        await state.update_data(order=order)
        await state.set_state(OrderFlow.background_width)
        await callback.message.edit_text(
            f"Высота, см: {height}\n\nШирина, см (минимум 100, далее любое значение):"
        )

    @router.message(OrderFlow.background_width, F.text)
    async def background_width(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["background_wallpapers"]["size_cm"]["width"] = message.text.strip()
        await state.update_data(order=order)
        await state.set_state(OrderFlow.background_color_sample)
        await message.answer(
            f"Ширина, см: {message.text.strip()}\n\nНужна цветопроба?",
            reply_markup=yes_no_kb(),
        )

    @router.callback_query(OrderFlow.background_color_sample, F.data.in_(["yes", "no"]))
    async def background_color_sample(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        order = data["order"]
        order["background_wallpapers"]["color_sample"]["required"] = callback.data == "yes"
        await state.update_data(order=order)
        sample_text = "Да" if callback.data == "yes" else "Нет"
        await state.set_state(OrderFlow.ask_paintings)
        await callback.message.edit_text(
            f"Цветопроба нужна: {sample_text}\n\nХотите картины из каталога фрески и индивидуальные изображения?",
            reply_markup=yes_no_kb(),
        )

    # Картины
    @router.callback_query(OrderFlow.ask_paintings, F.data.in_(["yes", "no"]))
    async def ask_paintings(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        order = data["order"]
        if callback.data == "yes":
            order["paintings"]["enabled"] = True
            await state.update_data(order=order)
            await state.set_state(OrderFlow.paintings_article)
            await callback.message.edit_text("Хотите картины? Да\n\nМатериал: Итальянский холст. Макс. размер: 450 x 140 см.\n\nАртикул:")
        else:
            order["paintings"]["enabled"] = False
            await state.update_data(order=order)
            await state.set_state(OrderFlow.ask_delivery_needed)
            await callback.message.edit_text("Хотите картины? Нет\n\nДоставка нужна?", reply_markup=yes_no_kb())

    @router.message(OrderFlow.paintings_article, F.text)
    async def paintings_article(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["paintings"]["article"] = message.text.strip()
        await state.update_data(order=order)
        await state.set_state(OrderFlow.paintings_canvas_width)
        await message.answer(f"Артикул: {message.text.strip()}\n\nПолный размер холста. Ширина, см:")

    @router.message(OrderFlow.paintings_canvas_width, F.text)
    async def paintings_canvas_width(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["paintings"]["canvas_total_size_cm"]["width"] = message.text.strip()
        await state.update_data(order=order)
        await state.set_state(OrderFlow.paintings_canvas_height)
        await message.answer(f"Полный размер холста. Ширина, см: {message.text.strip()}\n\nПолный размер холста. Высота, см:")

    @router.message(OrderFlow.paintings_canvas_height, F.text)
    async def paintings_canvas_height(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["paintings"]["canvas_total_size_cm"]["height"] = message.text.strip()
        await state.update_data(order=order)
        await state.set_state(OrderFlow.paintings_visible_width)
        await message.answer(f"Полный размер холста. Высота, см: {message.text.strip()}\n\nВидимый размер изображения. Ширина, см:")

    @router.message(OrderFlow.paintings_visible_width, F.text)
    async def paintings_visible_width(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["paintings"]["visible_image_size_cm"]["width"] = message.text.strip()
        await state.update_data(order=order)
        await state.set_state(OrderFlow.paintings_visible_height)
        await message.answer(f"Видимый размер изображения. Ширина, см: {message.text.strip()}\n\nВидимый размер изображения. Высота, см:")

    @router.message(OrderFlow.paintings_visible_height, F.text)
    async def paintings_visible_height(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["paintings"]["visible_image_size_cm"]["height"] = message.text.strip()
        await state.update_data(order=order)
        await state.set_state(OrderFlow.ask_delivery_needed)
        await message.answer(f"Видимый размер изображения. Высота, см: {message.text.strip()}\n\nДоставка нужна?", reply_markup=yes_no_kb())

    # Доставка
    @router.callback_query(OrderFlow.ask_delivery_needed, F.data.in_(["yes", "no"]))
    async def ask_delivery_needed(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        order = data["order"]
        needed = "Да" if callback.data == "yes" else "Нет"
        order["delivery"]["needed"] = needed
        await state.update_data(order=order)
        if callback.data == "yes":
            await state.set_state(OrderFlow.delivery_type)
            await callback.message.edit_text(
                "Доставка нужна: Да\n\nДо терминала ТК или до адреса?",
                reply_markup=list_kb(["До терминала ТК", "До адреса"], "delivery_type"),
            )
        else:
            await state.set_state(OrderFlow.ask_legal_entity)
            await callback.message.edit_text("Доставка не нужна.\n\nЮрлицо (ИП/ООО):")

    @router.callback_query(OrderFlow.delivery_type, F.data.startswith("delivery_type:"))
    async def delivery_type(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        idx = int(callback.data.split(":", 1)[1])
        delivery_type_value = ["До терминала ТК", "До адреса"][idx]
        data = await state.get_data()
        order = data["order"]
        order["delivery"]["type"] = delivery_type_value
        await state.update_data(order=order)
        await state.set_state(OrderFlow.delivery_carrier)
        await callback.message.edit_text(
            f"Тип доставки: {delivery_type_value}\n\nТК или самовывоз:",
            reply_markup=list_kb(config.delivery_carriers, "delivery_carrier"),
        )

    @router.callback_query(OrderFlow.delivery_carrier, F.data.startswith("delivery_carrier:"))
    async def delivery_carrier(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        idx = int(callback.data.split(":", 1)[1])
        carrier = config.delivery_carriers[idx]
        data = await state.get_data()
        order = data["order"]
        order["delivery"]["carrier"] = carrier
        await state.update_data(order=order)
        await state.set_state(OrderFlow.delivery_crate)
        await callback.message.edit_text(
            f"ТК/Самовывоз: {carrier}\n\nОбрешетка нужна?",
            reply_markup=yes_no_kb(),
        )

    @router.callback_query(OrderFlow.delivery_crate, F.data.in_(["yes", "no"]))
    async def delivery_crate(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        crate_value = "Да" if callback.data == "yes" else "Нет"
        data = await state.get_data()
        order = data["order"]
        order["delivery"]["crate"] = crate_value
        await state.update_data(order=order)
        await state.set_state(OrderFlow.ask_legal_entity)
        await callback.message.edit_text(
            f"Обрешетка: {crate_value}\n\nЮрлицо (ИП/ООО):"
        )

    # Финальные вопросы
    @router.message(OrderFlow.ask_legal_entity, F.text)
    async def ask_legal_entity(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["client"]["legal_entity"] = message.text.strip()
        await state.update_data(order=order)
        await state.set_state(OrderFlow.ask_city)
        await message.answer("Город:")

    @router.message(OrderFlow.ask_city, F.text)
    async def ask_city(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["client"]["city"] = message.text.strip()
        await state.update_data(order=order)
        await state.set_state(OrderFlow.ask_phone)
        await message.answer("Телефон:")

    @router.message(OrderFlow.ask_phone, F.text)
    async def ask_phone(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["client"]["phone"] = message.text.strip()
        await state.update_data(order=order)
        await state.set_state(OrderFlow.ask_email)
        await message.answer("Email:")

    @router.message(OrderFlow.ask_email, F.text)
    async def ask_email(message: Message, state: FSMContext) -> None:
        email = message.text.strip()
        data = await state.get_data()
        order = data["order"]
        order["client"]["email"] = email
        await state.update_data(order=order)
        await state.set_state(OrderFlow.ask_region)
        current_managers = reload_managers()
        regions_list = list(current_managers.keys())
        await message.answer(
            "Выберите регион:",
            reply_markup=list_kb(regions_list, "region"),
        )

    @router.callback_query(OrderFlow.ask_region, F.data.startswith("region:"))
    async def ask_region(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        idx = int(callback.data.split(":", 1)[1])
        current_managers = reload_managers()
        regions_list = list(current_managers.keys())
        region = regions_list[idx]
        data = await state.get_data()
        order = data["order"]
        order["client"]["region"] = region
        await state.update_data(order=order)
        await callback.message.edit_text(f"Регион: {region}")
        await finalize_order(callback.message, state, order)

    async def finalize_order(
        message: Message,
        state: FSMContext,
        order: dict[str, Any],
    ) -> None:
        summary = format_summary(order)
        region = order["client"].get("region", "")
        current_managers = reload_managers()
        manager_list = current_managers.get(region, [])
        
        manager_errors = []
        successful_sends = 0
        
        if manager_list:
            for manager in manager_list:
                try:
                    await message.bot.send_message(manager.chat_id, summary)
                    successful_sends += 1
                except Exception as e:
                    error_msg = str(e)
                    manager_name = manager.name or f"ID {manager.chat_id}"
                    manager_errors.append(f"{manager_name} (ID: {manager.chat_id}): {error_msg}")
                    logging.error(f"Failed to send message to manager {manager.chat_id}: {e}")
        
        # Пересылка админам - ВСЕГДА, если включено
        admin_summary = summary
        if manager_errors:
            admin_summary += "\n\n⚠️ ОШИБКИ ПРИ ОТПРАВКЕ МЕНЕДЖЕРАМ:\n"
            for error in manager_errors:
                admin_summary += f"• {error}\n"
        elif not manager_list:
            admin_summary += "\n\n⚠️ Менеджеры по региону не найдены."
        
        # Отправка админам - всегда, если включено
        logging.info(f"forward_to_admins: {config.forward_to_admins}, admin_ids: {config.admin_ids}")
        if config.forward_to_admins:
            if config.admin_ids:
                for admin_id in config.admin_ids:
                    try:
                        await message.bot.send_message(admin_id, admin_summary)
                        logging.info(f"✓ Successfully sent order summary to admin {admin_id}")
                    except Exception as e:
                        logging.error(f"✗ Failed to send message to admin {admin_id}: {e}")
            else:
                logging.warning("⚠ FORWARD_TO_ADMINS is enabled but ADMIN_IDS is empty")
        else:
            logging.info("ℹ FORWARD_TO_ADMINS is disabled, skipping admin notification")
        
        # Сообщение пользователю - показываем итоговую информацию без tg id и разделов "Нет"
        user_summary = format_user_summary(order)
        user_message = "Спасибо за вашу заявку!\n\n"
        user_message += "Ваша заявка:\n"
        user_message += user_summary
        user_message += "\n\nМы свяжемся с вами в ближайшее время."
        
        await state.clear()
        await message.answer(user_message)

    dp = Dispatcher()
    dp.include_router(router)
    bot = Bot(config.token)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(run_bot())

