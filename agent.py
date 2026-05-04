import json
import anthropic
from datetime import datetime
from loguru import logger
from models import Expense, Category, Income, IncomeSource
from config import settings

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

TOOLS = [
    {
        "name": "register_expense",
        "description": "Extrai e prepara uma despesa para registo. Usa esta ferramenta quando o utilizador descreve uma compra ou despesa.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Descrição curta da despesa"
                },
                "amount": {
                    "type": "number",
                    "description": "Valor da despesa em euros"
                },
                "category": {
                    "type": "string",
                    "enum": [c.value for c in Category],
                    "description": "Categoria da despesa"
                },
                "subscription": {
                    "type": "boolean",
                    "description": "True se for uma subscrição recorrente"
                },
                "date": {
                    "type": "string",
                    "description": "Data da despesa em dd/mm/yyyy. Inferir de expressões temporais (ex: 'ontem', 'dia 5'). Omitir se não mencionada."
                },
                "notes": {
                    "type": "string",
                    "description": "Notas opcionais sobre a despesa"
                }
            },
            "required": ["description", "amount", "category", "subscription"]
        }
    },
    {
        "name": "query_expenses",
        "description": "Consulta o histórico de despesas registadas. Usa esta ferramenta quando o utilizador pergunta sobre os seus gastos, totais, histórico, ou quer saber quanto gastou.",
        "input_schema": {
            "type": "object",
            "properties": {
                "month": {
                    "type": "integer",
                    "description": "Mês (1-12). Omitir para todos os meses."
                },
                "year": {
                    "type": "integer",
                    "description": "Ano (ex: 2026). Omitir para o ano atual."
                },
                "category": {
                    "type": "string",
                    "description": "Filtrar por categoria. Omitir para todas as categorias."
                },
            }
        }
    },
    {
        "name": "register_income",
        "description": "Regista ou atualiza o valor de uma fonte de income num mês. Usa quando o utilizador menciona que recebeu salário, subsídio, ofertas, side hustle, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "enum": [s.value for s in IncomeSource],
                    "description": "Fonte do income"
                },
                "amount": {
                    "type": "number",
                    "description": "Valor recebido em euros"
                },
                "month": {
                    "type": "integer",
                    "description": "Mês (1-12). Por defeito o mês atual."
                },
                "year": {
                    "type": "integer",
                    "description": "Ano. Por defeito o ano atual."
                }
            },
            "required": ["source", "amount"]
        }
    },
    {
        "name": "query_income",
        "description": "Consulta o income registado num mês. Usa quando o utilizador pergunta quanto recebeu, qual o balanço do mês (income vs despesas), ou quer ver o breakdown de income.",
        "input_schema": {
            "type": "object",
            "properties": {
                "month": {
                    "type": "integer",
                    "description": "Mês (1-12). Por defeito o mês atual."
                },
                "year": {
                    "type": "integer",
                    "description": "Ano. Por defeito o ano atual."
                }
            }
        }
    }
]


def _build_system_prompt() -> str:
    today = datetime.now()
    return f"""És um assistente de controlo de despesas e income pessoais.
Respondes sempre no mesmo idioma que o utilizador escreve.

Tens quatro ferramentas:
1. register_expense — quando o utilizador descreve uma compra ou despesa
2. query_expenses — quando o utilizador pergunta sobre os seus gastos ou histórico
3. register_income — quando o utilizador menciona que recebeu dinheiro (salário, subsídio, ofertas, side hustle, etc.)
4. query_income — quando o utilizador pergunta quanto recebeu ou quer ver o balanço do mês

Se a mensagem não for uma despesa, income, nem uma consulta, responde naturalmente sem usar ferramentas.

Hoje é {today.strftime("%d/%m/%Y")} ({today.strftime("%A")}). Para datas relativas:
- "hoje" → {today.strftime("%d/%m/%Y")}
- "ontem" → calcula a data de ontem
- "amanhã" → calcula a data de amanhã
- "dia X" ou "X de mês" → resolve para a ocorrência mais recente
Se não for mencionada data, omite o campo date.

Regras de categoria:
- Uber/Bolt/taxi → Uber
- Gas/gasolina/gasóleo → Fuel
- Supermercado/Continente/Lidl/Auchan → Groceries
- Restaurante/café/sushi/mcdonalds → Eating out
- Netflix/Spotify/subscrições mensais → Subscriptions (subscription=true)
- Médico/farmácia/dentista → Healthcare
- Impressora/pokemon/hobbies → Hobbies
- Carro/pneus/multa/estacionamento → Car
- Roupa/sapatos → Clothes
- Prendas/presentes → Gifts
- Metro/bus/comboio → Transport
- Cabeleireiro/barbeiro/cosmética → Beauty
- Viagens/hotel/voos/férias → Holidays
- Qualquer coisa sem categoria clara → Miscellaneous

Regras de income source:
- Salário/ordenado → Salary
- Prenda/oferta em dinheiro → Gifts
- Freelance/trabalho extra/side hustle → Side Hustle
- Subsídio de alimentação/refeição → Subsidio
- Cartão refeição/meal card → Meal Card
- Saldo transportado do mês anterior → CarryOver
- Ajuste/reconciliação → Ajuste de Reconciliação

Ao responder a consultas de despesas:
- Usa SEMPRE os campos "total" e "by_category" do resultado da ferramenta — nunca somes os valores tu próprio
- Apresenta os totais de forma clara e organizada
- Usa formatação Markdown (negrito, listas)
- Indica o período consultado
- Se relevante, mostra o breakdown por categoria

Ao responder a consultas de income ou balanço:
- Usa os campos "total" e "by_source" do resultado da ferramenta
- Para balanço (income vs despesas), chama query_income e query_expenses separadamente e mostra: income total, despesas total, e saldo (income - despesas)"""


def _build_expense_from_tool(data: dict) -> Expense:
    date = None
    if raw_date := data.get("date"):
        try:
            date = datetime.strptime(raw_date, "%d/%m/%Y")
        except ValueError:
            logger.warning(f"Could not parse date '{raw_date}', using today")

    return Expense(
        date=date,
        description=data["description"],
        amount=data["amount"],
        category=data["category"],
        subscription=data.get("subscription", False),
        notes=data.get("notes", "")
    )


def run_agent(user_message: str, history: list | None = None) -> dict:
    """
    Corre o loop do agente.
    Retorna:
      {"type": "expense", "expense": Expense}  — para mostrar confirmação
      {"type": "text", "text": str}             — resposta direta ao utilizador
    """
    from sheets_handler import read_expenses, write_income, read_income

    today = datetime.now()
    messages = list(history) if history else []
    messages.append({"role": "user", "content": user_message})
    logger.info(f"Agent started: {user_message}")

    while True:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=_build_system_prompt(),
            tools=TOOLS,
            messages=messages
        )

        logger.debug(f"Agent stop_reason: {response.stop_reason}")

        # Sem tool call — resposta de texto direta
        if response.stop_reason == "end_turn":
            text = " ".join(
                block.text for block in response.content
                if hasattr(block, "text")
            ).strip()
            return {"type": "text", "text": text or "Não percebi. Tenta descrever uma despesa ou pergunta sobre os teus gastos."}

        if response.stop_reason != "tool_use":
            return {"type": "text", "text": "Não percebi. Tenta descrever uma despesa ou pergunta sobre os teus gastos."}

        # Processar tool calls
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            if block.name == "register_expense":
                # Interrompe o loop — devolve despesa para confirmação
                expense = _build_expense_from_tool(block.input)
                logger.info(f"Expense extracted: {expense.description} €{expense.amount}")
                return {"type": "expense", "expense": expense}

            if block.name == "query_expenses":
                filters = block.input
                logger.info(f"Querying expenses: {filters}")
                data = read_expenses(
                    month=filters.get("month"),
                    year=filters.get("year"),
                    category=filters.get("category"),
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(data, ensure_ascii=False),
                })

            if block.name == "register_income":
                inp = block.input
                month = inp.get("month") or today.month
                year = inp.get("year") or today.year
                income = Income(
                    month=month,
                    year=year,
                    source=inp["source"],
                    amount=inp["amount"],
                )
                logger.info(f"Income registered: {income.source.value} €{income.amount} ({month}/{year})")
                write_income(income)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps({
                        "ok": True,
                        "source": income.source.value,
                        "amount": income.amount,
                        "month": month,
                        "year": year,
                    }),
                })

            if block.name == "query_income":
                inp = block.input
                month = inp.get("month") or today.month
                logger.info(f"Querying income: month={month}")
                data = read_income(month=month)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(data, ensure_ascii=False),
                })

        if not tool_results:
            return {"type": "text", "text": "Não percebi. Tenta descrever uma despesa ou pergunta sobre os teus gastos."}

        # Continua o loop com os resultados das ferramentas
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})


# Alias para compatibilidade — não usado internamente
def parse_expense(user_message: str) -> Expense | None:
    result = run_agent(user_message)
    if result["type"] == "expense":
        return result["expense"]
    return None
