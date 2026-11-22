"""Fast callback helpers and single-panel inline UI cleanup for Norin AI Bot."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Coroutine, Dict, Optional, Set, Tuple

from aiogram import Bot
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)

# Per-chat state: {chat_id: (last_inline_msg_id, should_delete_on_replace)}
_ACTIVE_PANELS: Dict[int, Tuple[int, bool]] = {}
_CHATS_WITH_ONE_TIME_KB: Set[int] = set()
_BG_TASKS: Set[asyncio.Task[Any]] = set()


def _track_task(coro: Coroutine[Any, Any, Any]) -> None:
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)


def mark_reply_kb_sent(chat_id: Optional[int]) -> None:
    """Record that this private chat received the collapsible main menu ReplyKeyboard."""
    if chat_id is not None:
        _CHATS_WITH_ONE_TIME_KB.add(int(chat_id))


def clear_active_panel(chat_id: Optional[int]) -> None:
    """Clear active inline panel tracking for chat_id (e.g. after dismiss or returning home)."""
    if chat_id is not None:
        _ACTIVE_PANELS.pop(int(chat_id), None)


async def _cleanup_previous_panel(
    bot: Bot, chat_id: int, msg_id: int, delete_msg: bool
) -> None:
    """Delete an obsolete navigation panel or strip buttons from a previous report."""
    with contextlib.suppress(Exception):
        if delete_msg:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        else:
            await bot.edit_message_reply_markup(
                chat_id=chat_id, message_id=msg_id, reply_markup=None
            )


async def _hide_sticky_reply_keyboard(bot: Bot, chat_id: int) -> None:
    """Dismiss any legacy persistent ReplyKeyboard without leaving clutter in chat."""
    with contextlib.suppress(Exception):
        stub = await bot.send_message(
            chat_id=chat_id,
            text="⚡",
            reply_markup=ReplyKeyboardRemove(),
            disable_notification=True,
        )
        await bot.delete_message(chat_id=chat_id, message_id=stub.message_id)


async def send_inline_panel(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup,
    *,
    delete_prev: bool = False,
    force_hide_kb: bool = False,
) -> Message:
    """
    Send a top-level inline panel while cleaning up the previous active inline menu in the
    background and ensuring any legacy sticky ReplyKeyboard is dismissed.
    """
    chat_id = int(message.chat.id)
    prev = _ACTIVE_PANELS.pop(chat_id, None)
    if prev is not None:
        prev_msg_id, prev_delete = prev
        _track_task(_cleanup_previous_panel(message.bot, chat_id, prev_msg_id, prev_delete))

    if force_hide_kb or chat_id not in _CHATS_WITH_ONE_TIME_KB:
        await _hide_sticky_reply_keyboard(message.bot, chat_id)
        _CHATS_WITH_ONE_TIME_KB.add(chat_id)

    sent = await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=reply_markup,
    )
    _ACTIVE_PANELS[chat_id] = (sent.message_id, delete_prev)
    return sent


async def fast_edit(
    cb: CallbackQuery,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    alert_text: Optional[str] = None,
    show_alert: bool = False,
) -> None:
    """Edit message text and answer CallbackQuery concurrently to halve round-trip latency."""
    results = await asyncio.gather(
        cb.message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup),
        cb.answer(alert_text, show_alert=show_alert) if alert_text else cb.answer(),
        return_exceptions=True,
    )
    edit_res = results[0]
    if isinstance(edit_res, Exception):
        if "message is not modified" not in str(edit_res).lower():
            raise edit_res
