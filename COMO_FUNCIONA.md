# Como Funciona o Expense Bot — Guia Completo de IA, Agentes e Arquitectura

Este documento explica em profundidade tudo o que este projecto usa e tudo o que poderia usar. Serve como guia de estudo para perceber como a IA moderna, agentes, ferramentas e servidores de IA funcionam na prática.

---

## Índice

1. [Visão Geral do Projecto](#1-visão-geral-do-projecto)
2. [Large Language Models — O que são e como funcionam](#2-large-language-models--o-que-são-e-como-funcionam)
3. [A Família de Modelos Anthropic (Claude)](#3-a-família-de-modelos-anthropic-claude)
4. [A API da Anthropic — Como comunicar com o modelo](#4-a-api-da-anthropic--como-comunicar-com-o-modelo)
5. [Tool Use / Function Calling — Como o modelo age no mundo](#5-tool-use--function-calling--como-o-modelo-age-no-mundo)
6. [O Agente deste Projecto — O Loop Agentic](#6-o-agente-deste-projecto--o-loop-agentic)
7. [System Prompts — Como dar personalidade e regras ao modelo](#7-system-prompts--como-dar-personalidade-e-regras-ao-modelo)
8. [O Bot de Telegram — Arquitectura e Funcionamento](#8-o-bot-de-telegram--arquitectura-e-funcionamento)
9. [Google Sheets como Base de Dados](#9-google-sheets-como-base-de-dados)
10. [Pydantic — Validação de Dados entre IA e Código](#10-pydantic--validação-de-dados-entre-ia-e-código)
11. [MCP — Model Context Protocol](#11-mcp--model-context-protocol)
12. [Servidores de IA e Providers](#12-servidores-de-ia-e-providers)
13. [Melhorias Possíveis e Conceitos Avançados](#13-melhorias-possíveis-e-conceitos-avançados)

---

## 1. Visão Geral do Projecto

O Expense Bot é um assistente de finanças pessoais que vive no Telegram. Envias uma mensagem em linguagem natural ("sushi 40€ ontem") e ele:

1. Envia o texto para o Claude (modelo de IA da Anthropic)
2. O Claude extrai as informações estruturadas (valor, categoria, data)
3. O bot pede confirmação com botões interactivos
4. Ao confirmar, regista numa folha do Google Sheets

**Fluxo de dados simplificado:**

```
Utilizador (Telegram)
       ↓ mensagem de texto
  main.py (bot)
       ↓ texto livre
  agent.py (agente IA)
       ↓ chamada HTTP
  API Anthropic (Claude Haiku)
       ↓ tool_use: register_expense
  agent.py (interpreta resultado)
       ↓ objecto Expense validado
  main.py (mostra confirmação)
       ↓ botão "Confirmar"
  sheets_handler.py
       ↓ escrita HTTP
  Google Sheets
```

---

## 2. Large Language Models — O que são e como funcionam

### O que é um LLM

Um **Large Language Model** (Modelo de Linguagem de Grande Escala) é uma rede neuronal treinada em enormes quantidades de texto. O seu único objectivo durante o treino foi prever qual a próxima palavra (ou "token") mais provável dado um contexto.

Desta tarefa aparentemente simples emergem capacidades surpreendentes: raciocínio, tradução, escrita de código, extracção de informação, e muito mais.

### Tokens — A unidade de trabalho

Os LLMs não processam caracteres nem palavras directamente — processam **tokens**. Um token é, grosso modo, uma parte de uma palavra. Por exemplo:

- "despesa" → 1 token
- "reconhecimento" → 2-3 tokens
- "€" → 1 token
- " 40.50" → 2-3 tokens

**Porquê importa?** Porque os modelos têm um limite de tokens por chamada (o "context window"), e o custo das APIs é medido em tokens consumidos (input + output).

### Como o modelo "pensa"

O modelo não pensa de forma linear como um humano. Cada resposta é gerada **token a token**, onde cada token novo é escolhido com base em todos os tokens anteriores. Internamente, usa **atenção** (o mecanismo por detrás do "transformer") para pescar padrões e relações em toda a sequência de contexto.

Quando vês `claude-haiku-4-5-20251001` a responder em português com regras de categorização, não está a "executar código" — está a prever qual a sequência de tokens mais coerente com o contexto que lhe deste.

### Temperature e determinismo

Os LLMs têm um parâmetro chamado **temperature**:
- `temperature=0` → resposta quase determinista (sempre escolhe o token mais provável)
- `temperature=1` → mais criativo e variado

Para extracção de dados (como neste projecto), baixa temperatura é melhor para consistência.

---

## 3. A Família de Modelos Anthropic (Claude)

A Anthropic organiza os seus modelos em três níveis de capacidade/custo:

### Haiku — Rápido e Barato
```
claude-haiku-4-5-20251001  ← usado neste projecto
```
- Mais rápido e barato
- Ideal para tarefas simples e bem definidas: extracção de dados, classificação, formatação
- Para este projecto é a escolha correcta: a tarefa é extrair campos de uma frase curta

### Sonnet — Equilíbrio
```
claude-sonnet-4-6
```
- Equilíbrio entre velocidade, custo e capacidade
- Melhor para raciocínio mais complexo, código, análise
- Seria útil se quisesses análise financeira mais sofisticada

### Opus — Mais Capaz
```
claude-opus-4-7
```
- O modelo mais capaz
- Para tarefas complexas: raciocínio em múltiplos passos, planeamento, investigação
- Mais lento e caro

### Context Window
Cada modelo tem um limite de contexto (quantos tokens cabem numa conversa). Actualmente os modelos Claude suportam até **200.000 tokens** de contexto — o equivalente a um livro inteiro. Para este projecto, nunca chegas perto desse limite.

---

## 4. A API da Anthropic — Como comunicar com o modelo

### A estrutura de uma chamada

Cada chamada à API é um HTTP POST para `https://api.anthropic.com/v1/messages`. O corpo da chamada tem este formato:

```python
client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=1024,
    system="...",          # instrução global para o modelo
    messages=[             # histórico da conversa
        {"role": "user",   "content": "sushi 40€ ontem"},
        {"role": "assistant", "content": "..."},  # resposta anterior
        # ...
    ],
    tools=[...]            # lista de ferramentas disponíveis
)
```

### Os roles das mensagens

Uma conversa com Claude é uma lista de turnos alternados:

| Role | Quem escreve | Conteúdo |
|------|-------------|---------|
| `user` | Tu / o teu código | Mensagem do utilizador, ou resultado de uma tool |
| `assistant` | Claude | Resposta de texto, ou pedido para usar uma tool |

A conversa é **stateless** — cada chamada à API envia todo o histórico desde o início. O modelo não "lembra" — és tu quem tem de guardar e reenviar o histórico.

### Stop reasons — Porque parou o modelo?

Quando o modelo responde, devolve um `stop_reason` que indica porque parou:

| stop_reason | Significado |
|-------------|-------------|
| `end_turn` | O modelo terminou a resposta naturalmente |
| `tool_use` | O modelo quer usar uma ferramenta |
| `max_tokens` | Atingiu o limite de tokens definido |
| `stop_sequence` | Encontrou uma sequência de paragem definida por ti |

No `agent.py` deste projecto, o loop verifica exactamente estes dois casos: `tool_use` (processa a ferramenta) ou `end_turn` (devolve a resposta ao utilizador).

### Blocos de conteúdo

A resposta de Claude não é apenas texto — é uma lista de **blocos de conteúdo**. Cada bloco tem um tipo:

```python
# Bloco de texto
{"type": "text", "text": "Aqui está o resumo..."}

# Bloco de tool use
{"type": "tool_use", "id": "toolu_01...", "name": "register_expense", "input": {...}}
```

O `agent.py` itera sobre estes blocos para encontrar pedidos de ferramentas.

---

## 5. Tool Use / Function Calling — Como o modelo age no mundo

### O problema fundamental

Um LLM puro só pode gerar texto. Mas para ser útil em aplicações reais, precisa de interagir com sistemas externos: bases de dados, APIs, ficheiros, calculadoras.

**Tool Use** (também chamado Function Calling noutros sistemas) resolve isso: defines funções disponíveis, e o modelo pode "pedir" que as executes.

### Como funciona — passo a passo

**1. Tu defines as ferramentas em JSON Schema:**

```python
tools = [
    {
        "name": "register_expense",
        "description": "Regista uma nova despesa",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "amount": {"type": "number"},
                "category": {"type": "string", "enum": ["Groceries", "Fuel", ...]}
            },
            "required": ["description", "amount", "category"]
        }
    }
]
```

**2. Envias as ferramentas na chamada à API.**

**3. O modelo decide se precisa de usar uma ferramenta.** Se sim, em vez de responder com texto, responde com um bloco `tool_use`:

```json
{
  "type": "tool_use",
  "id": "toolu_01abc123",
  "name": "register_expense",
  "input": {
    "description": "Sushi",
    "amount": 40.0,
    "category": "Eating out",
    "date": "30/04/2025"
  }
}
```

**4. O modelo pára e espera.** O `stop_reason` é `"tool_use"`.

**5. Tu executa a função com esses argumentos** (no caso deste projecto, `sheets_handler.write_expense()`).

**6. Adicionas o resultado de volta à conversa** com role `user` e tipo `tool_result`:

```python
{
    "role": "user",
    "content": [{
        "type": "tool_result",
        "tool_use_id": "toolu_01abc123",
        "content": json.dumps({"success": True, "row": 156})
    }]
}
```

**7. Voltas a chamar o modelo**, que agora conhece o resultado e pode responder ao utilizador.

### JSON Schema — A linguagem de definição de ferramentas

O JSON Schema é um standard para descrever a estrutura de dados JSON. É o que usas para dizer ao modelo que campos aceita cada ferramenta e de que tipo são.

```json
{
  "type": "object",
  "properties": {
    "amount":   {"type": "number",  "description": "Valor em euros"},
    "category": {"type": "string",  "enum": ["Groceries", "Fuel"]},
    "date":     {"type": "string",  "pattern": "\\d{2}/\\d{2}/\\d{4}"}
  },
  "required": ["amount", "category"]
}
```

O modelo usa esta descrição para preencher correctamente os campos. Quanto mais clara for a `description`, mais preciso o modelo é.

### Por que o modelo não soma — e por que o projecto avisa disso

No system prompt há uma instrução explícita: "usa sempre os campos `total` e `by_category` do resultado da tool — nunca somes no teu lado."

Porquê? Os LLMs são **maus a fazer aritmética**. Não calculam — completam padrões. "1+1=2" funciona porque esse padrão é comum no treino. Mas somar 152 valores com casas decimais é arriscado. A soma deve sempre ser feita em código Python, e o modelo apenas formata e apresenta o resultado.

---

## 6. O Agente deste Projecto — O Loop Agentic

### O que é um agente

Um **agente** é um sistema onde o modelo de IA controla o fluxo de execução, decidindo que acções tomar em resposta a um objectivo. Ao contrário de uma chamada simples (pergunta → resposta), um agente pode:

- Usar ferramentas múltiplas vezes
- Tomar decisões com base nos resultados
- Fazer múltiplas chamadas ao modelo até completar a tarefa

### O loop do `agent.py`

```python
async def run_agent(user_message: str) -> dict:
    messages = [{"role": "user", "content": user_message}]

    while True:
        response = client.messages.create(
            model=MODEL,
            system=_build_system_prompt(),
            messages=messages,
            tools=TOOLS,
        )

        if response.stop_reason == "end_turn":
            # Modelo respondeu com texto → devolver ao utilizador
            return {"type": "text", "text": response.content[0].text}

        if response.stop_reason == "tool_use":
            # Modelo quer usar uma ferramenta
            for block in response.content:
                if block.type == "tool_use":

                    if block.name == "register_expense":
                        # Extracção de despesa → não executa ainda, devolve para confirmação
                        expense = _build_expense_from_tool(block.input)
                        return {"type": "expense", "expense": expense}

                    if block.name == "query_expenses":
                        # Consulta → executa e continua o loop
                        result = read_expenses(**block.input)
                        messages.append({"role": "assistant", "content": response.content})
                        messages.append({
                            "role": "user",
                            "content": [{"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result)}]
                        })
                        break  # volta ao início do while
```

**Nota importante:** Para `register_expense`, o agente **não executa a escrita** — apenas extrai os dados e devolve para o utilizador confirmar. A escrita real acontece em `main.py` quando o utilizador carrega "Confirmar". Isto é uma boa prática: nunca executar acções irreversíveis sem confirmação humana.

### As duas ferramentas

**`register_expense`** — Extracção de linguagem natural para estrutura:
```
"sushi 40€ ontem" 
    → description="Sushi", amount=40.0, category="Eating out", date="30/04/2025"
```

**`query_expenses`** — Consulta com filtros:
```
"quanto gastei em gasolina em março?"
    → query_expenses(category="Fuel", month=3, year=2025)
    → resultado do Google Sheets
    → Claude formata a resposta
```

### Diagrama do loop

```
user: "sushi 40€ ontem"
         │
         ▼
   Claude analisa
         │
   stop_reason="tool_use"
   tool="register_expense"
         │
         ▼
   agent.py extrai Expense
         │
         ▼
   main.py mostra confirmação  ←── loop termina aqui para este caso
         │
   [utilizador confirma]
         │
         ▼
   sheets_handler.write_expense()
```

```
user: "quanto gastei em abril?"
         │
         ▼
   Claude analisa
         │
   stop_reason="tool_use"
   tool="query_expenses"
         │
         ▼
   sheets_handler.read_expenses()
         │
         ▼
   resultado adicionado à conversa
         │
         ▼
   Claude analisa resultado
         │
   stop_reason="end_turn"
         │
         ▼
   Resposta formatada ao utilizador
```

---

## 7. System Prompts — Como dar personalidade e regras ao modelo

### O que é um system prompt

O **system prompt** é uma instrução que aparece antes de qualquer mensagem do utilizador. Define o comportamento, personalidade, e regras do modelo para toda a conversa. É como um contrato entre ti e o modelo.

### O system prompt deste projecto

Faz várias coisas em simultâneo:

**1. Define o papel:**
```
"És um assistente de finanças pessoais. O utilizador fala português."
```

**2. Regras de categorização:**
```
"Uber, Bolt → categoria Uber
 Continente, Pingo Doce, Lidl → categoria Groceries
 Restaurante, sushi, pizza → categoria Eating out"
```
Sem estas regras, o modelo poderia categorizar "Pingo Doce" como "Miscellaneous".

**3. Interpretação de datas:**
```
"'ontem' = hoje - 1 dia
 'dia 15' = dia 15 do mês actual
 Se não mencionado, usar a data de hoje"
```

**4. Regras de aritmética:**
```
"Nunca somes valores tu mesmo. Usa sempre os campos total e by_category 
 devolvidos pela ferramenta query_expenses."
```

**5. Formato de resposta:**
```
"Usa Markdown para formatar as respostas."
```

### Boas práticas de system prompts

- **Sê específico, não genérico.** "Classifica despesas de transporte como Transport" é melhor que "sê inteligente com categorias".
- **Exemplos concretos.** Modelos aprendem por padrão — dar exemplos é mais eficaz que descrições abstractas.
- **Define o que NÃO fazer.** Às vezes é tão importante como o que fazer.
- **Separa responsabilidades.** O model não deve fazer aritmética se podes fazê-la em código.

---

## 8. O Bot de Telegram — Arquitectura e Funcionamento

### Polling vs Webhooks

Há duas formas de receber mensagens do Telegram:

**Polling (usado neste projecto):**
```
Bot → [a cada segundo] "Telegram, tens mensagens novas?"
Telegram → "Sim, estas aqui"
```
- Simples de implementar
- O bot inicia a ligação
- Funciona atrás de firewalls/NAT
- Desvantagem: ligeiro atraso, mais chamadas de rede

**Webhooks (alternativa):**
```
Telegram → [quando há mensagem] POST https://o-teu-servidor/webhook
```
- Telegram contacta o teu servidor directamente
- Mais eficiente (zero polling)
- Requer HTTPS e URL pública
- Melhor para produção com alto volume

### Handlers — Como o bot reage a eventos

O `python-telegram-bot` usa um sistema de handlers:

```python
app.add_handler(CommandHandler("start", start))
# Quando o utilizador escreve /start → chama a função start()

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
# Quando o utilizador escreve texto (não comando) → chama handle_message()

app.add_handler(CallbackQueryHandler(handle_confirmation))
# Quando o utilizador carrega num botão inline → chama handle_confirmation()
```

### Inline Keyboards — Botões interactivos

Os botões no Telegram funcionam com **callback data** — cada botão tem um identificador que é enviado ao bot quando clicado:

```python
InlineKeyboardButton("✅ Confirmar", callback_data="confirm")
InlineKeyboardButton("❌ Cancelar",  callback_data="cancel")
InlineKeyboardButton("✏️ Editar",    callback_data="edit")
```

Quando o utilizador carrega em "Confirmar", o Telegram envia ao bot um `CallbackQuery` com `data="confirm"`. O `handle_confirmation()` verifica este valor e age em conformidade.

### Estado entre mensagens — O problema

Os bots de Telegram são **stateless** por natureza. Quando o utilizador carrega "Confirmar", como é que o bot sabe qual a despesa que estava a confirmar?

O projecto guarda o estado no `context.user_data` do python-telegram-bot, que mantém um dicionário por utilizador em memória:

```python
# Ao mostrar confirmação:
context.user_data["pending_expense"] = expense

# Ao confirmar:
expense = context.user_data.get("pending_expense")
```

**Limitação:** Este estado vive apenas em memória. Se o bot reiniciar, perde-se. Uma solução mais robusta seria usar Redis ou uma base de dados.

---

## 9. Google Sheets como Base de Dados

### Service Accounts — Autenticação sem utilizador

Para o bot aceder ao Google Sheets sem intervenção humana (sem janela de login), usa-se uma **service account** — uma identidade de máquina com a sua própria chave privada.

O processo:
1. Criar service account no Google Cloud Console
2. Descarregar o ficheiro `credentials.json` com a chave privada
3. Partilhar o Google Sheet com o email da service account
4. O código usa a chave para obter tokens OAuth automaticamente

No projecto, o ficheiro `credentials.json` é convertido para string JSON e guardado na variável de ambiente `GOOGLE_CREDENTIALS_JSON` — assim não tens ficheiros sensíveis na imagem Docker.

### gspread — Cliente Python para Sheets

O `gspread` abstrai a API REST do Google Sheets:

```python
creds = Credentials.from_service_account_info(info, scopes=SCOPES)
client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_ID)
worksheet = sheet.worksheet("Expenses")

# Ler todos os valores
rows = worksheet.get_all_values()  # → lista de listas

# Escrever em batch (uma só chamada HTTP)
worksheet.batch_update([
    {"range": "C156", "values": [["30/04/2025"]]},
    {"range": "E156", "values": [["Sushi"]]},
])
```

### Porquê batch_update?

Cada chamada à API do Google tem latência de rede. Fazer 5 chamadas separadas (uma por coluna) seria 5x mais lento. O `batch_update` envia todas as escritas numa só chamada HTTP — reduz latência e o risco de atingir rate limits da API.

### Google Sheets como DB — Limitações

Sheets é conveniente (visualização humana, fórmulas, gráficos), mas tem limitações como base de dados:
- Sem transacções (risco de corrupção se dois writes simultâneos)
- Sem índices (ler 4000 linhas para filtrar é ineficiente)
- Rate limits da API (60 requests/minuto por utilizador)
- Sem tipos de dados reais (tudo é texto)

Para uso pessoal é perfeitamente adequado. Para múltiplos utilizadores ou alto volume, uma base de dados real (PostgreSQL, SQLite) seria melhor.

---

## 10. Pydantic — Validação de Dados entre IA e Código

### O problema que o Pydantic resolve

O modelo de IA devolve JSON com os campos da despesa. Mas o que garante que:
- `amount` é um número e não a string `"quarenta"`?
- `category` é um dos 18 valores válidos e não `"comida japonesa"`?
- A data está no formato correcto?

**Pydantic** é uma biblioteca de validação de dados que usa type hints do Python para garantir que os dados são do tipo certo, e lança erros claros quando não são.

### O modelo `Expense`

```python
class Category(str, Enum):
    EATING_OUT = "Eating out"
    GROCERIES  = "Groceries"
    FUEL       = "Fuel"
    # ...18 categorias

class Expense(BaseModel):
    date:         Optional[datetime] = None
    description:  str
    category:     Category           # tem de ser uma das 18 categorias
    amount:       float
    subscription: bool = False
    notes:        str = ""

    @field_validator("amount")
    def amount_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("amount deve ser positivo")
        return round(v, 2)   # garante 2 casas decimais

    @model_validator(mode="after")
    def set_date_if_none(self):
        if self.date is None:
            self.date = datetime.now()
        return self
```

Se o modelo de IA devolver `category: "Comida japonesa"`, o Pydantic lança `ValidationError` antes que esse valor chegue à base de dados. O `main.py` apanha esse erro e pede ao utilizador para reformular.

---

## 11. MCP — Model Context Protocol

### O que é o MCP

O **Model Context Protocol** é um protocolo aberto criado pela Anthropic (2024) para standardizar como os modelos de IA se ligam a ferramentas e fontes de dados externas.

Antes do MCP, cada integração era custom: código diferente para ligar o modelo ao Slack, ao GitHub, ao Notion. Com MCP, defines um **servidor MCP** que expõe ferramentas e recursos, e qualquer cliente compatível (Claude Desktop, Claude Code, IDEs) pode usá-lo automaticamente.

### Arquitectura MCP

```
┌─────────────────┐     MCP Protocol      ┌──────────────────┐
│  Host/Cliente   │ ◄───────────────────► │   Servidor MCP   │
│  (Claude, IDE)  │   (JSON-RPC via stdio  │  (o teu código)  │
└─────────────────┘    ou HTTP/SSE)        └──────────────────┘
                                                    │
                                           ┌────────┴────────┐
                                           │  Recursos       │
                                           │  (DB, APIs,     │
                                           │   ficheiros)    │
                                           └─────────────────┘
```

### Os três primitivos do MCP

**1. Tools (Ferramentas)** — O modelo pode chamar funções:
```json
{
  "name": "add_expense",
  "description": "Adiciona uma despesa ao Google Sheets",
  "inputSchema": { ... }
}
```
Equivalente ao tool use que já usas, mas standardizado e reutilizável.

**2. Resources (Recursos)** — O modelo pode ler dados:
```json
{
  "uri": "sheets://expenses/2025-04",
  "name": "Despesas de Abril 2025",
  "mimeType": "application/json"
}
```
Permite ao modelo aceder a contexto (ficheiros, dados de DB) sem precisar de ferramentas.

**3. Prompts (Templates)** — Prompts parametrizados reutilizáveis:
```json
{
  "name": "monthly_summary",
  "arguments": [{"name": "month"}, {"name": "year"}]
}
```

### Como o MCP se aplicaria aqui

Actualmente, as "ferramentas" do agente estão hardcoded no `agent.py`. Com MCP, poderias criar um servidor:

```python
# expense_mcp_server.py
from mcp.server import Server
from mcp.server.stdio import stdio_server

server = Server("expense-bot")

@server.list_tools()
async def list_tools():
    return [
        Tool(name="add_expense",   description="..."),
        Tool(name="get_expenses",  description="..."),
        Tool(name="get_summary",   description="..."),
    ]

@server.call_tool()
async def call_tool(name, arguments):
    if name == "add_expense":
        return await write_expense(Expense(**arguments))
    if name == "get_expenses":
        return read_expenses(**arguments)

async def main():
    async with stdio_server() as streams:
        await server.run(*streams)
```

**Vantagens do MCP neste contexto:**
- Poderias usar o mesmo servidor no Claude Desktop (chat directo) e no bot de Telegram
- Adicionar novas ferramentas sem tocar no `agent.py`
- Ferramentas descobertas dinamicamente (o modelo pergunta ao servidor o que está disponível)

### MCP vs Tool Use directo

| | Tool Use directo | MCP |
|--|--|--|
| Complexidade | Baixa | Média |
| Reutilização | Específico da app | Reutilizável |
| Descoberta dinâmica | Não | Sim |
| Melhor para | Apps únicas | Ecossistema de ferramentas |

Para este projecto, tool use directo é a escolha certa. MCP faz sentido quando tens múltiplos clientes a usar as mesmas ferramentas.

---

## 12. Servidores de IA e Providers

### O que é um "AI Server"

Um servidor de IA é um serviço que expõe modelos de linguagem via API HTTP. Recebes texto (prompt), devolve texto (resposta). Há vários providers:

| Provider | Modelos | Notas |
|----------|---------|-------|
| **Anthropic** | Claude Haiku/Sonnet/Opus | Usado neste projecto |
| **OpenAI** | GPT-4o, GPT-4.1 | API mais conhecida |
| **Google** | Gemini Flash/Pro | Contexto enorme (1M tokens) |
| **Mistral** | Mistral Large/Small | Europeu, bom para GDPR |
| **Meta** | Llama 3.x | Open-source, auto-hospedável |

### APIs compatíveis com OpenAI

Muitos providers implementam a mesma API que a OpenAI, para ser fácil migrar:

```python
# Anthropic SDK (nativo)
from anthropic import Anthropic
client = Anthropic()
response = client.messages.create(model="claude-haiku-4-5-20251001", ...)

# OpenAI SDK apontado para outro provider
from openai import OpenAI
client = OpenAI(base_url="https://api.outro-provider.com/v1", api_key="...")
response = client.chat.completions.create(model="gpt-4o", ...)
```

Poderias mesmo correr modelos localmente com **Ollama** (corre Llama, Mistral, etc. no teu Mac) e apontar o cliente OpenAI para `http://localhost:11434`.

### Auto-hospedagem vs API

| | API (Anthropic, OpenAI) | Auto-hospedagem (Ollama, vLLM) |
|--|--|--|
| Custo | Por token | Hardware próprio |
| Qualidade | Estado da arte | Depende do modelo |
| Privacidade | Dados vão para provider | Ficam locais |
| Manutenção | Zero | Alta |
| Latência | Rede | Local (pode ser mais rápido) |

Para dados financeiros pessoais, auto-hospedagem tem a vantagem da privacidade.

---

## 13. Melhorias Possíveis e Conceitos Avançados

### 13.1 Histórico de Conversa (Multi-turn)

**Problema actual:** Cada mensagem ao bot é tratada de forma isolada. Não há memória de conversa.

**O que melhoraria:** Perguntas de seguimento:
```
User: quanto gastei em abril?
Bot:  [resposta]
User: e em março?  ← actualmente não percebe o contexto
```

**Como implementar:**

```python
# Guardar histórico por utilizador
conversation_history: dict[int, list] = {}

async def handle_message(update, context):
    user_id = update.message.from_user.id
    history = conversation_history.get(user_id, [])

    history.append({"role": "user", "content": user_message})
    result = await run_agent(history)
    history.append({"role": "assistant", "content": result["text"]})

    conversation_history[user_id] = history[-20:]  # guardar últimas 20 msgs
```

**Atenção:** O histórico cresce indefinidamente. Estratégias para gerir:
- Janela deslizante (manter últimas N mensagens)
- Sumário automático (pedir ao modelo para resumir mensagens antigas)
- Guardar em Redis com TTL

### 13.2 Prompt Caching

**O que é:** A Anthropic permite marcar partes do prompt como "cacheáveis". Se o mesmo bloco de texto aparecer em chamadas consecutivas, o servidor usa a versão em cache — mais rápido e mais barato (5x mais barato em tokens de input cacheados).

**Ideal para este projecto:** O system prompt é sempre o mesmo. Cacheá-lo reduziria latência e custo em todas as chamadas.

```python
response = client.messages.create(
    model=MODEL,
    system=[
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"}  # cachear este bloco
        }
    ],
    messages=messages,
)
```

### 13.3 Streaming

**Problema actual:** O bot fica em silêncio até o modelo terminar toda a resposta. Para perguntas sobre despesas, isso pode ser 2-5 segundos.

**Com streaming:** O texto aparece token a token, como no Claude.ai.

```python
with client.messages.stream(
    model=MODEL,
    messages=messages,
) as stream:
    for text in stream.text_stream:
        # Enviar cada chunk ao Telegram
        await update.message.reply_text(text)  # simplificado
```

**Desafio:** O Telegram tem rate limits na edição de mensagens. A prática comum é acumular chunks e actualizar a mensagem a cada 500ms.

### 13.4 Base de Dados Real

**Problema actual:** Google Sheets como DB tem limitações de performance, concorrência e tipo de dados.

**Alternativas:**

**SQLite** (ficheiro local, zero infra):
```python
import sqlite3
# Perfeito para uso pessoal. Simples, rápido, sem servidor.
```

**PostgreSQL** (robusto, self-hosted):
```python
import asyncpg
# Transacções, índices, tipos de dados reais.
# Podias usar Supabase (PostgreSQL gerido, plano grátis).
```

**Manter o Sheets como "view":** Usar Sheets apenas para visualização, escrever na DB, sincronizar periodicamente com um webhook.

### 13.5 Análise Financeira com RAG

**RAG = Retrieval-Augmented Generation.** Em vez de enviar TODAS as despesas ao modelo (caro e lento), indexas as despesas numa base de dados vectorial e buscas apenas as mais relevantes.

```
User: "gastei mais em restaurantes este mês do que em março?"
       ↓
  Embedding da pergunta
       ↓
  Busca vectorial: despesas similares
       ↓
  Passa apenas as relevantes ao modelo
```

Ferramentas: **Chroma** (local), **Pinecone** (cloud), **pgvector** (PostgreSQL extension).

Para este projecto com ~200 despesas/mês, não é necessário. Mas com anos de dados começa a fazer sentido.

### 13.6 Structured Outputs

**Problema actual:** O modelo pode, teoricamente, devolver JSON malformado ou com campos inesperados.

A Anthropic tem suporte crescente para **structured outputs** — garantir que a resposta segue exactamente um schema. Alternativa: usar a biblioteca `instructor` que wrap a API Anthropic e força outputs Pydantic:

```python
import instructor
from anthropic import Anthropic

client = instructor.from_anthropic(Anthropic())

expense = client.messages.create(
    model=MODEL,
    response_model=Expense,  # Pydantic model directamente
    messages=[{"role": "user", "content": "sushi 40€ ontem"}],
)
# expense é um objecto Expense validado, garantido
```

Isto elimina a necessidade de tool use manual para extracção de dados estruturados.

### 13.7 Webhooks em vez de Polling

Para produção com múltiplos utilizadores, webhooks são mais eficientes:

```python
# Em vez de run_polling():
app.run_webhook(
    listen="0.0.0.0",
    port=8080,
    url_path="/webhook",
    webhook_url="https://o-teu-dominio.com/webhook",
)
```

Requer:
- Domínio com HTTPS (Let's Encrypt é gratuito)
- Ou um proxy reverso (nginx, Caddy)
- Ou um serviço como Railway, Fly.io, Render

### 13.8 Notificações Proactivas

O bot actual só responde. Podias adicionar alertas automáticos:

```python
# Cron job diário: verificar se ultrapassaste orçamento
async def daily_check():
    expenses = read_expenses(month=current_month)
    if expenses["total"] > MONTHLY_BUDGET:
        await bot.send_message(
            chat_id=USER_ID,
            text=f"⚠️ Já gastaste {expenses['total']}€ este mês!"
        )
```

### 13.9 Multi-Agente

Para tarefas complexas (ex: análise financeira detalhada com recomendações), podes ter múltiplos agentes especializados:

```
Orquestrador
├── Agente de Extracção     → parse linguagem natural
├── Agente de Análise       → tendências e padrões
└── Agente de Recomendação  → sugestões de poupança
```

Com a API Anthropic, isso é literalmente chamadas aninhadas — um agente chama ferramentas que por sua vez chamam outros agentes.

### 13.10 Modelo de Custos

Para referência, o custo de usar o Claude Haiku neste projecto:

| Operação | Tokens Input | Tokens Output | Custo aprox |
|----------|-------------|---------------|------------|
| Registar despesa | ~500 | ~100 | ~$0.0001 |
| Consultar despesas | ~2000 | ~300 | ~$0.0003 |

Para uso pessoal (50-100 interacções/mês), estamos a falar de centavos por mês. Haiku é deliberadamente barato para exactamente estes casos de uso.

---

## Resumo — O que este projecto usa vs o que poderia usar

| Conceito | Usado? | Onde |
|----------|--------|------|
| LLM (Claude Haiku) | ✅ | `agent.py` |
| Tool Use | ✅ | `agent.py` — 2 ferramentas |
| Agentic Loop | ✅ | `agent.py` — while loop |
| System Prompt | ✅ | `agent.py` — `_build_system_prompt()` |
| Pydantic Validation | ✅ | `models.py` |
| Telegram Polling | ✅ | `main.py` |
| Google Sheets DB | ✅ | `sheets_handler.py` |
| Prompt Caching | ❌ | Fácil de adicionar |
| Streaming | ❌ | Melhora UX |
| Histórico Multi-turn | ❌ | Contexto de conversa |
| MCP Server | ❌ | Reutilização de ferramentas |
| Webhooks | ❌ | Mais eficiente em produção |
| Base de Dados Real | ❌ | SQLite seria trivial |
| Structured Outputs | ❌ | `instructor` library |
| RAG | ❌ | Para grande volume de dados |

---

*Documento gerado para o projecto expense-bot — Maio 2026*
