"""Modo rápido: uma única chamada de LLM, sem agentes de pesquisa."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import litellm

from .config import settings
from .prompts import system_prompt

litellm.suppress_debug_info = True
litellm.drop_params = True

AVISO_MODO_RAPIDO = (
    "\n\n(AVISO DO SISTEMA: este modo não pesquisa na internet. Se a resposta exigir notícias "
    "ou dados recentes que não estejam em DADOS ATUAIS, diga que não tem o dado verificado e "
    "sugira ao usuário usar o modo 'Pesquisa com agentes'.)"
)


def _mensagens(pergunta: str, historico: list[dict[str, str]], dados: str | None) -> list[dict[str, str]]:
    conteudo = pergunta
    if dados:
        conteudo += "\n\n" + dados
    conteudo += AVISO_MODO_RAPIDO

    mensagens: list[dict[str, str]] = [{"role": "system", "content": system_prompt()}]
    for mensagem in historico[-6:]:
        papel = mensagem.get("role")
        texto = (mensagem.get("content") or "").strip()
        if papel in ("user", "assistant") and texto:
            mensagens.append({"role": papel, "content": texto[:1500]})
    mensagens.append({"role": "user", "content": conteudo})
    return mensagens


def _opcoes() -> dict[str, Any]:
    opcoes: dict[str, Any] = {
        "model": settings.modelo_litellm,
        "temperature": settings.temperatura,
        "stream": True,
    }
    if settings.max_tokens is not None:
        opcoes["max_completion_tokens"] = settings.max_tokens
    if settings.top_p is not None:
        opcoes["top_p"] = settings.top_p
    if settings.reasoning_effort:
        opcoes["reasoning_effort"] = settings.reasoning_effort
    if settings.api_key:
        opcoes["api_key"] = settings.api_key
    if settings.base_url:
        opcoes["base_url"] = settings.base_url
    return opcoes


async def responder_stream(
    pergunta: str,
    historico: list[dict[str, str]],
    dados: str | None,
) -> AsyncIterator[str]:
    if not settings.configurado:
        raise RuntimeError(
            "A IA ainda não foi configurada. Crie o arquivo .env a partir de .env.example "
            "e preencha LLM_MODEL e LLM_API_KEY."
        )

    resposta = await litellm.acompletion(
        messages=_mensagens(pergunta, historico, dados),
        **_opcoes(),
    )

    async for pedaco in resposta:
        if not pedaco.choices:
            continue
        conteudo = pedaco.choices[0].delta.content
        if conteudo:
            yield conteudo
