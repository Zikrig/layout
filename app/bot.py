import asyncio
import json
import logging
import smtplib
from email.message import EmailMessage
from copy import deepcopy
import io
import mimetypes
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
    main_menu = State()
    # Фрески
    ask_freski = State()
    freski_catalog = State()
    freski_library_catalog = State()
    freski_article = State()
    freski_width = State()
    freski_height = State()
    freski_material = State()
    freski_humidity = State()
    freski_crackle_aging = State()
    freski_color_sample = State()
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
    delivery_address = State()
    delivery_carrier = State()
    delivery_crate = State()
    ask_comment = State()
    # Финальные данные
    ask_legal_entity = State()
    ask_city = State()
    ask_phone = State()
    ask_email = State()
    ask_region = State()
    ask_manager_choice = State()
    # Админские команды
    admin_edit_manager_region = State()
    admin_edit_manager_name = State()
    admin_edit_manager_chat_id = State()
    admin_edit_text_start = State()
    admin_edit_text_freski = State()
    admin_edit_text_designer = State()
    admin_edit_text_background = State()
    admin_edit_text_paintings = State()


@dataclass(frozen=True)
class ManagerInfo:
    name: str | None
    email: str | None
    chat_id: int | None


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


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Фрески", callback_data="menu:freski")],
            [InlineKeyboardButton(text="Дизайнерские обои", callback_data="menu:designer")],
            [InlineKeyboardButton(text="Фоновые обои", callback_data="menu:background")],
            [InlineKeyboardButton(text="Картины", callback_data="menu:paintings")],
        ]
    )


def new_order_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Сделать еще заказ", callback_data="new_order")],
        ]
    )


def merge_kb(
    base_kb: InlineKeyboardMarkup | None,
    nav_kb: InlineKeyboardMarkup | None,
) -> InlineKeyboardMarkup | None:
    if base_kb and nav_kb:
        return InlineKeyboardMarkup(
            inline_keyboard=base_kb.inline_keyboard + nav_kb.inline_keyboard
        )
    return base_kb or nav_kb


def nav_kb(show_back: bool, show_continue: bool) -> InlineKeyboardMarkup | None:
    buttons = []
    if show_back:
        buttons.append(InlineKeyboardButton(text="Назад", callback_data="nav:back"))
    if show_continue:
        buttons.append(InlineKeyboardButton(text="Продолжить", callback_data="nav:continue"))
    if not buttons:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def comment_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="comment:skip")],
            [InlineKeyboardButton(text="Готово", callback_data="comment:done")],
        ]
    )


def comment_prompt(order: dict[str, Any]) -> str:
    comment = order.get("comment", {})
    photos_count = len(comment.get("photos", []))
    documents_count = len(comment.get("documents", []))
    total_count = photos_count + documents_count
    return (
        "Комментарий (можно текст, фото и документы до 5 МБ каждый, общий лимит 15 МБ).\n"
        "Добавляйте файлы по одному.\n"
        f"Добавлено {total_count} файлов ({photos_count} фото, {documents_count} документов)."
    )


async def render_step(
    message: Message,
    state: FSMContext,
    prompt: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    include_nav: bool = True,
) -> None:
    data = await state.get_data()
    order = data.get("order", {})
    summary = format_user_summary(order)
    text = f"{summary}\n\n{prompt}"

    back_mode = data.get("back_mode", False)
    nav = nav_kb(show_back=True, show_continue=back_mode)
    full_kb = merge_kb(reply_markup, nav) if include_nav else reply_markup

    message_id = data.get("order_message_id")
    chat_id = message.chat.id
    if message_id:
        await message.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=full_kb,
        )
    else:
        sent = await message.answer(text, reply_markup=full_kb)
        await state.update_data(order_message_id=sent.message_id)

    await state.update_data(
        current_step={
            "state_name": await state.get_state(),
            "prompt": prompt,
            "reply_markup": reply_markup,
            "include_nav": include_nav,
            "order_snapshot": deepcopy(order),
        }
    )


async def send_email_via_smtp(
    host: str,
    port: int,
    user: str,
    password: str,
    to_email: str,
    subject: str,
    body: str,
    attachments: list[tuple[str, bytes, str, str]] | None = None,
) -> None:
    if not host or not user or not password:
        raise RuntimeError("SMTP settings are not configured")
    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    if attachments:
        for filename, content, maintype, subtype in attachments:
            msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)

    def _send() -> None:
        server = smtplib.SMTP(host, port, timeout=10)
        server.starttls()
        server.login(user, password)
        server.send_message(msg)
        server.quit()

    await asyncio.to_thread(_send)


async def acknowledge_and_cleanup(message: Message) -> None:
    try:
        temp = await message.answer(
            "Спасибо! Ответ принят! Мы освободим место через 3..."
        )
        await asyncio.sleep(1)
        await temp.edit_text("Спасибо! Ответ принят! Мы освободим место через 2...")
        await asyncio.sleep(1)
        await temp.edit_text("Спасибо! Ответ принят! Мы освободим место через 1...")
        await asyncio.sleep(1)
        await message.bot.delete_message(message.chat.id, temp.message_id)
        await message.bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        # Не критично, если не удалось удалить сообщение
        pass


async def push_current_step(state: FSMContext) -> None:
    data = await state.get_data()
    current_step = data.get("current_step")
    if not current_step:
        return
    history = data.get("history", [])
    history.append(current_step)
    await state.update_data(history=history, back_mode=False, resume_step=None)


async def go_to_state(
    message: Message,
    state: FSMContext,
    next_state: State,
    prompt: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    include_nav: bool = True,
) -> None:
    await push_current_step(state)
    await state.set_state(next_state)
    await render_step(message, state, prompt, reply_markup, include_nav)


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
                chat_id_raw = manager.get("chat_id")
                chat_id = int(chat_id_raw) if chat_id_raw not in (None, "") else None
                normalized.append(
                    ManagerInfo(
                        name=manager.get("name"),
                        email=manager.get("email"),
                        chat_id=chat_id,
                    )
                )
            else:
                normalized.append(ManagerInfo(name=None, email=None, chat_id=int(manager)))
        result[region] = normalized
    return result


def save_managers(path: str, managers_map: dict[str, list[ManagerInfo]]) -> None:
    """Сохраняет менеджеров в JSON файл"""
    regions_list = []
    for region, managers_list in managers_map.items():
        managers_data = []
        for manager in managers_list:
            manager_dict: dict[str, Any] = {}
            if manager.chat_id is not None:
                manager_dict["chat_id"] = manager.chat_id
            if manager.name:
                manager_dict["name"] = manager.name
            if manager.email:
                manager_dict["email"] = manager.email
            managers_data.append(manager_dict)
        regions_list.append({"region": region, "managers": managers_data})
    
    data = {"regions": regions_list}
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_texts(path: str) -> dict[str, str]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return {k: str(v) for k, v in raw.items()}
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def save_texts(path: str, texts: dict[str, str]) -> None:
    Path(path).write_text(json.dumps(texts, ensure_ascii=False, indent=2), encoding="utf-8")


def is_admin(user_id: int, admin_ids: list[int]) -> bool:
    """Проверяет, является ли пользователь админом"""
    return user_id in admin_ids


def safe_value(value: Any) -> str:
    if value is None:
        return "-"
    if value is True:
        return "Да"
    if value is False:
        return "Нет"
    text = str(value).strip()
    return text if text else "-"


def format_user_summary(order: dict[str, Any]) -> str:
    """Форматирует заявку для пользователя - без tg id и без разделов 'Нет'"""
    legal_entity = order["client"].get("legal_entity", "-")
    city = order["client"].get("city", "-")
    phone = order["client"].get("phone", "-")
    email = order["client"].get("email", "-")
    region = order["client"].get("region", "-")
    manager_name = order["client"].get("manager_name")

    lines = []
    if legal_entity:
        lines.append(f"Юрлицо: {legal_entity}")
    if city:
        lines.append(f"Город: {city}")
    if phone:
        lines.append(f"Телефон: {phone}")
    if email:
        lines.append(f"Email: {email}")
    if region:
        lines.append(f"Регион доставки: {region}")
    if manager_name:
        lines.append(f"Менеджер: {manager_name}")
    if lines:
        lines.append("")

    # Фрески - только если enabled
    freski = order.get("freski", {})
    if freski.get("enabled"):
        size = freski.get("size_cm", {})
        lines.append("ФРЕСКИ")
        if freski.get("catalog_name"):
            lines.append(f"Каталог: {safe_value(freski.get('catalog_name'))}")
        if freski.get("article"):
            lines.append(f"Артикул: {safe_value(freski.get('article'))}")
        if size.get("width"):
            lines.append(f"Ширина, см: {safe_value(size.get('width'))}")
        if size.get("height"):
            lines.append(f"Высота, см: {safe_value(size.get('height'))}")
        if freski.get("material"):
            lines.append(f"Материал: {safe_value(freski.get('material'))}")
        if freski.get("color_sample") is not None:
            lines.append(f"Цветопроба: {safe_value(freski.get('color_sample'))}")
        if freski.get("hydro_insulation") is not None:
            lines.append(f"Гидроизоляция: {safe_value(freski.get('hydro_insulation'))}")
        if freski.get("crackle_aging") is not None:
            lines.append(f"Старение: {safe_value(freski.get('crackle_aging'))}")
        lines.append("")

    # Дизайнерские обои - только если enabled
    designer = order.get("designer_wallpapers", {})
    if designer.get("enabled"):
        color_sample = designer.get("color_sample", {})
        lines.append("ДИЗАЙНЕРСКИЕ ОБОИ")
        if designer.get("catalog_name"):
            lines.append(f"Каталог: {safe_value(designer.get('catalog_name'))}")
        if designer.get("article"):
            lines.append(f"Артикул: {safe_value(designer.get('article'))}")
        lines.append("Материал: Велюр")
        if designer.get("panel_size_cm"):
            lines.append(f"Размер панели: {safe_value(designer.get('panel_size_cm'))}")
        if designer.get("panels_order_left_to_right"):
            lines.append(f"Порядок панелей: {safe_value(designer.get('panels_order_left_to_right'))}")
        if designer.get("production_type"):
            lines.append(f"Тип производства: {safe_value(designer.get('production_type'))}")
        if color_sample.get("required") is not None:
            lines.append(f"Цветопроба нужна: {safe_value(color_sample.get('required'))}")
        if designer.get("mirror") is not None:
            lines.append(f"Отзеркалить: {safe_value(designer.get('mirror'))}")
        lines.append("")

    # Фоновые обои - только если enabled
    background = order.get("background_wallpapers", {})
    if background.get("enabled"):
        bg_color_sample = background.get("color_sample", {})
        bg_size = background.get("size_cm", {})
        lines.append("ФОНОВЫЕ ОБОИ")
        if background.get("catalog_name"):
            lines.append(f"Каталог: {safe_value(background.get('catalog_name'))}")
        if background.get("article"):
            lines.append(f"Артикул: {safe_value(background.get('article'))}")
        if background.get("material_type"):
            lines.append(f"Материал: {safe_value(background.get('material_type'))}")
        if bg_size.get("width"):
            lines.append(f"Ширина, см: {safe_value(bg_size.get('width'))}")
        if bg_size.get("height"):
            lines.append(f"Высота, см: {safe_value(bg_size.get('height'))}")
        if bg_color_sample.get("required") is not None:
            lines.append(f"Цветопроба нужна: {safe_value(bg_color_sample.get('required'))}")
        lines.append("")

    # Картины - только если enabled
    paintings = order.get("paintings", {})
    if paintings.get("enabled"):
        canvas_size = paintings.get("canvas_total_size_cm", {})
        visible_size = paintings.get("visible_image_size_cm", {})
        lines.append("КАРТИНЫ ИЗ КАТАЛОГА ФРЕСКИ И ИНДИВИДУАЛЬНЫЕ ИЗОБРАЖЕНИЯ")
        lines.append("Материал: Итальянский холст")
        lines.append("Макс. размер, см: 450 x 140")
        if paintings.get("article"):
            lines.append(f"Артикул: {safe_value(paintings.get('article'))}")
        if canvas_size.get("width") or canvas_size.get("height"):
            lines.append("Полный размер холста, см:")
            if canvas_size.get("width"):
                lines.append(f"  Ширина: {safe_value(canvas_size.get('width'))}")
            if canvas_size.get("height"):
                lines.append(f"  Высота: {safe_value(canvas_size.get('height'))}")
        if visible_size.get("width") or visible_size.get("height"):
            lines.append("Видимый размер изображения, см:")
            if visible_size.get("width"):
                lines.append(f"  Ширина: {safe_value(visible_size.get('width'))}")
            if visible_size.get("height"):
                lines.append(f"  Высота: {safe_value(visible_size.get('height'))}")
        lines.append("")

    delivery = order.get("delivery", {})
    if delivery.get("needed") is not None:
        delivery_lines = [
            "ДОСТАВКА",
            f"Нужна: {safe_value(delivery.get('needed'))}",
            f"Тип: {safe_value(delivery.get('type'))}",
        ]
        if delivery.get("address"):
            delivery_lines.append(f"Адрес: {safe_value(delivery.get('address'))}")
        delivery_lines.extend([
            f"ТК/Самовывоз: {safe_value(delivery.get('carrier'))}",
            f"Обрешетка: {safe_value(delivery.get('crate'))}",
            "",
        ])
        lines.extend(delivery_lines)

    comment = order.get("comment", {})
    if comment.get("text") or comment.get("photos") or comment.get("documents"):
        lines.append("КОММЕНТАРИИ")
        if comment.get("text"):
            lines.append(f"Текст: {safe_value(comment.get('text'))}")
        photos_count = len(comment.get("photos", []))
        documents_count = len(comment.get("documents", []))
        if photos_count > 0:
            lines.append(f"Фото: {photos_count} шт.")
        if documents_count > 0:
            lines.append(f"Документы: {documents_count} шт.")
        lines.append("")

    return "\n".join(lines)


def format_summary(order: dict[str, Any]) -> str:
    tg = order["client"].get("telegram", "-")
    legal_entity = order["client"].get("legal_entity", "-")
    city = order["client"].get("city", "-")
    phone = order["client"].get("phone", "-")
    email = order["client"].get("email", "-")
    region = order["client"].get("region", "-")
    manager_name = order["client"].get("manager_name")

    lines = [
        "Новая заявка",
        f"Пользователь: {tg}",
        f"Юрлицо: {legal_entity}",
        f"Город: {city}",
        f"Телефон: {phone}",
        f"Email: {email}",
        f"Регион доставки: {region}",
    ]
    if manager_name:
        lines.append(f"Менеджер: {manager_name}")
    lines.append("")

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
        delivery_lines = [
            "ДОСТАВКА",
            f"Нужна: {safe_value(delivery.get('needed'))}",
            f"Тип: {safe_value(delivery.get('type'))}",
        ]
        if delivery.get("address"):
            delivery_lines.append(f"Адрес: {safe_value(delivery.get('address'))}")
        delivery_lines.extend([
            f"ТК/Самовывоз: {safe_value(delivery.get('carrier'))}",
            f"Обрешетка: {safe_value(delivery.get('crate'))}",
            "",
        ])
        lines.extend(delivery_lines)

    comment = order.get("comment", {})
    if comment.get("text") or comment.get("photos") or comment.get("documents"):
        lines.append("КОММЕНТАРИИ")
        if comment.get("text"):
            lines.append(f"Текст: {safe_value(comment.get('text'))}")
        photos_count = len(comment.get("photos", []))
        documents_count = len(comment.get("documents", []))
        if photos_count > 0:
            lines.append(f"Фото: {photos_count} шт.")
        if documents_count > 0:
            lines.append(f"Документы: {documents_count} шт.")
        lines.append("")

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
            "manager_email": None,
            "manager_name": None,
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
            "address": None,
            "carrier": None,
            "crate": None,
        },
        "comment": {
            "text": None,
            "photos": [],
            "documents": [],
            "total_size": 0,
        },
    }


async def run_bot() -> None:
    config = load_config()
    managers_map = load_managers(config.managers_json)
    texts_map = load_texts(config.texts_json)
    router = Router()
    
    def reload_managers():
        nonlocal managers_map
        managers_map = load_managers(config.managers_json)
        return managers_map

    def reload_texts():
        nonlocal texts_map
        texts_map = load_texts(config.texts_json)
        return texts_map

    @router.message(CommandStart())
    async def start(message: Message, state: FSMContext) -> None:
        await state.clear()
        await ensure_user_profile(message)
        order = build_empty_order(telegram_label(message))
        await state.update_data(order=order)
        await state.set_state(OrderFlow.main_menu)
        texts = reload_texts()
        start_text = texts.get("start_text", "Добрый день.")
        await message.answer(start_text)
        await render_step(message, state, "Выберите раздел:", main_menu_kb(), include_nav=False)

    @router.callback_query(F.data == "new_order")
    async def new_order(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await state.clear()
        await ensure_user_profile(callback)
        order = build_empty_order(telegram_label(callback))
        await state.update_data(order=order)
        await state.set_state(OrderFlow.main_menu)
        texts = reload_texts()
        start_text = texts.get("start_text", "Добрый день.")
        await callback.message.answer(start_text)
        await render_step(callback.message, state, "Выберите раздел:", main_menu_kb(), include_nav=False)

    @router.callback_query(OrderFlow.main_menu, F.data.in_(["menu:freski", "menu:designer", "menu:background", "menu:paintings"]))
    async def main_menu(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        order = data["order"]

        if callback.data == "menu:freski":
            order["freski"]["enabled"] = True
            await state.update_data(order=order)
            texts = reload_texts()
            freski_text = texts.get("freski_text", "Фрески")
            await go_to_state(
                callback.message,
                state,
                OrderFlow.freski_catalog,
                f"{freski_text}\n\nКаталог:",
                list_kb(config.freski_catalogs, "freski_catalog"),
            )
            return

        if callback.data == "menu:designer":
            order["designer_wallpapers"]["enabled"] = True
            await state.update_data(order=order)
            texts = reload_texts()
            designer_text = texts.get("designer_text", "Дизайнерские обои")
            await go_to_state(
                callback.message,
                state,
                OrderFlow.designer_catalog,
                f"{designer_text}\n\nКаталог:",
                list_kb(config.designer_catalogs, "catalog"),
            )
            return

        if callback.data == "menu:background":
            order["background_wallpapers"]["enabled"] = True
            await state.update_data(order=order)
            texts = reload_texts()
            background_text = texts.get("background_text", "Фоновые обои")
            await go_to_state(
                callback.message,
                state,
                OrderFlow.background_material,
                f"{background_text}\n\nФактура (velure/colore):",
                list_kb(config.background_materials, "bg_material"),
            )
            return

        # menu:paintings
        order["paintings"]["enabled"] = True
        await state.update_data(order=order)
        texts = reload_texts()
        paintings_text = texts.get("paintings_text", "Картины")
        await go_to_state(
            callback.message,
            state,
            OrderFlow.paintings_article,
            f"{paintings_text}\nМатериал: Итальянский холст. Макс. размер: 450 x 140 см.\n\nАртикул:",
        )

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
        
        buttons = [
            [InlineKeyboardButton(text=f"Редактировать: {region}", callback_data=f"admin_edit:{region}")]
            for region in regions_list
        ]
        buttons.append([InlineKeyboardButton(text="Изменить стартовый текст", callback_data="admin_text:start")])
        buttons.append([InlineKeyboardButton(text="Изменить текст фресок", callback_data="admin_text:freski")])
        buttons.append([InlineKeyboardButton(text="Изменить текст дизайнерских обоев", callback_data="admin_text:designer")])
        buttons.append([InlineKeyboardButton(text="Изменить текст фоновых обоев", callback_data="admin_text:background")])
        buttons.append([InlineKeyboardButton(text="Изменить текст картин", callback_data="admin_text:paintings")])
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer("Выберите действие:", reply_markup=kb)

    @router.message(Command("admin"))
    async def admin_command(message: Message, state: FSMContext) -> None:
        await admin_menu(message, state)

    @router.callback_query(F.data == "admin_text:start")
    async def admin_text_start(callback: CallbackQuery, state: FSMContext) -> None:
        if not is_admin(callback.from_user.id, config.admin_ids):
            await callback.answer("У вас нет прав доступа.", show_alert=True)
            return
        await callback.answer()
        await state.set_state(OrderFlow.admin_edit_text_start)
        await callback.message.edit_text("Введите новый стартовый текст:")

    @router.callback_query(F.data == "admin_text:freski")
    async def admin_text_freski(callback: CallbackQuery, state: FSMContext) -> None:
        if not is_admin(callback.from_user.id, config.admin_ids):
            await callback.answer("У вас нет прав доступа.", show_alert=True)
            return
        await callback.answer()
        await state.set_state(OrderFlow.admin_edit_text_freski)
        await callback.message.edit_text("Введите новый текст для фресок:")

    @router.callback_query(F.data == "admin_text:designer")
    async def admin_text_designer(callback: CallbackQuery, state: FSMContext) -> None:
        if not is_admin(callback.from_user.id, config.admin_ids):
            await callback.answer("У вас нет прав доступа.", show_alert=True)
            return
        await callback.answer()
        await state.set_state(OrderFlow.admin_edit_text_designer)
        await callback.message.edit_text("Введите новый текст для дизайнерских обоев:")

    @router.callback_query(F.data == "admin_text:background")
    async def admin_text_background(callback: CallbackQuery, state: FSMContext) -> None:
        if not is_admin(callback.from_user.id, config.admin_ids):
            await callback.answer("У вас нет прав доступа.", show_alert=True)
            return
        await callback.answer()
        await state.set_state(OrderFlow.admin_edit_text_background)
        await callback.message.edit_text("Введите новый текст для фоновых обоев:")

    @router.callback_query(F.data == "admin_text:paintings")
    async def admin_text_paintings(callback: CallbackQuery, state: FSMContext) -> None:
        if not is_admin(callback.from_user.id, config.admin_ids):
            await callback.answer("У вас нет прав доступа.", show_alert=True)
            return
        await callback.answer()
        await state.set_state(OrderFlow.admin_edit_text_paintings)
        await callback.message.edit_text("Введите новый текст для картин:")

    @router.message(OrderFlow.admin_edit_text_start, F.text)
    async def admin_edit_text_start(message: Message, state: FSMContext) -> None:
        if not is_admin(message.from_user.id, config.admin_ids):
            await message.answer("У вас нет прав доступа.")
            return
        texts = reload_texts()
        texts["start_text"] = message.text.strip()
        save_texts(config.texts_json, texts)
        await state.clear()
        await message.answer("Стартовый текст обновлен.")
        await admin_menu(message, state)

    @router.message(OrderFlow.admin_edit_text_freski, F.text)
    async def admin_edit_text_freski(message: Message, state: FSMContext) -> None:
        if not is_admin(message.from_user.id, config.admin_ids):
            await message.answer("У вас нет прав доступа.")
            return
        texts = reload_texts()
        texts["freski_text"] = message.text.strip()
        save_texts(config.texts_json, texts)
        await state.clear()
        await message.answer("Текст фресок обновлен.")
        await admin_menu(message, state)

    @router.message(OrderFlow.admin_edit_text_designer, F.text)
    async def admin_edit_text_designer(message: Message, state: FSMContext) -> None:
        if not is_admin(message.from_user.id, config.admin_ids):
            await message.answer("У вас нет прав доступа.")
            return
        texts = reload_texts()
        texts["designer_text"] = message.text.strip()
        save_texts(config.texts_json, texts)
        await state.clear()
        await message.answer("Текст дизайнерских обоев обновлен.")
        await admin_menu(message, state)

    @router.message(OrderFlow.admin_edit_text_background, F.text)
    async def admin_edit_text_background(message: Message, state: FSMContext) -> None:
        if not is_admin(message.from_user.id, config.admin_ids):
            await message.answer("У вас нет прав доступа.")
            return
        texts = reload_texts()
        texts["background_text"] = message.text.strip()
        save_texts(config.texts_json, texts)
        await state.clear()
        await message.answer("Текст фоновых обоев обновлен.")
        await admin_menu(message, state)

    @router.message(OrderFlow.admin_edit_text_paintings, F.text)
    async def admin_edit_text_paintings(message: Message, state: FSMContext) -> None:
        if not is_admin(message.from_user.id, config.admin_ids):
            await message.answer("У вас нет прав доступа.")
            return
        texts = reload_texts()
        texts["paintings_text"] = message.text.strip()
        save_texts(config.texts_json, texts)
        await state.clear()
        await message.answer("Текст картин обновлен.")
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
            name = manager.name or manager.email or "Без имени"
            chat_label = f"ID: {manager.chat_id}" if manager.chat_id else "ID: нет"
            buttons.append([InlineKeyboardButton(
                text=f"{name} ({chat_label})",
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
        name = manager.name or manager.email or "Без имени"
        chat_label = manager.chat_id if manager.chat_id else "нет"
        await callback.message.edit_text(
            f"Менеджер:\nИмя: {name}\nID: {chat_label}\n\nЧто изменить?",
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
            current_managers[region][manager_idx] = ManagerInfo(
                name=new_name,
                email=manager.email,
                chat_id=manager.chat_id,
            )
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
            current_managers[region].append(
                ManagerInfo(name=new_name, email=None, chat_id=new_chat_id)
            )
            save_managers(config.managers_json, current_managers)
            await state.clear()
            await message.answer(f"Менеджер добавлен:\nИмя: {new_name}\nID: {new_chat_id}")
            await admin_menu(message, state)
        else:
            # Изменяем существующего
            manager = current_managers[region][manager_idx]
            current_managers[region][manager_idx] = ManagerInfo(
                name=manager.name,
                email=manager.email,
                chat_id=new_chat_id,
            )
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
        name = manager.name or manager.email or "Без имени"
        
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Да, удалить", callback_data=f"admin_confirm_delete:{region}:{manager_idx}")],
                [InlineKeyboardButton(text="Отмена", callback_data=f"admin_edit:{region}")],
            ]
        )
        await callback.message.edit_text(
            f"Вы уверены, что хотите удалить менеджера:\nИмя: {name}\nID: {manager.chat_id or 'нет'}?",
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
            await go_to_state(
                callback.message,
                state,
                OrderFlow.designer_catalog,
                "Хотите дизайнерские обои? Да\n\nКаталог:",
                list_kb(config.designer_catalogs, "catalog"),
            )
        else:
            order["designer_wallpapers"]["enabled"] = False
            await state.update_data(order=order)
            await go_to_state(
                callback.message,
                state,
                OrderFlow.ask_background_wallpapers,
                "Хотите дизайнерские обои? Нет\n\nХотите фоновые обои?",
                yes_no_kb(),
            )

    @router.callback_query(OrderFlow.designer_catalog, F.data.startswith("catalog:"))
    async def designer_catalog(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        idx = int(callback.data.split(":", 1)[1])
        catalog_name = config.designer_catalogs[idx]
        data = await state.get_data()
        order = data["order"]
        order["designer_wallpapers"]["catalog_name"] = catalog_name
        await state.update_data(order=order)
        await go_to_state(
            callback.message,
            state,
            OrderFlow.designer_article,
            "Артикул:",
        )

    @router.message(OrderFlow.designer_article, F.text)
    async def designer_article(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        article = message.text.strip()
        order["designer_wallpapers"]["article"] = article
        await state.update_data(order=order)
        if article.upper().startswith("ID-"):
            await message.answer("Похоже, это фреска. Проверьте, пожалуйста, раздел.")
        await go_to_state(
            message,
            state,
            OrderFlow.designer_panel_size,
            "Материал: Велюр.\n\nРазмер панели:",
            list_kb(config.designer_panel_sizes, "panel_size"),
        )
        await acknowledge_and_cleanup(message)

    @router.callback_query(OrderFlow.designer_panel_size, F.data.startswith("panel_size:"))
    async def designer_panel_size(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        idx = int(callback.data.split(":", 1)[1])
        panel_size = config.designer_panel_sizes[idx]
        data = await state.get_data()
        order = data["order"]
        order["designer_wallpapers"]["panel_size_cm"] = panel_size
        await state.update_data(order=order)
        await go_to_state(
            callback.message,
            state,
            OrderFlow.designer_panel_order,
            "Порядок панелей слева направо:",
        )

    @router.message(OrderFlow.designer_panel_order, F.text)
    async def designer_panel_order(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["designer_wallpapers"]["panels_order_left_to_right"] = message.text.strip()
        await state.update_data(order=order)
        await go_to_state(
            message,
            state,
            OrderFlow.designer_production_type,
            "Тип производства:",
            list_kb(["Единым полотном", "Порезать на полотна"], "production_type"),
        )
        await acknowledge_and_cleanup(message)

    @router.callback_query(OrderFlow.designer_production_type, F.data.startswith("production_type:"))
    async def designer_production_type(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        idx = int(callback.data.split(":", 1)[1])
        production_type = ["Единым полотном", "Порезать на полотна"][idx]
        data = await state.get_data()
        order = data["order"]
        order["designer_wallpapers"]["production_type"] = production_type
        await state.update_data(order=order)
        await go_to_state(
            callback.message,
            state,
            OrderFlow.designer_color_sample,
            "Нужна цветопроба?",
            yes_no_kb(),
        )

    @router.callback_query(OrderFlow.designer_color_sample, F.data.in_(["yes", "no"]))
    async def designer_color_sample(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        order = data["order"]
        order["designer_wallpapers"]["color_sample"]["required"] = callback.data == "yes"
        await state.update_data(order=order)
        sample_text = "Да" if callback.data == "yes" else "Нет"
        await go_to_state(
            callback.message,
            state,
            OrderFlow.designer_mirror,
            "Отзеркалить?",
            yes_no_kb(),
        )

    @router.callback_query(OrderFlow.designer_mirror, F.data.in_(["yes", "no"]))
    async def designer_mirror(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        order = data["order"]
        mirror_value = "Да" if callback.data == "yes" else "Нет"
        order["designer_wallpapers"]["mirror"] = mirror_value
        await state.update_data(order=order)
        await go_to_state(
            callback.message,
            state,
            OrderFlow.ask_comment,
            comment_prompt(order),
            comment_kb(),
        )

    @router.callback_query(OrderFlow.ask_freski, F.data.in_(["yes", "no"]))
    async def ask_freski(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        order = data["order"]
        if callback.data == "yes":
            order["freski"]["enabled"] = True
            await state.update_data(order=order)
            await go_to_state(
                callback.message,
                state,
                OrderFlow.freski_catalog,
                "Хотите фрески? Да\n\nКаталог:",
                list_kb(config.freski_catalogs, "freski_catalog"),
            )
        else:
            order["freski"]["enabled"] = False
            await state.update_data(order=order)
            await go_to_state(
                callback.message,
                state,
                OrderFlow.ask_designer_wallpapers,
                "Хотите фрески? Нет\n\nХотите дизайнерские обои?",
                yes_no_kb(),
            )

    @router.callback_query(OrderFlow.freski_catalog, F.data.startswith("freski_catalog:"))
    async def freski_catalog(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        idx = int(callback.data.split(":", 1)[1])
        catalog_name = config.freski_catalogs[idx]
        data = await state.get_data()
        order = data["order"]
        if catalog_name == "Библиотека Affresco":
            order["freski"]["catalog_name"] = catalog_name
            await state.update_data(order=order)
            await go_to_state(
                callback.message,
                state,
                OrderFlow.freski_library_catalog,
                "Библиотека Affresco\n\nКаталог:",
                list_kb(config.freski_library_catalogs, "freski_library_catalog"),
            )
            return

        order["freski"]["catalog_name"] = "Индивидуальная отрисовка"
        await state.update_data(order=order)
        await go_to_state(
            callback.message,
            state,
            OrderFlow.freski_article,
            "Индивидуальная отрисовка\n\nАртикул:",
        )

    @router.callback_query(OrderFlow.freski_library_catalog, F.data.startswith("freski_library_catalog:"))
    async def freski_library_catalog(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        idx = int(callback.data.split(":", 1)[1])
        catalog_name = config.freski_library_catalogs[idx]
        data = await state.get_data()
        order = data["order"]
        order["freski"]["catalog_name"] = catalog_name
        await state.update_data(order=order)
        await go_to_state(
            callback.message,
            state,
            OrderFlow.freski_article,
            f"Каталог: {catalog_name}\n\nАртикул:",
        )

    @router.message(OrderFlow.freski_width, F.text)
    async def freski_width(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["freski"]["size_cm"]["width"] = message.text.strip()
        await state.update_data(order=order)
        await go_to_state(
            message,
            state,
            OrderFlow.freski_height,
            "Высота, см:",
        )
        await acknowledge_and_cleanup(message)

    @router.message(OrderFlow.freski_height, F.text)
    async def freski_height(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["freski"]["size_cm"]["height"] = message.text.strip()
        await state.update_data(order=order)
        await go_to_state(
            message,
            state,
            OrderFlow.freski_material,
            "Материал:",
            list_kb(config.freski_materials, "freski_material"),
        )
        await acknowledge_and_cleanup(message)

    @router.message(OrderFlow.freski_article, F.text)
    async def freski_article(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        article = message.text.strip()
        order["freski"]["article"] = article
        await state.update_data(order=order)
        await go_to_state(
            message,
            state,
            OrderFlow.freski_width,
            "Ширина, см:",
        )
        await acknowledge_and_cleanup(message)

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
            await go_to_state(
                callback.message,
                state,
                OrderFlow.freski_humidity,
                f"Материал: {material}\n\nПомещение влажное?",
                yes_no_kb(),
            )
            return

        if material == "Кракелюр":
            await go_to_state(
                callback.message,
                state,
                OrderFlow.freski_crackle_aging,
                "Кракелюр выбран.\n\nНужна средняя степень старения?",
                yes_no_kb(),
            )
            return

        if material in {"Колоре", "Колоре Лайт"}:
            order["freski"]["color_sample"] = "Да"
            await state.update_data(order=order)
            await go_to_state(
                callback.message,
                state,
                OrderFlow.ask_comment,
                comment_prompt(order),
                comment_kb(),
            )
            return

        await go_to_state(
            callback.message,
            state,
            OrderFlow.freski_color_sample,
            f"Материал: {material}\n\nНужна цветопроба?",
            yes_no_kb(),
        )

    @router.callback_query(OrderFlow.freski_humidity, F.data.in_(["yes", "no"]))
    async def freski_humidity(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        order = data["order"]
        humidity = "Да" if callback.data == "yes" else "Нет"
        order["freski"]["hydro_insulation"] = "Да" if callback.data == "yes" else "Нет"
        await state.update_data(order=order)
        await go_to_state(
            callback.message,
            state,
            OrderFlow.freski_color_sample,
            f"Помещение влажное: {humidity}\n\nНужна цветопроба?",
            yes_no_kb(),
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
        await go_to_state(
            callback.message,
            state,
            OrderFlow.freski_color_sample,
            "Нужна цветопроба?",
            yes_no_kb(),
        )

    @router.callback_query(OrderFlow.freski_color_sample, F.data.in_(["yes", "no"]))
    async def freski_color_sample(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        order = data["order"]
        color_sample = "Да" if callback.data == "yes" else "Нет"
        order["freski"]["color_sample"] = color_sample
        await state.update_data(order=order)
        await go_to_state(
            callback.message,
            state,
            OrderFlow.ask_comment,
            comment_prompt(order),
            comment_kb(),
        )

    # Фоновые обои
    @router.callback_query(OrderFlow.ask_background_wallpapers, F.data.in_(["yes", "no"]))
    async def ask_background_wallpapers(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        order = data["order"]
        if callback.data == "yes":
            order["background_wallpapers"]["enabled"] = True
            await state.update_data(order=order)
            await go_to_state(
                callback.message,
                state,
                OrderFlow.background_material,
                "Хотите фоновые обои? Да\n\nФактура (velure/colore):",
                list_kb(config.background_materials, "bg_material"),
            )
        else:
            order["background_wallpapers"]["enabled"] = False
            await state.update_data(order=order)
            await go_to_state(
                callback.message,
                state,
                OrderFlow.ask_paintings,
                "Хотите фоновые обои? Нет\n\nХотите картины из каталога фрески и индивидуальные изображения?",
                yes_no_kb(),
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
        await go_to_state(
            callback.message,
            state,
            OrderFlow.background_catalog,
            "Каталог:",
            list_kb(config.background_catalogs, "bg_catalog"),
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
        await go_to_state(
            callback.message,
            state,
            OrderFlow.background_article,
            "Артикул:",
        )

    @router.message(OrderFlow.background_article, F.text)
    async def background_article(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["background_wallpapers"]["article"] = message.text.strip()
        await state.update_data(order=order)
        material = order["background_wallpapers"].get("material_type", "")
        heights = config.background_heights_velour if material == "Велюр" else config.background_heights_colore
        heights_str = [str(h) for h in heights]
        await go_to_state(
            message,
            state,
            OrderFlow.background_height,
            "Высота, см:",
            list_kb(heights_str, "bg_height"),
        )
        await acknowledge_and_cleanup(message)

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
        await go_to_state(
            callback.message,
            state,
            OrderFlow.background_width,
            "Ширина, см (минимум 100, далее любое значение):",
        )

    @router.message(OrderFlow.background_width, F.text)
    async def background_width(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["background_wallpapers"]["size_cm"]["width"] = message.text.strip()
        await state.update_data(order=order)
        await go_to_state(
            message,
            state,
            OrderFlow.background_color_sample,
            "Нужна цветопроба?",
            yes_no_kb(),
        )
        await acknowledge_and_cleanup(message)

    @router.callback_query(OrderFlow.background_color_sample, F.data.in_(["yes", "no"]))
    async def background_color_sample(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        order = data["order"]
        order["background_wallpapers"]["color_sample"]["required"] = callback.data == "yes"
        await state.update_data(order=order)
        sample_text = "Да" if callback.data == "yes" else "Нет"
        await go_to_state(
            callback.message,
            state,
            OrderFlow.ask_comment,
            comment_prompt(order),
            comment_kb(),
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
            await go_to_state(
                callback.message,
                state,
                OrderFlow.paintings_article,
                "Хотите картины? Да\n\nМатериал: Итальянский холст. Макс. размер: 450 x 140 см.\n\nАртикул:",
            )
        else:
            order["paintings"]["enabled"] = False
            await state.update_data(order=order)
            await go_to_state(
                callback.message,
                state,
                OrderFlow.ask_comment,
                comment_prompt(order),
                comment_kb(),
            )

    @router.message(OrderFlow.paintings_article, F.text)
    async def paintings_article(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["paintings"]["article"] = message.text.strip()
        await state.update_data(order=order)
        await go_to_state(
            message,
            state,
            OrderFlow.paintings_canvas_width,
            "Полный размер холста. Ширина, см:",
        )
        await acknowledge_and_cleanup(message)

    @router.message(OrderFlow.paintings_canvas_width, F.text)
    async def paintings_canvas_width(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["paintings"]["canvas_total_size_cm"]["width"] = message.text.strip()
        await state.update_data(order=order)
        await go_to_state(
            message,
            state,
            OrderFlow.paintings_canvas_height,
            "Полный размер холста. Высота, см:",
        )
        await acknowledge_and_cleanup(message)

    @router.message(OrderFlow.paintings_canvas_height, F.text)
    async def paintings_canvas_height(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["paintings"]["canvas_total_size_cm"]["height"] = message.text.strip()
        await state.update_data(order=order)
        await go_to_state(
            message,
            state,
            OrderFlow.paintings_visible_width,
            "Видимый размер изображения. Ширина, см:",
        )
        await acknowledge_and_cleanup(message)

    @router.message(OrderFlow.paintings_visible_width, F.text)
    async def paintings_visible_width(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["paintings"]["visible_image_size_cm"]["width"] = message.text.strip()
        await state.update_data(order=order)
        await go_to_state(
            message,
            state,
            OrderFlow.paintings_visible_height,
            "Видимый размер изображения. Высота, см:",
        )
        await acknowledge_and_cleanup(message)

    @router.message(OrderFlow.paintings_visible_height, F.text)
    async def paintings_visible_height(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["paintings"]["visible_image_size_cm"]["height"] = message.text.strip()
        await state.update_data(order=order)
        await go_to_state(
            message,
            state,
            OrderFlow.ask_comment,
            comment_prompt(order),
            comment_kb(),
        )
        await acknowledge_and_cleanup(message)

    @router.callback_query(OrderFlow.ask_comment, F.data == "comment:skip")
    async def ask_comment_skip(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        order = data["order"]
        order["comment"] = {"text": None, "photos": [], "documents": [], "total_size": 0}
        await state.update_data(order=order)
        await go_to_state(
            callback.message,
            state,
            OrderFlow.ask_delivery_needed,
            "Доставка нужна?",
            yes_no_kb(),
        )

    @router.callback_query(OrderFlow.ask_comment, F.data == "comment:done")
    async def ask_comment_done(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await go_to_state(
            callback.message,
            state,
            OrderFlow.ask_delivery_needed,
            "Доставка нужна?",
            yes_no_kb(),
        )

    @router.message(OrderFlow.ask_comment, F.photo)
    async def ask_comment_photo(message: Message, state: FSMContext) -> None:
        photo = message.photo[-1]
        if photo.file_size and photo.file_size > 5 * 1024 * 1024:
            await render_step(
                message,
                state,
                f"Файл больше 5 МБ. Отправьте файл меньшего размера.\n\n{comment_prompt((await state.get_data())['order'])}",
                comment_kb(),
            )
            await acknowledge_and_cleanup(message)
            return
        data = await state.get_data()
        order = data["order"]
        comment = order.get("comment", {"text": None, "photos": [], "documents": [], "total_size": 0})
        new_total = comment.get("total_size", 0) + (photo.file_size or 0)
        if new_total > 15 * 1024 * 1024:
            await render_step(
                message,
                state,
                f"Превышен общий лимит 15 МБ. Нажмите «Готово» или удалите лишние файлы.\n\n{comment_prompt(order)}",
                comment_kb(),
            )
            await acknowledge_and_cleanup(message)
            return
        caption = message.caption.strip() if message.caption else None
        if caption:
            existing_text = comment.get("text")
            comment["text"] = f"{existing_text}\n{caption}" if existing_text else caption
        comment["photos"].append(
            {"file_id": photo.file_id, "size": photo.file_size or 0}
        )
        comment["total_size"] = new_total
        order["comment"] = comment
        await state.update_data(order=order)
        await render_step(
            message,
            state,
            f"Фото добавлено.\n{comment_prompt(order)}",
            comment_kb(),
        )
        await acknowledge_and_cleanup(message)

    @router.message(OrderFlow.ask_comment, F.document)
    async def ask_comment_document(message: Message, state: FSMContext) -> None:
        document = message.document
        if document.file_size and document.file_size > 5 * 1024 * 1024:
            await render_step(
                message,
                state,
                f"Файл больше 5 МБ. Отправьте документ меньшего размера.\n\n{comment_prompt((await state.get_data())['order'])}",
                comment_kb(),
            )
            await acknowledge_and_cleanup(message)
            return
        data = await state.get_data()
        order = data["order"]
        comment = order.get("comment", {"text": None, "photos": [], "documents": [], "total_size": 0})
        new_total = comment.get("total_size", 0) + (document.file_size or 0)
        if new_total > 15 * 1024 * 1024:
            await render_step(
                message,
                state,
                f"Превышен общий лимит 15 МБ. Нажмите «Готово» или удалите лишние файлы.\n\n{comment_prompt(order)}",
                comment_kb(),
            )
            await acknowledge_and_cleanup(message)
            return
        caption = message.caption.strip() if message.caption else None
        if caption:
            existing_text = comment.get("text")
            comment["text"] = f"{existing_text}\n{caption}" if existing_text else caption
        comment["documents"].append(
            {"file_id": document.file_id, "size": document.file_size or 0, "file_name": document.file_name}
        )
        comment["total_size"] = new_total
        order["comment"] = comment
        await state.update_data(order=order)
        await render_step(
            message,
            state,
            f"Документ добавлен.\n{comment_prompt(order)}",
            comment_kb(),
        )
        await acknowledge_and_cleanup(message)

    @router.message(OrderFlow.ask_comment, F.text)
    async def ask_comment_text(message: Message, state: FSMContext) -> None:
        text = message.text.strip()
        if text.lower() in {"пропустить", "пропуск", "skip"}:
            text = None
        data = await state.get_data()
        order = data["order"]
        comment = order.get("comment", {"text": None, "photos": [], "documents": [], "total_size": 0})
        comment["text"] = text
        order["comment"] = comment
        await state.update_data(order=order)
        await render_step(
            message,
            state,
            comment_prompt(order),
            comment_kb(),
        )
        await acknowledge_and_cleanup(message)

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
            await go_to_state(
                callback.message,
                state,
                OrderFlow.delivery_type,
                "До терминала ТК или до адреса?",
                list_kb(["До терминала ТК", "До адреса"], "delivery_type"),
            )
        else:
            await go_to_state(
                callback.message,
                state,
                OrderFlow.ask_legal_entity,
                "Юрлицо (ИП/ООО):",
            )

    @router.callback_query(F.data == "nav:back")
    async def nav_back(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        history = data.get("history", [])
        current_step = data.get("current_step")
        if not history:
            return
        last = history.pop()
        await state.update_data(
            history=history,
            resume_step=current_step,
            back_mode=True,
        )
        await state.set_state(last["state_name"])
        await render_step(
            callback.message,
            state,
            last["prompt"],
            last.get("reply_markup"),
            last.get("include_nav", True),
        )

    @router.callback_query(F.data == "nav:continue")
    async def nav_continue(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        data = await state.get_data()
        resume_step = data.get("resume_step")
        if not resume_step:
            return
        await state.update_data(back_mode=False, resume_step=None)
        await state.set_state(resume_step["state_name"])
        await render_step(
            callback.message,
            state,
            resume_step["prompt"],
            resume_step.get("reply_markup"),
            resume_step.get("include_nav", True),
        )

    @router.callback_query(OrderFlow.delivery_type, F.data.startswith("delivery_type:"))
    async def delivery_type(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        idx = int(callback.data.split(":", 1)[1])
        delivery_type_value = ["До терминала ТК", "До адреса"][idx]
        data = await state.get_data()
        order = data["order"]
        order["delivery"]["type"] = delivery_type_value
        await state.update_data(order=order)
        if delivery_type_value == "До адреса":
            await go_to_state(
                callback.message,
                state,
                OrderFlow.delivery_address,
                "Адрес доставки:",
            )
        else:
            await go_to_state(
                callback.message,
                state,
                OrderFlow.delivery_carrier,
                "ТК или самовывоз:",
                list_kb(config.delivery_carriers, "delivery_carrier"),
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
        if carrier in {"Курьерская Москва", "Самовывоз"}:
            order["delivery"]["crate"] = None
            await state.update_data(order=order)
            await go_to_state(
                callback.message,
                state,
                OrderFlow.ask_legal_entity,
                "Юрлицо (ИП/ООО):",
            )
        else:
            await go_to_state(
                callback.message,
                state,
                OrderFlow.delivery_crate,
                "Обрешетка нужна?",
                yes_no_kb(),
            )

    @router.callback_query(OrderFlow.delivery_crate, F.data.in_(["yes", "no"]))
    async def delivery_crate(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        crate_value = "Да" if callback.data == "yes" else "Нет"
        data = await state.get_data()
        order = data["order"]
        order["delivery"]["crate"] = crate_value
        await state.update_data(order=order)
        await go_to_state(
            callback.message,
            state,
            OrderFlow.ask_legal_entity,
            "Юрлицо (ИП/ООО):"
        )

    @router.message(OrderFlow.delivery_address, F.text)
    async def delivery_address(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["delivery"]["address"] = message.text.strip()
        await state.update_data(order=order)
        await go_to_state(
            message,
            state,
            OrderFlow.delivery_carrier,
            "ТК или самовывоз:",
            list_kb(config.delivery_carriers, "delivery_carrier"),
        )
        await acknowledge_and_cleanup(message)

    # Финальные вопросы
    @router.message(OrderFlow.ask_legal_entity, F.text)
    async def ask_legal_entity(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["client"]["legal_entity"] = message.text.strip()
        await state.update_data(order=order)
        await go_to_state(
            message,
            state,
            OrderFlow.ask_city,
            "Город:",
        )
        await acknowledge_and_cleanup(message)

    @router.message(OrderFlow.ask_city, F.text)
    async def ask_city(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["client"]["city"] = message.text.strip()
        await state.update_data(order=order)
        await go_to_state(
            message,
            state,
            OrderFlow.ask_phone,
            "Телефон:",
        )
        await acknowledge_and_cleanup(message)

    @router.message(OrderFlow.ask_phone, F.text)
    async def ask_phone(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        order = data["order"]
        order["client"]["phone"] = message.text.strip()
        await state.update_data(order=order)
        await go_to_state(
            message,
            state,
            OrderFlow.ask_email,
            "Email:",
        )
        await acknowledge_and_cleanup(message)

    @router.message(OrderFlow.ask_email, F.text)
    async def ask_email(message: Message, state: FSMContext) -> None:
        email = message.text.strip()
        data = await state.get_data()
        order = data["order"]
        order["client"]["email"] = email
        await state.update_data(order=order)
        current_managers = reload_managers()
        regions_list = list(current_managers.keys())
        await go_to_state(
            message,
            state,
            OrderFlow.ask_region,
            "Выберите регион:",
            list_kb(regions_list, "region"),
        )
        await acknowledge_and_cleanup(message)

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
        region_managers = current_managers.get(region, [])
        if len(region_managers) == 1:
            manager = region_managers[0]
            order["client"]["manager_email"] = manager.email
            order["client"]["manager_name"] = manager.name or manager.email
            await state.update_data(order=order)
            await render_step(
                callback.message,
                state,
                f"Регион: {region}\n\nМенеджер: {manager.name or manager.email or manager.chat_id}",
            )
            await finalize_order(callback.message, state, order)
            return
        if len(region_managers) > 1:
            await state.update_data(order=order)
            await state.set_state(OrderFlow.ask_manager_choice)
            manager_labels = [
                f"{m.name or m.email or 'Менеджер'} ({m.email or 'без email'})"
                for m in region_managers
            ]
            await render_step(
                callback.message,
                state,
                f"Регион: {region}\n\nВыберите менеджера:",
                list_kb(manager_labels, "manager"),
            )
            return
        await render_step(callback.message, state, f"Регион: {region}")
        await finalize_order(callback.message, state, order)

    @router.callback_query(OrderFlow.ask_manager_choice, F.data.startswith("manager:"))
    async def ask_manager_choice(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await push_current_step(state)
        idx = int(callback.data.split(":", 1)[1])
        data = await state.get_data()
        order = data["order"]
        region = order["client"].get("region", "")
        current_managers = reload_managers()
        region_managers = current_managers.get(region, [])
        if not region_managers or idx >= len(region_managers):
            await render_step(
                callback.message,
                state,
                "Менеджер не найден. Попробуйте выбрать регион заново.",
            )
            await state.set_state(OrderFlow.ask_region)
            regions_list = list(current_managers.keys())
            await go_to_state(
                callback.message,
                state,
                OrderFlow.ask_region,
                "Выберите регион:",
                list_kb(regions_list, "region"),
            )
            return
        manager = region_managers[idx]
        order["client"]["manager_email"] = manager.email
        order["client"]["manager_name"] = manager.name or manager.email or "Менеджер"
        await state.update_data(order=order)
        await render_step(
            callback.message,
            state,
            f"Менеджер: {manager.name or manager.email or manager.chat_id}",
        )
        await finalize_order(callback.message, state, order)

    async def finalize_order(
        message: Message,
        state: FSMContext,
        order: dict[str, Any],
    ) -> None:
        summary = format_summary(order)
        comment_photos = order.get("comment", {}).get("photos", [])
        region = order["client"].get("region", "")
        current_managers = reload_managers()
        manager_list = current_managers.get(region, [])
        
        manager_errors = []
        successful_sends = 0

        selected_manager_email = order["client"].get("manager_email")
        target_managers = manager_list
        if selected_manager_email:
            target_managers = [m for m in manager_list if m.email == selected_manager_email]

        attachments: list[tuple[str, bytes, str, str]] = []
        comment_data = order.get("comment", {})
        comment_photos = comment_data.get("photos", [])
        comment_documents = comment_data.get("documents", [])
        
        if comment_photos:
            for idx, photo in enumerate(comment_photos, start=1):
                try:
                    file = await message.bot.get_file(photo["file_id"])
                    buffer = io.BytesIO()
                    await message.bot.download_file(file.file_path, buffer)
                    file_bytes = buffer.getvalue()
                    mime_type, _ = mimetypes.guess_type(file.file_path or "")
                    if mime_type:
                        maintype, subtype = mime_type.split("/", 1)
                    else:
                        maintype, subtype = "image", "jpeg"
                    filename = f"comment_photo_{idx}.{subtype}"
                    attachments.append((filename, file_bytes, maintype, subtype))
                except Exception as e:
                    logging.error(f"Failed to download photo for email: {e}")
        
        if comment_documents:
            for idx, doc in enumerate(comment_documents, start=1):
                try:
                    file = await message.bot.get_file(doc["file_id"])
                    buffer = io.BytesIO()
                    await message.bot.download_file(file.file_path, buffer)
                    file_bytes = buffer.getvalue()
                    mime_type, _ = mimetypes.guess_type(file.file_path or "")
                    if mime_type:
                        maintype, subtype = mime_type.split("/", 1)
                    else:
                        maintype, subtype = "application", "octet-stream"
                    file_name = doc.get("file_name", f"document_{idx}")
                    attachments.append((file_name, file_bytes, maintype, subtype))
                except Exception as e:
                    logging.error(f"Failed to download document for email: {e}")

        if target_managers:
            for manager in target_managers:
                if not manager.email:
                    manager_label = manager.name or "Без имени"
                    manager_errors.append(f"{manager_label}: нет email")
                    continue
                try:
                    await send_email_via_smtp(
                        config.smtp_host,
                        config.smtp_port,
                        config.smtp_user,
                        config.smtp_password,
                        manager.email,
                        "Новая заявка",
                        summary,
                        attachments=attachments if attachments else None,
                    )
                    successful_sends += 1
                except Exception as e:
                    manager_name = manager.name or manager.email
                    manager_errors.append(f"{manager_name} ({manager.email}): {e}")
                    logging.error(f"Failed to send email to manager {manager.email}: {e}")

        if manager_errors:
            logging.error("Manager email send errors: " + "; ".join(manager_errors))
        
        # Сообщение пользователю - показываем итоговую информацию без tg id и разделов "Нет"
        user_summary = format_user_summary(order)
        user_message = "Спасибо за вашу заявку!\n\n"
        user_message += "Ваша заявка:\n"
        user_message += user_summary
        user_message += "\n\nМы свяжемся с вами в ближайшее время."
        
        await state.clear()
        await message.answer(user_message, reply_markup=new_order_kb())

    dp = Dispatcher()
    dp.include_router(router)
    bot = Bot(config.token)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(run_bot())

