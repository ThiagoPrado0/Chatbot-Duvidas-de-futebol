# ⚽ Papo de Bola — chatbot de futebol com CrewAI

Chat de futebol com interface pronta em `index.html`, backend em **FastAPI** e respostas geradas por uma **LLM chamada via API**. Dois agentes do **CrewAI** cuidam da pesquisa:

1. **Pesquisador de futebol** — busca na internet (`buscar_na_web`) e abre as páginas mais relevantes (`ler_pagina`).
2. **Redator do Papo de Bola** — transforma a apuração + os dados oficiais em uma resposta curta, em português do Brasil, sem inventar fatos.

Quando a pergunta envolve tabela, jogos ou artilharia, a API também consulta a **football-data.org** e entrega os números oficiais para os agentes.

> A chave da IA fica **somente no servidor** (`.env`). O navegador conversa com o FastAPI em `/api/chat`.

---

## 1. O que você precisa

- Python **3.10 a 3.13**
- Uma chave de API de LLM (OpenAI, Groq, OpenRouter, DeepSeek, etc.)
- Opcional: chave da [football-data.org](https://www.football-data.org/client/register) (grátis) para tabelas e jogos
- Opcional: chave do [Tavily](https://tavily.com) ou [Serper](https://serper.dev) para busca mais estável (sem chave, usa DuckDuckGo)

## 2. Início rápido (Windows)

1. Dê dois cliques em **`start.bat`**.
2. Na primeira execução ele cria o `.env` e o ambiente virtual, e para.
3. Abra o **`.env`** e preencha, no mínimo:

   ```env
   LLM_MODEL=groq/qwen/qwen3.8-27b
   LLM_API_KEY=gsk_...
   ```

   A chave da Groq é criada em <https://console.groq.com/keys>. O `.env` deste projeto já vem com o modelo escolhido; falta apenas colar a chave.

4. Rode **`start.bat`** de novo.
5. Acesse **http://localhost:8000**.

### Manualmente (qualquer sistema)

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env      # cp no Linux/macOS
# edite o .env
uvicorn server.main:app --host 127.0.0.1 --port 8000
```

> Não abra o `index.html` com dois cliques (`file://`). A página precisa do servidor para chamar a API.

## 3. Configurar o provedor de IA

O projeto usa o formato do **LiteLLM/CrewAI**. O padrão já configurado é:

**Groq — `qwen/qwen3.8-27b`**
```env
LLM_MODEL=groq/qwen/qwen3.8-27b
LLM_API_KEY=gsk_...
```
> Chave em <https://console.groq.com/keys>. O prefixo `groq/` é obrigatório para o LiteLLM rotear para a Groq; o restante (`qwen/qwen3.8-27b`) é o ID do modelo.

Outros provedores (opcional):

**OpenAI**
```env
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-...
```

**OpenRouter**
```env
LLM_MODEL=openrouter/google/gemini-2.5-flash
LLM_API_KEY=sk-or-...
```

**DeepSeek** (endpoint compatível com OpenAI)
```env
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-...
```

**Ollama local** (sem custo, sem chave)
```env
LLM_MODEL=ollama/llama3.1
LLM_BASE_URL=http://localhost:11434
```

> Modelos pequenos (7B) costumam falhar em usar ferramentas. Para o modo com agentes, prefira modelos com bom suporte a *tool calling*. O `qwen/qwen3.8-27b` da Groq é o modelo definido neste projeto.

### Busca na web

```env
# uma das duas (recomendado)
TAVILY_API_KEY=tvly-...
# SERPER_API_KEY=...
```

Sem chave, o backend usa **DuckDuckGo** — funciona, mas pode sofrer bloqueios ou limites.

### Dados oficiais

```env
FOOTBALL_DATA_TOKEN=sua-chave
```

O plano gratuito da football-data.org cobre as principais competições e tem limite de requisições por minuto. As respostas ficam em cache por 2 minutos.

## 4. Como funciona

```
Navegador (index.html + app.js)
        │  POST /api/chat  (SSE)
        ▼
FastAPI (server/main.py)
        │
        ├── football-data.org  →  tabela / jogos / artilheiros (quando aplicável)
        │
        ├── modo "crew"  →  CrewAI
        │      ├─ pergunta só de tabela/jogos/artilharia → redator direto (sem busca)
        │      ├─ dados oficiais + outro assunto        → pesquisador (1 busca) + redator
        │      └─ sem dados oficiais                    → pesquisador (até MAX_BUSCAS) + redator
        │
        └── modo "rapido" →  uma chamada de LLM, com streaming token a token
        ▼
Eventos SSE: status → (fonte) → final | erro
```

- **Pesquisa com agentes**: mais lento (várias chamadas), com fontes e informação atualizada.
- **Resposta rápida**: uma única chamada, com streaming; usa apenas o conhecimento do modelo + dados oficiais da pergunta.

### Central de futebol

O item **Central de futebol** no menu abre uma área de dados oficiais que **não gasta tokens de LLM**:

- Competições: Brasileirão, Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions League, Primeira Liga e Eredivisie.
- **Classificação** (com G4/Z4 destacados onde há consenso), **jogos** (próximos e últimos resultados) e **artilheiros**.
- Os dados vêm da football-data.org e ficam em cache na página; **↻ Atualizar** força uma nova consulta.
- **✦ Perguntar à IA** leva a competição e a seção para o chat com a pergunta já escrita — você decide quando enviar.
- As abas e as competições funcionam pelo teclado (setas, Home e End). O escudo que não carrega vira a sigla do time.

A Central só aparece com dados se `FOOTBALL_DATA_TOKEN` estiver preenchido; sem token, ela explica como criar a conta gratuita.

### Economia automática de buscas

O bot decide sozinho quanto pesquisar, e a cota é imposta na ferramenta (não só pedida no prompt):

| Pergunta | Chamadas de LLM | Buscas na web |
|---|---|---|
| “Qual a situação da tabela do Brasileirão?” | 1 | **0** — responde com a API oficial |
| “Tabela do Brasileirão e o técnico do líder?” | 2 a 3 | **1** |
| “Quem é o técnico do Fluminense hoje?” | 2 a 4 | até `MAX_BUSCAS` (2) |

Quando a cota estoura, a ferramenta devolve “cota esgotada” e o agente é obrigado a responder com o que já tem, em vez de continuar buscando. Isso mantém as respostas dentro do limite de tokens do plano gratuito da Groq.

A interface mostra o andamento (ex.: “Pesquisando na internet…”, “Lendo uma fonte encontrada…”), os dados oficiais usados e os links das fontes. Tabelas em Markdown na resposta viram tabelas de verdade, com rolagem horizontal no celular; cada resposta tem um botão **Copiar**.

## 5. Endpoints

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/` | Interface do chat |
| `GET` | `/api/config` | Modelo, provedor, busca e status da configuração |
| `POST` | `/api/chat` | Chat com streaming SSE (`mensagem`, `historico`, `modo`) |
| `GET` | `/api/competicoes` | Lista as competições disponíveis na Central |
| `GET` | `/api/competicao/{code}` | Classificação, jogos ou artilheiros (`?secao=tabela\|jogos\|artilheiros`) |
| `GET` | `/api/health` | Verificação simples do servidor |

Exemplo de corpo do `/api/chat`:

```json
{
  "mensagem": "Como está a tabela do Brasileirão?",
  "historico": [{ "role": "user", "content": "oi" }],
  "modo": "crew"
}
```

## 6. Estrutura do projeto

```
chatbot 2/
├── index.html          # interface (visual original preservado)
├── app.js              # conversa com a API, SSE, fontes e memória local
├── server/
│   ├── main.py         # FastAPI + streaming SSE
│   ├── crew.py         # agentes e tarefas do CrewAI
│   ├── search.py       # ferramentas de busca e leitura de páginas
│   ├── football.py     # football-data.org (tabela, jogos, artilheiros)
│   ├── chat.py         # modo rápido (uma chamada de LLM)
│   ├── prompts.py      # regras de escopo e prompts dos agentes
│   └── config.py       # leitura do .env
├── requirements.txt
├── .env.example
└── start.bat
```

## 7. Problemas comuns

**“A IA ainda não está configurada”**
O `.env` não existe ou está sem `LLM_API_KEY`/`LLM_MODEL`. Depois de editar, reinicie o servidor.

**`401` / `invalid api key`**
Chave errada, sem créditos ou modelo de outro provedor. Confira `LLM_MODEL` e `LLM_API_KEY`.

**“Sem dados oficiais: FOOTBALL_DATA_TOKEN não configurado”**
É só um aviso: a resposta continua, mas sem tabela/jogos oficiais. Configure o token para habilitar.

**A busca falha sempre**
DuckDuckGo pode bloquear requisições do servidor. Configure `TAVILY_API_KEY` ou `SERPER_API_KEY`.

**O agente entra em loop**
Reduza `MAX_ITERACOES` no `.env` ou use um modelo melhor em *tool calling*.

**`rate_limit_exceeded` / `Request too large ... ITPM`**
O plano gratuito da Groq limita tokens de entrada por minuto (7.000 no Qwen 3.8 27B). O modo com agentes usa 2 a 4 chamadas por pergunta, então espere alguns segundos entre perguntas ou reduza `MAX_ITERACOES`, `MAX_FONTES` e o tamanho dos trechos. Em uso contínuo, considere o plano pago.

**Porta 8000 ocupada**
Rode em outra porta: `uvicorn server.main:app --port 8001` e acesse `http://localhost:8001`.

**Primeira resposta demora**
No modo com agentes são feitas várias chamadas de LLM. O servidor envia *heartbeats* para manter a conexão viva enquanto isso.

## 8. Segurança e custos

- A chave da API nunca é enviada ao navegador.
- O histórico fica no `localStorage` do usuário e é enviado ao servidor somente para dar contexto.
- Cada pergunta no modo “Pesquisa com agentes” faz mais de uma chamada de LLM (pesquisa + redação); acompanhe o consumo no painel do provedor.
- Para publicar na internet, coloque autenticação/rate limit na frente da API e restrinja o CORS ao seu domínio.
