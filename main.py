import sys
import asyncio
from loguru import logger
from pydantic import ValidationError
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from agent import run_agent
from sheets_handler import write_expense
from config import settings

logger.remove()
logger.add(sys.stdout, level=settings.LOG_LEVEL, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")
logger.add("logs/expense_bot.log", rotation="1 week", retention="1 month", level="DEBUG")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Olá! Sou o teu assistente de despesas.\n\n"
        "Envia-me uma despesa como:\n"
        "• *café 1.50*\n"
        "• *uber para o aeroporto 12€*\n"
        "• *gasolina 40€*\n"
        "• *continente 23.50*\n\n"
        "Vou registar tudo automaticamente no Google Sheets! 📊",
        parse_mode="Markdown"
    )


def _confirmation_text(expense) -> str:
    subscription_text = "✅ Sim" if expense.subscription else "❌ Não"
    return (
        f"*Confirmar despesa?*\n\n"
        f"📝 {expense.description}\n"
        f"🏷️ {expense.category.value}\n"
        f"💶 €{expense.amount:.2f}\n"
        f"🔄 Subscrição: {subscription_text}\n"
        f"📅 {expense.date.strftime('%d/%m/%Y')}"
    )


def _confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirmar", callback_data="confirm"),
            InlineKeyboardButton("❌ Cancelar", callback_data="cancel"),
        ],
        [
            InlineKeyboardButton("✏️ Editar", callback_data="edit"),
        ]
    ])


def _edit_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏷️ Categoria", callback_data="edit_category")],
        [InlineKeyboardButton("← Voltar", callback_data="back_to_confirm")],
    ])


def _category_keyboard() -> InlineKeyboardMarkup:
    from models import Category
    categories = list(Category)
    buttons = []
    row = []
    for cat in categories:
        row.append(InlineKeyboardButton(cat.value, callback_data=f"cat_{cat.name}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("← Voltar", callback_data="edit")])
    return InlineKeyboardMarkup(buttons)


_HISTORY_MAX = 4  # 2 exchanges × 2 messages each


def _trim_history(history: list) -> list:
    return history[-_HISTORY_MAX:]


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    user_id = update.message.from_user.id
    username = update.message.from_user.username

    logger.info(f"Message from {username} ({user_id}): {user_message}")

    await update.message.reply_chat_action("typing")

    try:
        history = context.user_data.get("history", [])
        result = run_agent(user_message, history=history)

        if result["type"] == "text":
            await update.message.reply_text(result["text"], parse_mode="Markdown")
            context.user_data["history"] = _trim_history(
                history + [
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": result["text"]},
                ]
            )
            return

        expense = result["expense"]
        context.user_data["pending_expense"] = expense
        context.user_data["pending_user_message"] = user_message

        await update.message.reply_text(
            _confirmation_text(expense),
            parse_mode="Markdown",
            reply_markup=_confirmation_keyboard()
        )

    except ValidationError:
        await update.message.reply_text(
            "Não consegui detetar o valor da despesa.\n"
            "Tenta incluir o preço, por exemplo: *Gasolina 20€*",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.exception(f"Error processing message: {e}")
        await update.message.reply_text(
            "❌ Ocorreu um erro ao processar a despesa. Tenta novamente."
        )


async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    try:
        await query.answer()
    except BadRequest:
        return

    data = query.data

    # Editar categoria: atualiza e volta à confirmação
    if data.startswith("cat_"):
        from models import Category
        cat_name = data[4:]
        expense = context.user_data.get("pending_expense")
        if expense is None:
            return
        try:
            expense.category = Category[cat_name]
        except KeyError:
            return
        await query.edit_message_text(
            _confirmation_text(expense),
            parse_mode="Markdown",
            reply_markup=_confirmation_keyboard()
        )
        return

    if data == "edit":
        expense = context.user_data.get("pending_expense")
        if expense is None:
            return
        await query.edit_message_text(
            f"*O que queres editar?*\n\n"
            f"📝 {expense.description} — €{expense.amount:.2f}",
            parse_mode="Markdown",
            reply_markup=_edit_menu_keyboard()
        )
        return

    if data == "edit_category":
        expense = context.user_data.get("pending_expense")
        if expense is None:
            return
        await query.edit_message_text(
            f"*Escolhe a nova categoria:*\n\n"
            f"Categoria atual: *{expense.category.value}*",
            parse_mode="Markdown",
            reply_markup=_category_keyboard()
        )
        return

    if data == "back_to_confirm":
        expense = context.user_data.get("pending_expense")
        if expense is None:
            return
        await query.edit_message_text(
            _confirmation_text(expense),
            parse_mode="Markdown",
            reply_markup=_confirmation_keyboard()
        )
        return

    # Confirm ou cancel — remove a despesa pendente
    expense = context.user_data.pop("pending_expense", None)
    if expense is None:
        return

    if data == "confirm":
        await query.edit_message_text(
            f"⏳ *A registar...*\n\n"
            f"📝 {expense.description}\n"
            f"💶 €{expense.amount:.2f}",
            parse_mode="Markdown"
        )
        try:
            loop = asyncio.get_event_loop()
            row = await loop.run_in_executor(None, write_expense, expense)
            subscription_text = "✅ Sim" if expense.subscription else "❌ Não"
            await query.edit_message_text(
                f"✅ *Despesa registada!*\n\n"
                f"📝 {expense.description}\n"
                f"🏷️ {expense.category.value}\n"
                f"💶 €{expense.amount:.2f}\n"
                f"🔄 Subscrição: {subscription_text}\n"
                f"📅 {expense.date.strftime('%d/%m/%Y')}\n"
                f"_Linha #{row} no Google Sheets_",
                parse_mode="Markdown"
            )
            logger.info(f"Expense confirmed and written to row {row}: {expense.description}")
            pending_user_message = context.user_data.pop("pending_user_message", None)
            if pending_user_message is not None:
                assistant_summary = (
                    f"Despesa registada: {expense.description} €{expense.amount:.2f} "
                    f"({expense.category.value}, {expense.date.strftime('%d/%m/%Y')})"
                )
                context.user_data["history"] = _trim_history(
                    context.user_data.get("history", []) + [
                        {"role": "user", "content": pending_user_message},
                        {"role": "assistant", "content": assistant_summary},
                    ]
                )
        except Exception as e:
            logger.exception(f"Error writing expense: {e}")
            context.user_data.pop("pending_user_message", None)
            await query.edit_message_text(
                "❌ Ocorreu um erro ao registar a despesa. Tenta novamente."
            )
    else:
        await query.edit_message_text("❌ *Despesa cancelada.*", parse_mode="Markdown")
        logger.info(f"Expense cancelled: {expense.description}")
        context.user_data.pop("pending_user_message", None)


def main():
    logger.info("Starting Expense Bot...")

    app = ApplicationBuilder().token(settings.TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_confirmation))

    logger.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
