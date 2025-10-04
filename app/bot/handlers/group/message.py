import asyncio
from typing import Optional

from aiogram import Router, F
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import MagicData
from aiogram.types import Message
from aiogram.utils.markdown import hlink

from app.bot.manager import Manager
from app.bot.types.album import Album
from app.bot.utils.redis import RedisStorage
# # Импорт для работы с базой данных
# from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
# from sqlalchemy.orm import sessionmaker
# from sqlalchemy import text  # Добавлен импорт text
# from datetime import datetime  # Добавлен импорт datetime

# from environs import Env

# env = Env()
# env.read_env()

# DATABASE_URL = f"postgresql+asyncpg://{env.str('DB_USER')}:{env.str('DB_PASSWORD')}@{env.str('PG_HOST')}:{env.str('PG_PORT')}/{env.str('DB_NAME')}"

# engine = create_async_engine(DATABASE_URL)
# async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# # Функция для получения ключей из БД
# async def get_keys(session: AsyncSession, tg_id: int):
#     # Используем text для SQL запроса
#     query = text("""
#         SELECT * FROM keys WHERE tg_id = :tg_id
#     """)
    
#     result = await session.execute(query, {"tg_id": tg_id})
#     return result.mappings().all()  # Возвращаем список словарей

# # Функция для получения и форматирования информации о ключах пользователя
# async def get_user_keys_info(tg_id: int) -> str:
#     try:
#         async with async_session() as session:
#             keys = await get_keys(session, tg_id)
            
#             if not keys:
#                 return "У пользователя нет активных ключей."
            
#             result = "🔑 <b>Информация о ключах пользователя:</b>\n\n"
            
#             for i, key in enumerate(keys, 1):
#                 expiry_time = key.get('expiry_time', 0)
#                 expiry_date = datetime.utcfromtimestamp(expiry_time / 1000) if expiry_time else datetime.utcnow()
#                 current_date = datetime.utcnow()
#                 time_left = expiry_date - current_date
                
#                 if time_left.total_seconds() <= 0:
#                     status = "❌ истек"
#                 else:
#                     status = f"✅ активен (осталось {time_left.days} дней)"
                
#                 result += (
#                     f"<b>Ключ #{i}:</b>\n"
#                     f"• ID: <code>{key.get('client_id', 'не указан')}</code>\n"
#                     f"• Email: <code>{key.get('email', 'не указан')}</code>\n"
#                     f"• Сервер: <code>{key.get('server_id', 'не указан')}</code>\n"
#                     f"• Статус: {status}\n"
#                     f"• Срок действия до: {expiry_date.strftime('%d.%m.%Y %H:%M')}\n"
#                 )
                
#                 if key.get('tariff_id'):
#                     result += f"• Тариф: {key.get('tariff_id')}\n"
                
#                 result += f"• Заморожен: {'Да' if key.get('is_frozen') else 'Нет'}\n\n"
            
#             return result
#     except Exception as e:
#         import traceback
#         error_details = traceback.format_exc()
#         print(f"Ошибка при получении информации о ключах: {e}\n{error_details}")
#         return f"Ошибка при получении информации о ключах пользователя: {e}"

router = Router()
router.message.filter(
    MagicData(F.event_chat.id == F.config.bot.GROUP_ID),  # type: ignore
    F.chat.type.in_(["group", "supergroup"]),
    F.message_thread_id.is_not(None),
)

@router.message(F.forum_topic_created)
async def handler(message: Message, manager: Manager, redis: RedisStorage) -> None:
    await asyncio.sleep(3)
    user_data = await redis.get_by_message_thread_id(message.message_thread_id)
    if not user_data: return None  # noqa

    # Generate a URL for the user's profile
    url = f"https://t.me/{user_data.username[1:]}" if user_data.username != "-" else f"tg://user?id={user_data.id}"

    # Get the appropriate text based on the user's state
    text = manager.text_message.get("user_started_bot")

    # # Базовое сообщение без информации о ключах
    # base_text = text.format(name=hlink(user_data.full_name, url))

    # try:
    #     # Пытаемся получить информацию о ключах
    #     keys_info = await get_user_keys_info(user_data.id)
    #     full_text = base_text + f"\n\n{keys_info}"
        
    #     message = await message.bot.send_message(
    #         chat_id=manager.config.bot.GROUP_ID,
    #         text=full_text,
    #         message_thread_id=user_data.message_thread_id,
    #         parse_mode="HTML"
    #     )
    # except Exception as e:
    #     import traceback
    #     error_details = traceback.format_exc()
    #     print(f"Ошибка при формировании сообщения с ключами: {e}\n{error_details}")
    #     # Отправляем сообщение без информации о ключах
    #     message = await message.bot.send_message(
    #         chat_id=manager.config.bot.GROUP_ID,
    #         text=base_text,
    #         message_thread_id=user_data.message_thread_id,
    #         parse_mode="HTML"
    #     )

    message = await message.bot.send_message(
        chat_id=manager.config.bot.GROUP_ID,
        text=text.format(name=hlink(user_data.full_name, url)),
        message_thread_id=user_data.message_thread_id
    )

    # Pin the message
    await message.pin()


@router.message(F.pinned_message | F.forum_topic_edited | F.forum_topic_closed | F.forum_topic_reopened)
async def handler(message: Message) -> None:
    """
    Delete service messages such as pinned, edited, closed, or reopened forum topics.

    :param message: Message object.
    :return: None
    """
    await message.delete()


@router.message(F.media_group_id, F.from_user[F.is_bot.is_(False)])
@router.message(F.media_group_id.is_(None), F.from_user[F.is_bot.is_(False)])
async def handler(message: Message, manager: Manager, redis: RedisStorage, album: Optional[Album] = None) -> None:
    """
    Handles user messages and sends them to the respective user.
    If silent mode is enabled for the user, the messages are ignored.

    :param message: Message object.
    :param manager: Manager object.
    :param redis: RedisStorage object.
    :param album: Album object or None.
    :return: None
    """
    user_data = await redis.get_by_message_thread_id(message.message_thread_id)
    if not user_data: return None  # noqa

    if user_data.message_silent_mode:
        # If silent mode is enabled, ignore all messages.
        return

    text = manager.text_message.get("message_sent_to_user")

    try:
        if not album:
            await message.copy_to(chat_id=user_data.id)
        else:
            await album.copy_to(chat_id=user_data.id)

    except TelegramAPIError as ex:
        if "blocked" in ex.message:
            text = manager.text_message.get("blocked_by_user")

    except (Exception,):
        text = manager.text_message.get("message_not_sent")

    # Reply to the edited message with the specified text
    msg = await message.reply(text)
    # Wait for 5 seconds before deleting the reply
    await asyncio.sleep(5)
    # Delete the reply to the edited message
    await msg.delete()
