"""Consulta de dados oficiais de futebol (football-data.org)."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from .config import settings

BASE = "https://api.football-data.org/v4"
CACHE_SEGUNDOS = 120

# Ordem importa: a primeira competição cujo apelido aparecer na pergunta vence.
COMPETICOES: list[dict[str, Any]] = [
    {"code": "SA", "nome": "Serie A (Itália)", "k": ["serie a italiana", "campeonato italiano", "calcio"]},
    {"code": "PL", "nome": "Premier League", "k": ["premier league", "campeonato ingles"]},
    {"code": "PD", "nome": "La Liga", "k": ["la liga", "laliga", "campeonato espanhol"]},
    {"code": "BL1", "nome": "Bundesliga", "k": ["bundesliga", "campeonato alemao"]},
    {"code": "FL1", "nome": "Ligue 1", "k": ["ligue 1", "campeonato frances"]},
    # ELC antes de CL: "championship" também contém a palavra "champions".
    {"code": "ELC", "nome": "Championship", "k": ["championship"]},
    {"code": "CL", "nome": "Champions League", "k": ["champions"]},
    {"code": "WC", "nome": "Copa do Mundo", "k": ["copa do mundo"]},
    {"code": "PPL", "nome": "Primeira Liga", "k": ["primeira liga", "campeonato portugues"]},
    {"code": "DED", "nome": "Eredivisie", "k": ["eredivisie"]},
    {"code": "EC", "nome": "Eurocopa", "k": ["eurocopa"]},
    {"code": "BSA", "nome": "Brasileirão Série A", "k": ["brasileir", "serie a"]},
]

BRASILEIRAO = next(c for c in COMPETICOES if c["code"] == "BSA")

STATUS = {
    "FINISHED": "encerrado",
    "IN_PLAY": "em andamento",
    "PAUSED": "intervalo",
    "SCHEDULED": "agendado",
    "TIMED": "agendado",
    "POSTPONED": "adiado",
    "SUSPENDED": "suspenso",
    "CANCELED": "cancelado",
    "AWARDED": "atribuído",
}

_cache: dict[str, tuple[float, dict[str, Any]]] = {}


class FootballIndisponivel(RuntimeError):
    """Levantado quando os dados oficiais não podem ser consultados."""


@dataclass
class Dados:
    contexto: str
    rotulo: str
    nome: str
    falhas: list[str]


def normalizar(texto: str) -> str:
    import unicodedata

    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return sem_acento.lower()


def _competicao(pergunta: str) -> dict[str, Any] | None:
    q = normalizar(pergunta)
    for competicao in COMPETICOES:
        if any(apelido in q for apelido in competicao["k"]):
            return competicao
    return None


def _consultas(pergunta: str) -> dict[str, bool]:
    q = normalizar(pergunta)
    return {
        "tabela": bool(re.search(r"tabela|classificacao|posicao|lider|rebaix|\bg4\b|\bg6\b|pontos", q)),
        "artilheiros": bool(re.search(r"artilh|goleador", q)),
        "jogos": bool(
            re.search(
                r"resultado|placar|rodada|proxim[oa]s? jogo|jogos? (de|da|do|hoje|amanha|ontem)"
                r"|quando joga|joga hoje|ultimo jogo|jogou",
                q,
            )
        ),
    }


# Temas que a football-data.org NÃO cobre: se aparecerem, vale pesquisar na web.
TEMAS_EXTRAS = re.compile(
    r"tecnico|treinador|contrat|transfer|reforc|lesion|desfalque|escalac|elenco|jogador"
    r"|historia|curiosidade|arbitr|regra|tatica|formacao|estadio|torcida|eleicao"
    r"|presidente|salario|multa|renovacao|aposent|camisa|ingresso|transmissao|assistir"
    r"|por que|porque|como funciona|vale a pena|melhor"
)


def so_dados_oficiais(pergunta: str) -> bool:
    """True quando a pergunta é só tabela/jogos/artilharia, sem outros assuntos.

    Nesses casos o bloco oficial já responde tudo e não é preciso buscar na web.
    """
    if not any(_consultas(pergunta).values()):
        return False
    return not TEMAS_EXTRAS.search(normalizar(pergunta))


def _nome_time(time: dict[str, Any]) -> str:
    return time.get("shortName") or time.get("name") or "?"


def _quando(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%d/%m %H:%M")
    except (ValueError, TypeError):
        return iso


async def _get(cliente: httpx.AsyncClient, caminho: str) -> dict[str, Any]:
    agora = time.monotonic()
    em_cache = _cache.get(caminho)
    if em_cache and agora - em_cache[0] < CACHE_SEGUNDOS:
        return em_cache[1]

    resposta = await cliente.get(caminho)
    payload: dict[str, Any] = {}
    try:
        payload = resposta.json()
    except ValueError:
        pass

    if resposta.status_code == 429:
        raise FootballIndisponivel("limite de consultas por minuto da football-data.org atingido")
    if resposta.status_code >= 400:
        mensagem = payload.get("message") or payload.get("error") or f"HTTP {resposta.status_code}"
        raise FootballIndisponivel(str(mensagem))

    _cache[caminho] = (agora, payload)
    return payload


async def _secao_tabela(cliente: httpx.AsyncClient, code: str) -> str:
    dados = await _get(cliente, f"/competitions/{code}/standings")
    linhas: list[str] = []
    for tabela in dados.get("standings", []):
        if tabela.get("type") != "TOTAL":
            continue
        if tabela.get("group"):
            linhas.append(str(tabela["group"]).replace("_", " ") + ":")
        for time in tabela.get("table", []):
            linhas.append(
                f"{time.get('position')}. {_nome_time(time.get('team', {}))} - "
                f"{time.get('points')} pts em {time.get('playedGames')} jogos, "
                f"{time.get('won')}V {time.get('draw')}E {time.get('lost')}D, "
                f"saldo {time.get('goalDifference')}"
            )
    if not linhas:
        return "TABELA: a competição não retornou classificação."
    return "TABELA:\n" + "\n".join(linhas[:40])


async def _secao_artilheiros(cliente: httpx.AsyncClient, code: str) -> str:
    dados = await _get(cliente, f"/competitions/{code}/scorers")
    linhas: list[str] = []
    for indice, artilheiro in enumerate(dados.get("scorers", [])[:10], 1):
        jogador = (artilheiro.get("player") or {}).get("name", "?")
        time = _nome_time(artilheiro.get("team") or {})
        gols = artilheiro.get("goals", 0)
        assistencias = artilheiro.get("assists")
        extra = f", {assistencias} assistências" if assistencias else ""
        linhas.append(f"{indice}. {jogador} ({time}) - {gols} gols{extra}")
    if not linhas:
        return "ARTILHEIROS: a competição não retornou artilharia."
    return "ARTILHEIROS:\n" + "\n".join(linhas)


async def _secao_jogos(cliente: httpx.AsyncClient, code: str, pergunta: str) -> str:
    hoje = datetime.now(timezone.utc)
    de = (hoje - timedelta(days=7)).date().isoformat()
    ate = (hoje + timedelta(days=7)).date().isoformat()
    dados = await _get(cliente, f"/competitions/{code}/matches?dateFrom={de}&dateTo={ate}")

    jogos = dados.get("matches", [])
    q = normalizar(pergunta)
    citados = [
        jogo
        for jogo in jogos
        if any(
            nome and len(nome) > 3 and normalizar(nome) in q
            for time in (jogo.get("homeTeam") or {}, jogo.get("awayTeam") or {})
            for nome in (time.get("name"), time.get("shortName"))
        )
    ]
    if citados:
        jogos = citados

    linhas: list[str] = []
    for jogo in jogos[:20]:
        placar = jogo.get("score", {}).get("fullTime") or {}
        if jogo.get("status") in ("SCHEDULED", "TIMED") or placar.get("home") is None:
            resultado = "x"
        else:
            resultado = f"{placar.get('home')} x {placar.get('away')}"
        linhas.append(
            f"{_quando(jogo.get('utcDate', ''))}: "
            f"{_nome_time(jogo.get('homeTeam') or {})} {resultado} "
            f"{_nome_time(jogo.get('awayTeam') or {})} "
            f"({STATUS.get(jogo.get('status', ''), jogo.get('status'))})"
        )

    cabecalho = "JOGOS (últimos 7 e próximos 7 dias):"
    return cabecalho + "\n" + ("\n".join(linhas) if linhas else "nenhum jogo encontrado no período")


async def coletar(pergunta: str) -> Dados | None:
    """Retorna os dados oficiais relevantes para a pergunta, ou None se não houver consulta aplicável."""
    competicao = _competicao(pergunta)
    quer = _consultas(pergunta)

    if not competicao and not any(quer.values()):
        return None

    # "Série A" sozinho costuma significar Italiano, mas "Brasileirão Série A" é Brasileirão.
    q = normalizar(pergunta)
    if "brasileir" in q:
        competicao = BRASILEIRAO

    alvo = competicao or BRASILEIRAO
    if not any(quer.values()):
        quer["tabela"] = True

    if not settings.football_token:
        raise FootballIndisponivel(
            "FOOTBALL_DATA_TOKEN não configurado no .env (cadastro gratuito em football-data.org)"
        )

    partes: list[str] = []
    rotulos: list[str] = []
    falhas: list[str] = []

    headers = {"X-Auth-Token": settings.football_token}
    async with httpx.AsyncClient(base_url=BASE, headers=headers, timeout=25) as cliente:
        tarefas: list[tuple[str, Any]] = []
        if quer["tabela"]:
            tarefas.append(("tabela", _secao_tabela(cliente, alvo["code"])))
        if quer["artilheiros"]:
            tarefas.append(("artilheiros", _secao_artilheiros(cliente, alvo["code"])))
        if quer["jogos"]:
            tarefas.append(("jogos", _secao_jogos(cliente, alvo["code"], pergunta)))

        resultados = await asyncio.gather(*(tarefa for _, tarefa in tarefas), return_exceptions=True)

    for (nome, _), resultado in zip(tarefas, resultados):
        if isinstance(resultado, BaseException):
            falhas.append(f"{nome}: {str(resultado)[:160]}")
        else:
            partes.append(str(resultado))
            rotulos.append(nome)

    if not partes:
        detalhe = "; ".join(falhas) or "resposta vazia"
        raise FootballIndisponivel(f"football-data.org não retornou dados ({detalhe})")

    agora = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M")
    contexto = (
        f"DADOS ATUAIS (football-data.org, consultados em {agora}) - {alvo['nome']}:\n"
        + "\n\n".join(partes)
    )
    if falhas:
        contexto += "\n\nOBSERVAÇÃO: falhou a consulta de " + "; ".join(falhas)

    rotulo = f"📊 Dados atualizados: {alvo['nome']} · {', '.join(rotulos)}"
    if falhas:
        rotulo += " · parcial"

    return Dados(contexto=contexto, rotulo=rotulo, nome=alvo["nome"], falhas=falhas)


# ---------------------------------------------------------------------------
#  Dados estruturados para a "Central de futebol" (JSON para a interface)
# ---------------------------------------------------------------------------

# Competições que aparecem na Central (as sazonais ficam de fora).
COMPETICOES_UI = ["BSA", "PL", "PD", "SA", "BL1", "FL1", "CL", "PPL", "DED"]

# Faixas destacadas na tabela (só onde é consenso, para não inventar zona).
ZONAS = {"BSA": {"superior": 4, "inferior": 4, "legenda_alta": "G4", "legenda_baixa": "Z4"}}


def lista_competicoes() -> list[dict[str, str]]:
    nomes = {c["code"]: c["nome"] for c in COMPETICOES}
    return [{"code": code, "nome": nomes[code]} for code in COMPETICOES_UI if code in nomes]


def _agora() -> str:
    return datetime.now().astimezone().strftime("%d/%m/%Y %H:%M")


def _equipe(time: dict[str, Any]) -> dict[str, Any]:
    return {
        "time": _nome_time(time),
        "nome": time.get("name"),
        "sigla": time.get("tla"),
        "escudo": time.get("crest"),
    }


async def _tabela_json(cliente: httpx.AsyncClient, code: str) -> dict[str, Any]:
    dados = await _get(cliente, f"/competitions/{code}/standings")
    grupos: list[dict[str, Any]] = []

    for tabela in dados.get("standings", []):
        if tabela.get("type") != "TOTAL":
            continue
        linhas = []
        for linha in tabela.get("table", []):
            equipe = _equipe(linha.get("team") or {})
            linhas.append(
                {
                    "posicao": linha.get("position"),
                    **equipe,
                    "pontos": linha.get("points"),
                    "jogos": linha.get("playedGames"),
                    "vitorias": linha.get("won"),
                    "empates": linha.get("draw"),
                    "derrotas": linha.get("lost"),
                    "saldo": linha.get("goalDifference"),
                }
            )
        grupo = str(tabela.get("group") or "").replace("_", " ").strip() or None
        if grupo and grupo.lower() in {"matchday", "regular season"}:
            grupo = None
        grupos.append({"grupo": grupo, "linhas": linhas})

    if not grupos:
        raise FootballIndisponivel("a competição não retornou classificação agora")

    return {"grupos": grupos, "zonas": ZONAS.get(code)}


def _jogo_json(jogo: dict[str, Any]) -> dict[str, Any]:
    placar = jogo.get("score") or {}
    fim = placar.get("fullTime") or {}
    return {
        "data": _quando(jogo.get("utcDate", "")),
        "iso": jogo.get("utcDate"),
        "status": STATUS.get(jogo.get("status"), jogo.get("status")),
        "rodada": jogo.get("matchday"),
        "casa": _nome_time(jogo.get("homeTeam") or {}),
        "casa_escudo": (jogo.get("homeTeam") or {}).get("crest"),
        "casa_sigla": (jogo.get("homeTeam") or {}).get("tla"),
        "fora": _nome_time(jogo.get("awayTeam") or {}),
        "fora_escudo": (jogo.get("awayTeam") or {}).get("crest"),
        "fora_sigla": (jogo.get("awayTeam") or {}).get("tla"),
        "gols_casa": fim.get("home"),
        "gols_fora": fim.get("away"),
    }


async def _jogos_json(cliente: httpx.AsyncClient, code: str) -> dict[str, Any]:
    dados = await _get(cliente, f"/competitions/{code}/matches")
    jogos = dados.get("matches", [])

    terminados = [j for j in jogos if j.get("status") == "FINISHED"]
    proximos = [j for j in jogos if j.get("status") in ("SCHEDULED", "TIMED")]

    if not terminados and not proximos:
        raise FootballIndisponivel("a competição não retornou jogos agora")

    return {
        "ultimos": [_jogo_json(j) for j in terminados[-8:]],
        "proximos": [_jogo_json(j) for j in proximos[:8]],
    }


async def _artilheiros_json(cliente: httpx.AsyncClient, code: str) -> dict[str, Any]:
    dados = await _get(cliente, f"/competitions/{code}/scorers?limit=15")
    lista = []
    for indice, item in enumerate(dados.get("scorers", [])[:15], 1):
        jogador = item.get("player") or {}
        equipe = _equipe(item.get("team") or {})
        lista.append(
            {
                "posicao": indice,
                "jogador": jogador.get("name"),
                "time": equipe["time"],
                "escudo": equipe["escudo"],
                "gols": item.get("goals"),
                "assistencias": item.get("assists"),
                "jogos": item.get("playedMatches"),
            }
        )

    if not lista:
        raise FootballIndisponivel("a competição não retornou artilheiros agora")

    return {"artilheiros": lista}


async def panorama(code: str, secao: str) -> dict[str, Any]:
    """Monta o JSON de uma seção da Central (tabela, jogos ou artilheiros)."""
    code = code.upper()
    competicao = next((c for c in COMPETICOES if c["code"] == code), None)
    if not competicao:
        raise ValueError(f"competição desconhecida: {code}")
    if secao not in ("tabela", "jogos", "artilheiros"):
        raise ValueError(f"seção desconhecida: {secao}")
    if not settings.football_token:
        raise FootballIndisponivel(
            "FOOTBALL_DATA_TOKEN não configurado no .env (cadastro gratuito em football-data.org)"
        )

    headers = {"X-Auth-Token": settings.football_token}
    async with httpx.AsyncClient(base_url=BASE, headers=headers, timeout=25) as cliente:
        if secao == "tabela":
            dados = await _tabela_json(cliente, code)
        elif secao == "jogos":
            dados = await _jogos_json(cliente, code)
        else:
            dados = await _artilheiros_json(cliente, code)

    return {
        "code": code,
        "nome": competicao["nome"],
        "secao": secao,
        "atualizado_em": _agora(),
        **dados,
    }
