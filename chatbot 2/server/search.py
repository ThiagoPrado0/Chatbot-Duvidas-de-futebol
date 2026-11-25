"""Ferramentas de pesquisa na internet usadas pelos agentes do CrewAI."""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from .config import settings

CABECALHOS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}
TEMPO_LIMITE = 18


def _limpar(texto: str | None, limite: int) -> str:
    if not texto:
        return ""
    return " ".join(str(texto).split())[:limite]


def _resultado(
    titulo: str | None, url: str | None, trecho: str | None, data: str | None = None
) -> dict[str, str] | None:
    if not url:
        return None
    item = {
        "titulo": _limpar(titulo, 180) or url,
        "url": url,
        "trecho": _limpar(trecho, 400),
    }
    data_limpa = _limpar(data, 30)
    if data_limpa:
        item["data"] = data_limpa
    return item


def _tavily(consulta: str, quantidade: int) -> list[dict[str, str]]:
    resposta = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": settings.tavily_key,
            "query": consulta,
            "max_results": quantidade,
            "search_depth": "advanced",
            "include_answer": False,
        },
        timeout=TEMPO_LIMITE,
    )
    resposta.raise_for_status()
    itens = resposta.json().get("results", [])
    return [
        r
        for r in (
            _resultado(i.get("title"), i.get("url"), i.get("content"), i.get("published_date"))
            for i in itens
        )
        if r
    ]


def _serper(consulta: str, quantidade: int) -> list[dict[str, str]]:
    resposta = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": settings.serper_key or "", "Content-Type": "application/json"},
        json={"q": consulta, "num": quantidade, "gl": "br", "hl": "pt-br"},
        timeout=TEMPO_LIMITE,
    )
    resposta.raise_for_status()
    itens = resposta.json().get("organic", [])
    return [
        r
        for r in (
            _resultado(i.get("title"), i.get("link"), i.get("snippet"), i.get("date"))
            for i in itens
        )
        if r
    ]


def _duckduckgo(consulta: str, quantidade: int) -> list[dict[str, str]]:
    try:
        from ddgs import DDGS  # pacote novo
    except ImportError:  # compatibilidade com versões antigas
        from duckduckgo_search import DDGS  # type: ignore

    with DDGS() as buscador:
        itens = buscador.text(consulta, max_results=quantidade)

    return [
        r
        for r in (
            _resultado(
                i.get("title"),
                i.get("href") or i.get("url"),
                i.get("body") or i.get("snippet"),
                i.get("date"),
            )
            for i in itens
        )
        if r
    ]


def pesquisar(consulta: str, quantidade: int = 6) -> list[dict[str, str]]:
    """Busca na web usando Tavily/Serper (se configurados) ou DuckDuckGo."""
    consulta = (consulta or "").strip()
    if not consulta:
        raise ValueError("a consulta de busca está vazia")

    provedores: list[tuple[str, Any]] = []
    if settings.tavily_key:
        provedores.append(("Tavily", _tavily))
    if settings.serper_key:
        provedores.append(("Serper", _serper))
    provedores.append(("DuckDuckGo", _duckduckgo))

    erros: list[str] = []
    for nome, funcao in provedores:
        try:
            achados = funcao(consulta, quantidade)
            if achados:
                return achados
            erros.append(f"{nome}: nenhum resultado")
        except Exception as erro:  # tenta o próximo provedor
            erros.append(f"{nome}: {type(erro).__name__} {str(erro)[:120]}")

    raise RuntimeError("busca indisponível (" + "; ".join(erros) + ")")


def _url_segura(url: str) -> bool:
    """Bloqueia esquemas estranhos e endereços internos (proteção básica de SSRF)."""
    partes = urlparse(url)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        return False
    if partes.hostname.lower() in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False
    try:
        ip = ipaddress.ip_address(partes.hostname)
        return ip.is_global
    except ValueError:
        return True


def ler_pagina(url: str) -> str:
    if not _url_segura(url):
        return "URL não permitida: use apenas endereços públicos http/https retornados pela busca."

    resposta = requests.get(url, headers=CABECALHOS, timeout=TEMPO_LIMITE)
    resposta.raise_for_status()
    tipo = resposta.headers.get("Content-Type", "")
    if "html" not in tipo and "text" not in tipo:
        return f"Conteúdo não textual ({tipo or 'desconhecido'}) em {url}."

    sopa = BeautifulSoup(resposta.text, "html.parser")
    for tag in sopa(["script", "style", "noscript", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()

    texto = " ".join(sopa.get_text(" ", strip=True).split())
    if len(texto) < 120:
        return f"A página parece não ter conteúdo útil para leitura ({len(texto)} caracteres)."
    return f"Conteúdo de {url}:\n{texto[:3000]}"


class EntradaBusca(BaseModel):
    consulta: str = Field(..., description="Consulta de busca curta e específica, em português ou inglês.")


class EntradaLeitura(BaseModel):
    url: str = Field(..., description="URL pública (http/https) que deve ser lida na íntegra.")


class BuscarWebTool(BaseTool):
    name: str = "buscar_na_web"
    description: str = (
        "Pesquisa futebol na internet e retorna resultados com título, URL e trecho. "
        "Use para notícias, dados atuais, técnicos, elencos, transferências, lesões, história e estatísticas. "
        "Informe uma consulta curta e específica."
    )
    args_schema: type[BaseModel] = EntradaBusca
    fontes: list[dict[str, Any]] = Field(default_factory=list)
    # Cota por pergunta: a ferramenta recusa chamadas além disso (economia de tokens).
    limite: int = 2
    usos: list[int] = Field(default_factory=list)

    def _run(self, consulta: str) -> str:
        if len(self.usos) >= self.limite:
            return (
                "Cota de buscas desta pergunta esgotada. Não chame a ferramenta de novo: "
                "escreva o relatório com o que já encontrou e diga o que não deu para confirmar."
            )

        try:
            achados = pesquisar(consulta, 4)
        except Exception as erro:
            return f"A busca falhou: {erro}. Tente outra consulta, mais curta."

        self.usos.append(1)

        vistos = {f["url"] for f in self.fontes}
        for item in achados:
            if item["url"] not in vistos:
                self.fontes.append(item)
                vistos.add(item["url"])

        linhas = [f'Resultados da busca por "{consulta}":']
        for indice, item in enumerate(achados, 1):
            quando = f" (publicado em {item['data']})" if item.get("data") else ""
            linhas.append(f"{indice}. {item['titulo']}{quando} — {item['url']}")
            if item["trecho"]:
                linhas.append(f"   {item['trecho']}")
        linhas.append(
            "Lembre-se: copie números e nomes exatamente como aparecem e cite a URL no relatório. "
            "Quando as fontes se contradisserem, fique com a de publicação mais recente e diga a data do fato."
        )
        return "\n".join(linhas)


class LerPaginaTool(BaseTool):
    name: str = "ler_pagina"
    description: str = (
        "Abre uma URL pública encontrada na busca e retorna o texto principal da página. "
        "Use quando o trecho do resultado não for suficiente para confirmar um fato."
    )
    args_schema: type[BaseModel] = EntradaLeitura
    # Cota por pergunta (cada página custa ~750 tokens).
    limite: int = 1
    usos: list[int] = Field(default_factory=list)

    def _run(self, url: str) -> str:
        if len(self.usos) >= self.limite:
            return (
                "Cota de leitura de páginas desta pergunta esgotada. "
                "Responda com os trechos que já tem."
            )
        self.usos.append(1)
        try:
            return ler_pagina(url)
        except Exception as erro:
            return f"Não consegui ler a página {url}: {type(erro).__name__} {str(erro)[:160]}"
