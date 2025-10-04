from contextlib import suppress

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, MagicData
from aiogram.types import Message, InlineKeyboardButton, CallbackQuery
from aiogram.utils.markdown import hcode, hbold
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.manager import Manager
from app.bot.utils.redis import RedisStorage

# Импорт для работы с базой данных
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text  # Добавлен импорт text
from datetime import datetime  # Добавлен импорт datetime

from environs import Env

env = Env()
env.read_env()

DATABASE_URL = f"postgresql+asyncpg://{env.str('DB_USER')}:{env.str('DB_PASSWORD')}@{env.str('PG_HOST')}:{env.str('PG_PORT')}/{env.str('DB_NAME')}"

V2RAYTUN_DEEPLINK = f"{env.str('WEBHOOK_HOST')}/?url=v2raytun://import/"
HAPP_DEEPLINK = f"{env.str('WEBHOOK_HOST')}/?url=happ://add/"

engine = create_async_engine(DATABASE_URL)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# Функция для получения ключей из БД
async def get_keys(session: AsyncSession, tg_id: int):
    # Используем text для SQL запроса
    query = text("""
        SELECT * FROM keys WHERE tg_id = :tg_id
    """)
    
    result = await session.execute(query, {"tg_id": tg_id})
    return result.mappings().all()  # Возвращаем список словарей

# Функция для получения и форматирования информации о ключах пользователя
async def get_user_keys_info(tg_id: int) -> tuple[str, list]:
    try:
        async with async_session() as session:
            keys = await get_keys(session, tg_id)
            
            if not keys:
                return "У пользователя нет активных ключей.", []
            
            result = "🔑 <b>Информация о ключах пользователя:</b>\n\n"
            keys_data = []  # Список для хранения данных о ключах для инлайн кнопок
            
            for i, key in enumerate(keys, 1):
                expiry_time = key.get('expiry_time', 0)
                expiry_date = datetime.utcfromtimestamp(expiry_time / 1000) if expiry_time else datetime.utcnow()
                current_date = datetime.utcnow()
                time_left = expiry_date - current_date
                
                if time_left.total_seconds() <= 0:
                    status = "❌ истек"
                else:
                    status = f"✅ активен (осталось {time_left.days} дней)"
                
                result += (
                    f"<b>Ключ #{i}:</b>\n"
                    f"• ID: <code>{key.get('client_id', 'не указан')}</code>\n"
                    f"• Ключ: <code>{key.get('email', 'не указан')}</code>\n"
                    f"• Кластер: <code>{key.get('server_id', 'не указан')}</code>\n"
                    f"• Статус: {status}\n"
                    f"• Срок действия до: {expiry_date.strftime('%d.%m.%Y %H:%M')}\n"
                )
                
                if key.get('tariff_id'):
                    result += f"• Тариф: {key.get('tariff_id')}\n"
                
                result += f"• Заморожен: {'Да' if key.get('is_frozen') else 'Нет'}\n\n"

                # Сохраняем информацию о ключе для создания инлайн кнопок
                key_data = {
                    'id': i,
                    'name': f"Ключ #{i} - {key.get('email', 'не указан')}",
                    'key': key.get('key', ''),
                    'remnawave_link': key.get('remnawave_link', '')
                }
                keys_data.append(key_data)
                
                # Дополнительная информация о ключе
                if key.get('key'):
                    result += (
                        f"• Диплинк Happ: <code>{HAPP_DEEPLINK}{key.get('key')}</code>\n"
                        f"• Диплинк V2RayTun: <code>{V2RAYTUN_DEEPLINK}{key.get('key')}</code>\n\n\n"
                    )

                if key.get('remnawave_link'):
                    result += f"• Remnawave: <code>{key.get('remnawave_link')}</code>\n\n\n"
            
            result += "Нажмите на кнопку с ключом, чтобы отправить диплинки для приложений пользователю."
            return result, keys_data
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Ошибка при получении информации о ключах: {e}\n{error_details}")
        return f"Ошибка при получении информации о ключах пользователя: {e}", []

router_id = Router()
router_id.message.filter(
    F.chat.type.in_(["group", "supergroup"]),
)


@router_id.message(Command("id"))
async def handler(message: Message) -> None:
    """
    Sends chat ID in response to the /id command.

    :param message: Message object.
    :return: None
    """
    await message.reply(hcode(message.chat.id))


router = Router()
router.message.filter(
    F.message_thread_id.is_not(None),
    F.chat.type.in_(["group", "supergroup"]),
    MagicData(F.event_chat.id == F.config.bot.GROUP_ID),  # type: ignore
)


@router.message(Command("silent"))
async def handler(message: Message, manager: Manager, redis: RedisStorage) -> None:
    """
    Toggles silent mode for a user in the group.
    If silent mode is disabled, it will be enabled, and vice versa.

    :param message: Message object.
    :param manager: Manager object.
    :param redis: RedisStorage object.
    :return: None
    """
    user_data = await redis.get_by_message_thread_id(message.message_thread_id)
    if not user_data: return None  # noqa

    if user_data.message_silent_mode:
        text = manager.text_message.get("silent_mode_disabled")
        with suppress(TelegramBadRequest):
            # Reply with the specified text
            await message.reply(text)

            # Unpin the chat message with the silent mode status
            await message.bot.unpin_chat_message(
                chat_id=message.chat.id,
                message_id=user_data.message_silent_id,
            )

        user_data.message_silent_mode = False
        user_data.message_silent_id = None
    else:
        text = manager.text_message.get("silent_mode_enabled")
        with suppress(TelegramBadRequest):
            # Reply with the specified text
            msg = await message.reply(text)

            # Pin the chat message with the silent mode status
            await msg.pin(disable_notification=True)

        user_data.message_silent_mode = True
        user_data.message_silent_id = msg.message_id

    await redis.update_user(user_data.id, user_data)


@router.message(Command("information"))
async def handler(message: Message, manager: Manager, redis: RedisStorage) -> None:
    """
    Sends user information in response to the /information command.

    :param message: Message object.
    :param manager: Manager object.
    :param redis: RedisStorage object.
    :return: None
    """
    user_data = await redis.get_by_message_thread_id(message.message_thread_id)
    if not user_data: return None  # noqa

    format_data = user_data.to_dict()
    format_data["full_name"] = hbold(format_data["full_name"])
    text = manager.text_message.get("user_information")
    # Reply with formatted user information
    await message.reply(text.format_map(format_data))


@router.message(Command("keys"))
async def handler(message: Message, manager: Manager, redis: RedisStorage) -> None:
    user_data = await redis.get_by_message_thread_id(message.message_thread_id)
    if not user_data: return None  # noqa

    try:
        # Пытаемся получить информацию о ключах
        keys_info, keys_data = await get_user_keys_info(user_data.id)
        
        # Создаем инлайн кнопки для каждого ключа
        builder = InlineKeyboardBuilder()
        for key_data in keys_data:
            # Создаем callback данные, содержащие ID пользователя и ID ключа
            callback_data = f"key_{user_data.id}_{key_data['id']}_{key_data['key']}"
            builder.add(InlineKeyboardButton(
                text=key_data['name'][:35],  # Ограничиваем длину текста кнопки
                callback_data=callback_data
            ))
        
        # Размещаем кнопки в одну колонку
        builder.adjust(1)
        
        await message.reply(
            text=keys_info,
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Ошибка при формировании сообщения с ключами: {e}\n{error_details}")
        # Отправляем сообщение без информации о ключах
        await message.reply(
            text="Не удалось получить информацию о ключах пользователя.",
            parse_mode="HTML"
        )

# # Обработчик нажатия на инлайн кнопку с ключом
# @router.callback_query(F.data.startswith("key_"))
# async def handle_key_selection(callback_query: CallbackQuery):
#     # Извлекаем данные из callback_data
#     data_parts = callback_query.data.split("_")
#     if len(data_parts) < 4:
#         await callback_query.answer("Некорректные данные")
#         return
    
#     _, user_id, key_id, key_value = data_parts[0], data_parts[1], data_parts[2], data_parts[3]
    
#     # Создаем инлайн кнопки для выбора приложения
#     builder = InlineKeyboardBuilder()
    
#     # Добавляем кнопки для разных приложений с диплинками
#     builder.add(InlineKeyboardButton(
#         text="V2RayTun",
#         url=f"{V2RAYTUN_DEEPLINK}{key_value}"
#     ))
    
#     builder.add(InlineKeyboardButton(
#         text="Happ",
#         url=f"{HAPP_DEEPLINK}{key_value}"
#     ))
    
#     # Размещаем кнопки в строку
#     builder.adjust(2)
    
#     # Отправляем сообщение с инструкциями и кнопками
#     await callback_query.message.answer(
#         text="Нажмите на ваше приложение, и ключ вставится автоматически:",
#         reply_markup=builder.as_markup()
#     )
    
#     # Отвечаем на callback, чтобы убрать часы загрузки
#     await callback_query.answer()

# Обработчик нажатия на инлайн кнопку с ключом
@router.callback_query(F.data.startswith("key_"))
async def handle_key_selection(callback_query: CallbackQuery, manager: Manager, redis: RedisStorage):
    # Извлекаем данные из callback_data
    data_parts = callback_query.data.split("_")
    if len(data_parts) < 4:
        await callback_query.answer("Некорректные данные")
        return
    
    _, user_id, key_id, key_value = data_parts[0], data_parts[1], data_parts[2], data_parts[3]
    
    # Получаем данные пользователя
    user_data = await redis.get_user(int(user_id))
    if not user_data:
        await callback_query.answer("Пользователь не найден")
        return
    
    # Создаем инлайн кнопки для выбора приложения
    builder = InlineKeyboardBuilder()
    
    # Добавляем кнопки для разных приложений с диплинками
    builder.add(InlineKeyboardButton(
        text="V2RayTun",
        url=f"{V2RAYTUN_DEEPLINK}{key_value}"
    ))
    
    builder.add(InlineKeyboardButton(
        text="Happ",
        url=f"{HAPP_DEEPLINK}{key_value}"
    ))
    
    # Размещаем кнопки в строку
    builder.adjust(2)
    
    try:
        # Отправляем сообщение ПОЛЬЗОВАТЕЛЮ с инструкциями и кнопками
        await callback_query.bot.send_message(
            chat_id=user_data.id,  # ID пользователя
            text="Нажмите на ваше приложение, и ключ вставится автоматически:",
            reply_markup=builder.as_markup()
        )
        
        # Отправляем сообщение в ГРУППУ о том, что диплинки отправлены
        await callback_query.message.reply(
            text=f"Диплинки для ключа #{key_id} отправлены пользователю."
        )
        
        # Отвечаем на callback, чтобы убрать часы загрузки
        await callback_query.answer("Диплинки отправлены пользователю")
    except Exception as e:
        # В случае ошибки выводим сообщение
        print(f"Ошибка при отправке диплинков: {e}")
        await callback_query.answer("Ошибка при отправке диплинков")
        await callback_query.message.reply(f"Ошибка при отправке диплинков: {e}")


@router.message(Command(commands=["ban"]))
async def handler(message: Message, manager: Manager, redis: RedisStorage) -> None:
    """
    Toggles the ban status for a user in the group.
    If the user is banned, they will be unbanned, and vice versa.

    :param message: Message object.
    :param manager: Manager object.
    :param redis: RedisStorage object.
    :return: None
    """
    user_data = await redis.get_by_message_thread_id(message.message_thread_id)
    if not user_data: return None  # noqa

    if user_data.is_banned:
        user_data.is_banned = False
        text = manager.text_message.get("user_unblocked")
    else:
        user_data.is_banned = True
        text = manager.text_message.get("user_blocked")

    # Reply with the specified text
    await message.reply(text)
    await redis.update_user(user_data.id, user_data)
