import gspread
from datetime import datetime
from google.oauth2.service_account import Credentials
from loguru import logger
from models import Expense
from config import settings

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

_worksheet = None


def _get_worksheet():
    global _worksheet
    if _worksheet is None:
        import json
        info = json.loads(settings.GOOGLE_CREDENTIALS_JSON)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(settings.SPREADSHEET_ID)
        _worksheet = sheet.worksheet("Expenses")
        logger.info("Google Sheets connection established")
    return _worksheet


def write_expense(expense: Expense) -> int:
    try:
        ws = _get_worksheet()
        col_c = ws.col_values(3)  # coluna C (Date)
        next_row = len(col_c) + 1

        logger.info(f"Next empty row: {next_row}")

        ws.batch_update([
            {"range": f"C{next_row}", "values": [[expense.date.strftime("%d/%m/%Y")]]},
            {"range": f"E{next_row}", "values": [[expense.description]]},
            {"range": f"H{next_row}", "values": [[expense.category.value]]},
            {"range": f"I{next_row}", "values": [[expense.amount]]},
            {"range": f"L{next_row}", "values": [[expense.notes]]},
        ], value_input_option="USER_ENTERED")

        logger.info(f"Written to row {next_row}: {expense.description}")
        return next_row

    except gspread.exceptions.APIError:
        global _worksheet
        _worksheet = None
        raise


def _parse_amount(raw: str) -> float | None:
    """Converte '40,00 €', '40.00', '40' → float. Retorna None se inválido."""
    try:
        cleaned = raw.strip().replace("€", "").replace(" ", "").replace(",", ".")
        value = float(cleaned) if cleaned else 0
        return value if value > 0 else None
    except ValueError:
        return None


def read_expenses(month: int = None, year: int = None, category: str = None) -> list[dict]:
    ws = _get_worksheet()
    rows = ws.get_all_values()

    logger.info(f"read_expenses: total rows={len(rows)}")
    shown = 0
    for i, r in enumerate(rows):
        if any(v.strip() for v in r) and shown < 6:
            logger.debug(f"  row[{i}] = {r}")
            shown += 1

    # Colunas (0-indexed): C=2 data, E=4 descrição, H=7 categoria, I=8 valor
    expenses = []
    for row in rows:
        if len(row) < 9:
            continue
        date_str = row[2].strip()
        if not date_str:
            continue
        try:
            date = datetime.strptime(date_str, "%d/%m/%Y")
        except ValueError:
            continue

        if month and date.month != month:
            continue
        if year and date.year != year:
            continue

        cat = row[7].strip() if len(row) > 7 else ""
        if category and cat.lower() != category.lower():
            continue

        amount = _parse_amount(row[8]) if len(row) > 8 else None
        if amount is None:
            continue

        expenses.append({
            "date": date_str,
            "description": row[4].strip() if len(row) > 4 else "",
            "category": cat,
            "amount": amount,
        })

    # Agrega totais em Python para evitar erros aritméticos do modelo
    total = round(sum(e["amount"] for e in expenses), 2)
    by_category: dict[str, float] = {}
    for e in expenses:
        by_category[e["category"]] = round(by_category.get(e["category"], 0) + e["amount"], 2)

    logger.info(f"read_expenses: {len(expenses)} rows, total={total} (month={month}, year={year}, category={category})")
    return {
        "total": total,
        "count": len(expenses),
        "by_category": dict(sorted(by_category.items(), key=lambda x: x[1], reverse=True)),
        "expenses": expenses,
    }
