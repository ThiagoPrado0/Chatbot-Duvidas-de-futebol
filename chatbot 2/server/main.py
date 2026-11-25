"""API FastAPI do Papo de Bola (CrewAI + pesquisa na web)."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from . import chat as modo_rapido
from . import crew as modo_agentes
from .config import RAIZ, settings
from .football import FootballIndisponivel, coletar, lista_competicoes, panorama

app = FastAPI(title="Papo de Bola API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class Mensagem(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(default="", max_length=8000)


class PedidoChat(BaseModel):
    mensagem: str = Field(..., min_length=1, max_length=4000)
    historico: list[Mensagem] = Field(default_factory=list, max_length=20)
    modo: Literal["crew", "rapido"] = "crew"


def _sse(evento: str, dados: dict[str, Any]) -> str:
    return f"event: {evento}\ndata: {json.dumps(dados, ensure_ascii=False)}\n\n"


def _mensagem_erro(erro: Exception) -> str:
    if not settings.configurado:
        return (
            "A IA ainda não está configurada. Copie o arquivo .env.example para .env, "
            "preencha LLM_MODEL e LLM_API_KEY e reinicie o servidor."
        )
    texto = str(erro).strip() or type(erro).__name__
    baixo = texto.lower()
    dica = ""
    if any(pista in baixo for pista in ("api key", "authentication", "unauthorized", "401", "invalid key")):
        dica = " Confira a chave em LLM_API_KEY no arquivo .env."
    elif any(pista in baixo for pista in ("rate limit", "429", "quota")):
        dica = " O provedor limitou as chamadas; aguarde alguns segundos e tente de novo."
    elif any(pista in baixo for pista in ("not found", "404", "model")):
        dica = " Confira se LLM_MODEL existe no provedor configurado."
    return f"{texto[:500]}{dica}"


async def _fluxo(pedido: PedidoChat, request: Request) -> AsyncIterator[str]:
    pergunta = pedido.mensagem.strip()
    if not pergunta:
        yield _sse("erro", {"texto": "Envie uma pergunta sobre futebol."})
        return

    historico = [m.model_dump() for m in pedido.historico]

    # 1) Dados oficiais (quando a pergunta pede tabela/jogos/artilharia).
    yield _sse("status", {"texto": "Consultando dados oficiais…", "tipo": "info"})
    dados = None
    try:
        dados = await coletar(pergunta)
        if dados:
            yield _sse("status", {"texto": dados.rotulo, "tipo": "info"})
    except FootballIndisponivel as erro:
        yield _sse("status", {"texto": f"Sem dados oficiais: {erro}", "tipo": "aviso"})
    except Exception as erro:  # rede, timeout, resposta inesperada...
        yield _sse("status", {"texto": f"Sem dados oficiais: {_mensagem_erro(erro)}", "tipo": "aviso"})

    contexto = dados.contexto if dados else None

    if await request.is_disconnected():
        return

    # 2a) Modo rápido: um único LLM, com streaming de tokens.
    if pedido.modo == "rapido":
        yield _sse("status", {"texto": "Gerando resposta…", "tipo": "info"})
        resposta = ""
        try:
            async for pedaco in modo_rapido.responder_stream(pergunta, historico, contexto):
                resposta += pedaco
                yield _sse("token", {"texto": pedaco})
        except Exception as erro:
            yield _sse("erro", {"texto": _mensagem_erro(erro)})
            return

        if not resposta.strip():
            yield _sse("erro", {"texto": "O modelo não retornou texto. Tente novamente."})
            return

        # Se a resposta usou dados oficiais, mostra de onde eles vieram.
        fontes_rapido: list[dict[str, str]] = []
        if dados:
            fontes_rapido = [
                {
                    "titulo": f"football-data.org · {dados.nome}",
                    "url": "https://www.football-data.org/",
                    "trecho": (
                        "Classificação, jogos e artilharia consultados direto na API "
                        "oficial no momento da pergunta."
                    ),
                }
            ]
            for fonte in fontes_rapido:
                yield _sse("fonte", fonte)

        yield _sse("final", {"resposta": resposta.strip(), "fontes": fontes_rapido})
        return

    # 2b) Modo CrewAI: pesquisa com agentes em uma thread separada,
    #     enviando o progresso por uma fila assíncrona.
    fila: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
    loop = asyncio.get_running_loop()
    ultimo_status = {"texto": ""}

    def enviar_status(texto: str) -> None:
        if not texto or texto == ultimo_status["texto"]:
            return
        ultimo_status["texto"] = texto
        loop.call_soon_threadsafe(fila.put_nowait, ("status", texto))

    def trabalhar() -> None:
        try:
            resultado = modo_agentes.executar(pergunta, historico, contexto, enviar_status)
            loop.call_soon_threadsafe(
                fila.put_nowait,
                ("final", {"resposta": resultado.resposta, "fontes": resultado.fontes}),
            )
        except Exception as erro:
            loop.call_soon_threadsafe(fila.put_nowait, ("erro", _mensagem_erro(erro)))
        finally:
            loop.call_soon_threadsafe(fila.put_nowait, ("fim", None))

    threading.Thread(target=trabalhar, name="crew-papo-de-bola", daemon=True).start()

    yield _sse("status", {"texto": "Agentes iniciando…", "tipo": "info"})

    while True:
        try:
            tipo, dados_evento = await asyncio.wait_for(fila.get(), timeout=15)
        except asyncio.TimeoutError:
            # Mantém a conexão viva enquanto os agentes trabalham.
            yield ": ping\n\n"
            continue

        if tipo == "fim":
            break
        if tipo == "status":
            yield _sse("status", {"texto": dados_evento, "tipo": "info"})
        elif tipo == "final":
            for fonte in dados_evento.get("fontes", []):
                yield _sse("fonte", fonte)
            yield _sse("final", dados_evento)
        elif tipo == "erro":
            yield _sse("erro", {"texto": str(dados_evento)})


@app.get("/", include_in_schema=False)
async def pagina() -> FileResponse:
    return FileResponse(RAIZ / "index.html", media_type="text/html", headers={"Cache-Control": "no-cache"})


@app.get("/app.js", include_in_schema=False)
async def script() -> FileResponse:
    return FileResponse(RAIZ / "app.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


@app.get("/api/health")
@app.get("/health", include_in_schema=False)
async def health() -> dict[str, Any]:
    return {"ok": True, "modelo": settings.modelo, "configurado": settings.configurado}


@app.get("/api/config")
async def config() -> dict[str, Any]:
    return {
        "modelo": settings.modelo,
        "provedor": settings.provedor,
        "configurado": settings.configurado,
        "pesquisa_web": settings.motor_busca,
        "dados_oficiais": bool(settings.football_token),
        "modos": [
            {"valor": "crew", "rotulo": "Pesquisa com agentes"},
            {"valor": "rapido", "rotulo": "Resposta rápida"},
        ],
    }


@app.get("/api/competicoes")
async def competicoes() -> dict[str, Any]:
    return {
        "competicoes": lista_competicoes(),
        "dados_oficiais": bool(settings.football_token),
    }


@app.get("/api/competicao/{code}")
async def competicao(
    code: str,
    secao: Literal["tabela", "jogos", "artilheiros"] = "tabela",
) -> dict[str, Any]:
    """Classificação, jogos ou artilheiros de uma competição (football-data.org)."""
    try:
        return await panorama(code, secao)
    except ValueError as erro:
        raise HTTPException(status_code=404, detail=str(erro)) from erro
    except FootballIndisponivel as erro:
        raise HTTPException(status_code=503, detail=str(erro)) from erro
    except Exception as erro:  # rede, timeout, resposta inesperada...
        raise HTTPException(
            status_code=502, detail="não foi possível consultar a football-data.org agora"
        ) from erro


@app.post("/api/chat")
async def chat(pedido: PedidoChat, request: Request) -> StreamingResponse:
    return StreamingResponse(
        _fluxo(pedido, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
