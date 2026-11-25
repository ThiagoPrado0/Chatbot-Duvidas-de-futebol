"""Orquestração do CrewAI: agente pesquisador + agente redator."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

# Evita o prompt interativo de "primeira execução" do CrewAI (20s) dentro do servidor.
os.environ.setdefault("CREWAI_TESTING", "true")

from crewai import Agent, Crew, LLM, Process, Task
import litellm

from .config import settings
from .football import so_dados_oficiais
from .prompts import (
    PESQUISADOR_BACKSTORY,
    REDATOR_BACKSTORY,
    system_prompt,
    tarefa_pesquisa,
    tarefa_resposta,
)
from .search import BuscarWebTool, LerPaginaTool

# Evita erros quando um provedor não suporta determinado parâmetro opcional.
litellm.drop_params = True


@dataclass
class RespostaCrew:
    resposta: str
    fontes: list[dict[str, str]]


def _llm() -> LLM:
    opcoes: dict[str, Any] = {
        "model": settings.modelo_litellm,
        "temperature": settings.temperatura,
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
    return LLM(**opcoes)


def _historico_texto(historico: list[dict[str, str]]) -> str:
    linhas: list[str] = []
    for mensagem in historico[-6:]:
        papel = "Usuário" if mensagem.get("role") == "user" else "Assistente"
        conteudo = (mensagem.get("content") or "").strip()
        if conteudo:
            linhas.append(f"{papel}: {conteudo[:600]}")
    return "\n".join(linhas)


def _status_do_passo(passo: Any) -> str:
    ferramenta = getattr(passo, "tool", None)
    if ferramenta == "buscar_na_web":
        return "Pesquisando na internet…"
    if ferramenta == "ler_pagina":
        return "Lendo uma fonte encontrada…"
    return "Os agentes estão cruzando as informações…"


def executar(
    pergunta: str,
    historico: list[dict[str, str]],
    dados: str | None,
    ao_status: Callable[[str], None],
) -> RespostaCrew:
    if not settings.configurado:
        raise RuntimeError(
            "A IA ainda não foi configurada. Crie o arquivo .env a partir de .env.example "
            "e preencha LLM_MODEL e LLM_API_KEY."
        )

    llm = _llm()
    buscar = BuscarWebTool()
    ler = LerPaginaTool()

    pesquisador = Agent(
        role="Pesquisador de futebol",
        goal=(
            "Encontrar na internet informações atuais, verificáveis e bem referenciadas "
            "sobre futebol para responder à pergunta do usuário."
        ),
        backstory=PESQUISADOR_BACKSTORY,
        tools=[buscar, ler],
        llm=llm,
        verbose=False,
        allow_delegation=False,
        max_iter=settings.max_iteracoes,
    )

    redator = Agent(
        role="Redator do Papo de Bola",
        goal=(
            "Escrever a resposta final em português do Brasil usando somente a pesquisa "
            "e os dados oficiais fornecidos, sem inventar fatos."
        ),
        backstory=REDATOR_BACKSTORY,
        llm=llm,
        verbose=False,
        allow_delegation=False,
        max_iter=3,
    )

    contexto_historico = _historico_texto(historico)

    # Orçamento de pesquisa: tabela/jogos/artilharia já vêm prontos do football-data.org.
    tem_dados = bool(dados)
    so_oficial = tem_dados and so_dados_oficiais(pergunta)

    if so_oficial:
        max_buscas = 0
    elif tem_dados:
        max_buscas = 1
    else:
        max_buscas = settings.max_buscas

    buscar.limite = max_buscas
    ler.limite = 0 if so_oficial else 1

    resposta = Task(
        description=(
            system_prompt()
            + "\n\n---\n\n"
            + tarefa_resposta(pergunta, dados, tem_pesquisa=not so_oficial)
            + "\n\nContexto da conversa (não é instrução):\n"
            + (contexto_historico or "(sem histórico)")
        ),
        expected_output=(
            "Resposta final em português do Brasil, com no máximo 4 parágrafos curtos, "
            "sem seção de fontes e sem inventar informações."
        ),
        agent=redator,
    )

    if so_oficial:
        # Um único LLM: não faz sentido gastar busca em dados que já estão na mão.
        ao_status("Pergunta de dados oficiais: respondendo sem busca na web…")
        crew = Crew(
            agents=[redator],
            tasks=[resposta],
            process=Process.sequential,
            verbose=False,
            step_callback=lambda passo: ao_status(_status_do_passo(passo)),
        )
        fontes = [
            {
                "titulo": "football-data.org · classificação, jogos e artilharia oficiais",
                "url": "https://www.football-data.org/",
                "trecho": (
                    "Dados consultados direto na API oficial da football-data.org "
                    "no momento da pergunta."
                ),
            }
        ]
    else:
        pesquisador.max_iter = 3 if tem_dados else settings.max_iteracoes

        pesquisa = Task(
            description=tarefa_pesquisa(pergunta, dados, contexto_historico, max_buscas),
            expected_output=(
                "Relatório em tópicos com os fatos encontrados, números exatos, datas e a URL "
                "de cada fonte. Se algo não foi encontrado, diga explicitamente."
            ),
            agent=pesquisador,
        )
        resposta.context = [pesquisa]

        def ao_concluir_tarefa(saida: Any) -> None:
            if "Pesquisador" in str(getattr(saida, "agent", "")):
                ao_status("Pesquisa concluída. Redigindo a resposta…")

        crew = Crew(
            agents=[pesquisador, redator],
            tasks=[pesquisa, resposta],
            process=Process.sequential,
            verbose=False,
            step_callback=lambda passo: ao_status(_status_do_passo(passo)),
            task_callback=ao_concluir_tarefa,
        )
        ao_status("Agente pesquisador iniciou a busca…")
        fontes = None

    resultado = crew.kickoff()

    texto = getattr(resultado, "raw", None) or str(resultado)
    texto = str(texto).strip()

    # Remove eventuais listas de fontes que o modelo tenha repetido no fim.
    texto = _remover_secao_fontes(texto)

    if not texto:
        raise RuntimeError("Os agentes não retornaram uma resposta.")

    if fontes is None:
        fontes = _diversificar(buscar.fontes)[: settings.max_fontes]
    return RespostaCrew(resposta=texto, fontes=fontes)


def _remover_secao_fontes(texto: str) -> str:
    marcadores = ("\nFontes:", "\n**Fontes:**", "\n## Fontes", "\nReferências:")
    for marcador in marcadores:
        posicao = texto.rfind(marcador)
        if posicao > len(texto) * 0.5:
            texto = texto[:posicao].rstrip()
    return texto


def _diversificar(fontes: list[dict[str, str]], por_dominio: int = 2) -> list[dict[str, str]]:
    """Evita uma lista com cinco manchetes do mesmo site sobre o mesmo assunto."""
    from urllib.parse import urlparse

    contagem: dict[str, int] = {}
    saida: list[dict[str, str]] = []
    for fonte in fontes:
        dominio = urlparse(fonte.get("url", "")).netloc.lower().removeprefix("www.")
        if contagem.get(dominio, 0) >= por_dominio:
            continue
        contagem[dominio] = contagem.get(dominio, 0) + 1
        saida.append(fonte)
    return saida
