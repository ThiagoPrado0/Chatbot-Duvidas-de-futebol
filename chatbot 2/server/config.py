"""Configuração central da aplicação (lida do arquivo .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")


def _inteiro(nome: str, padrao: int) -> int:
    try:
        return int(os.getenv(nome, padrao))
    except (TypeError, ValueError):
        return padrao


def _decimal(nome: str, padrao: float) -> float:
    try:
        return float(os.getenv(nome, padrao))
    except (TypeError, ValueError):
        return padrao


def _primeira_chave() -> str | None:
    """Aceita LLM_API_KEY ou a chave específica do provedor."""
    for nome in (
        "LLM_API_KEY",
        "OPENAI_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "DEEPSEEK_API_KEY",
        "TOGETHER_API_KEY",
    ):
        valor = (os.getenv(nome) or "").strip()
        if valor:
            return valor
    return None


def _reasoning_effort() -> str | None:
    """O CrewAI só aceita estes valores; "default" (Groq) vira None."""
    valor = (os.getenv("LLM_REASONING_EFFORT") or "").strip().lower()
    validos = {"none", "minimal", "low", "medium", "high", "xhigh"}
    return valor if valor in validos else None


@dataclass(frozen=True)
class Config:
    modelo: str
    api_key: str | None
    base_url: str | None
    temperatura: float
    max_tokens: int | None
    top_p: float | None
    reasoning_effort: str | None
    max_iteracoes: int
    football_token: str | None
    tavily_key: str | None
    serper_key: str | None
    max_fontes: int
    max_buscas: int

    @property
    def modelo_litellm(self) -> str:
        """Monta o identificador que o LiteLLM/CrewAI entende.

        Quando LLM_BASE_URL aponta para um endpoint compatível com OpenAI
        (DeepSeek, Ollama, vLLM, LM Studio...), o modelo precisa do prefixo
        ``openai/`` para o LiteLLM usar o cliente certo.
        """
        modelo = self.modelo.strip()
        if self.base_url and "/" not in modelo:
            return f"openai/{modelo}"
        return modelo

    @property
    def provedor(self) -> str:
        if "/" in self.modelo_litellm:
            return self.modelo_litellm.split("/", 1)[0]
        return "openai"

    @property
    def configurado(self) -> bool:
        if self.api_key:
            return True
        # Ollama/local não exige chave.
        if self.modelo.startswith("ollama"):
            return True
        return bool(self.base_url and ("localhost" in self.base_url or "127.0.0.1" in self.base_url))

    @property
    def motor_busca(self) -> str:
        if self.tavily_key:
            return "tavily"
        if self.serper_key:
            return "serper"
        return "duckduckgo"


settings = Config(
    modelo=os.getenv("LLM_MODEL", "groq/qwen/qwen3.8-27b").strip(),
    api_key=_primeira_chave(),
    base_url=(os.getenv("LLM_BASE_URL") or "").strip() or None,
    temperatura=_decimal("LLM_TEMPERATURE", 0.2),
    max_tokens=_inteiro("LLM_MAX_TOKENS", 2048),
    top_p=_decimal("LLM_TOP_P", 0.95),
    reasoning_effort=_reasoning_effort(),
    max_iteracoes=_inteiro("MAX_ITERACOES", 4),
    football_token=(os.getenv("FOOTBALL_DATA_TOKEN") or "").strip() or None,
    tavily_key=(os.getenv("TAVILY_API_KEY") or "").strip() or None,
    serper_key=(os.getenv("SERPER_API_KEY") or "").strip() or None,
    max_fontes=_inteiro("MAX_FONTES", 8),
    max_buscas=_inteiro("MAX_BUSCAS", 2),
)
