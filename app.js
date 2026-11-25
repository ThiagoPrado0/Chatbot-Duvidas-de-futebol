/* Papo de Bola — front-end conectado à API (FastAPI + CrewAI). */

const chat = document.getElementById("chat");
const form = document.getElementById("form");
const entrada = document.getElementById("entrada");
const botao = document.getElementById("enviar");
const seletor = document.getElementById("modelo");
const vazio = document.getElementById("vazio");
const statusIA = document.getElementById("status-ia");
const limparBotao = document.getElementById("limpar");
const workspace = document.querySelector(".workspace");
const centralEl = document.getElementById("central");
const rodape = document.querySelector(".rodape");
const statusCaixa = document.querySelector(".header-status");
const kicker = document.getElementById("kicker");
const tituloVista = document.getElementById("titulo-vista");
const subVista = document.getElementById("sub-vista");
const compChips = document.getElementById("comp-chips");
const centralConteudo = document.getElementById("central-conteudo");
const atualizarBotao = document.getElementById("atualizar");
const abasSecao = [...document.querySelectorAll(".central-tabs button[data-secao]")];
const navBotoes = [...document.querySelectorAll(".side-link, .nav-mobile button")];

const CHAVE_MEMORIA = "papo-de-bola-historico";
let historico = [];
let ocupado = false;

/* ---------- utilidades ---------- */

const escapar = (texto) =>
  String(texto ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

const fmt = (t) => formatarMarkdown(t);

function formatarLinha(linha) {
  return escapar(linha)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/^[*-] /, "• ");
}

const ehLinhaTabela = (linha) => /^\s*\|.*\|\s*$/.test(linha);
const ehSeparadorTabela = (linha) =>
  /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/.test(linha);
const celulasTabela = (linha) =>
  linha
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((celula) => celula.trim());

function tabelaHTML(cabecalho, corpo) {
  const th = cabecalho.map((c) => `<th scope="col">${formatarLinha(c)}</th>`).join("");
  const trs = corpo
    .map((linha) => `<tr>${linha.map((c) => `<td>${formatarLinha(c)}</td>`).join("")}</tr>`)
    .join("");
  return `<div class="tabela-md"><table><thead><tr>${th}</tr></thead><tbody>${trs}</tbody></table></div>`;
}

/* Markdown enxuto: negrito, marcadores e tabelas com | ... |. */
function formatarMarkdown(texto) {
  const linhas = String(texto ?? "").split("\n");
  const saida = [];

  for (let i = 0; i < linhas.length; i += 1) {
    if (ehLinhaTabela(linhas[i]) && ehSeparadorTabela(linhas[i + 1] || "")) {
      const cabecalho = celulasTabela(linhas[i]);
      const corpo = [];
      i += 2;
      while (i < linhas.length && ehLinhaTabela(linhas[i])) {
        corpo.push(celulasTabela(linhas[i]));
        i += 1;
      }
      i -= 1;
      saida.push(tabelaHTML(cabecalho, corpo));
      continue;
    }
    saida.push(formatarLinha(linhas[i]));
  }

  return saida.join("\n");
}

function criar(tipo) {
  if (vazio.isConnected) vazio.remove();

  const row = document.createElement("div");
  row.className = tipo === "user" ? "row user" : "row bot" + (tipo === "erro" ? " erro" : "");
  row.innerHTML =
    (tipo === "user" ? "" : '<div class="av">⚽</div>') +
    '<div class="bolha"><div class="chip"></div><div class="txt"></div><div class="fontes"></div></div>';

  chat.appendChild(row);
  chat.scrollTop = chat.scrollHeight;

  const resultado = {
    row,
    txt: row.querySelector(".txt"),
    chip: row.querySelector(".chip"),
    fontes: row.querySelector(".fontes"),
  };

  if (tipo !== "user") {
    const acoes = document.createElement("div");
    acoes.className = "acoes";
    const copiar = document.createElement("button");
    copiar.type = "button";
    copiar.className = "copiar";
    copiar.innerHTML = '<span aria-hidden="true">⧉</span> Copiar';
    copiar.title = "Copiar esta resposta";
    copiar.addEventListener("click", () => copiarTexto(resultado.txt.innerText, copiar));
    acoes.append(copiar);
    row.querySelector(".bolha").append(acoes);
    resultado.copiar = copiar;
  }

  return resultado;
}

async function copiarTexto(texto, botaoCopiar) {
  const limpo = (texto || "").replace(/\n?Copiar\s*$/, "").trim();
  try {
    await navigator.clipboard.writeText(limpo);
  } catch {
    const area = document.createElement("textarea");
    area.value = limpo;
    area.style.cssText = "position:fixed;opacity:0";
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  botaoCopiar.classList.add("feito");
  botaoCopiar.innerHTML = '<span aria-hidden="true">✓</span> Copiado';
  setTimeout(() => {
    botaoCopiar.classList.remove("feito");
    botaoCopiar.innerHTML = '<span aria-hidden="true">⧉</span> Copiar';
  }, 1800);
}

function rolarSePerto() {
  const perto = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 140;
  if (perto) chat.scrollTop = chat.scrollHeight;
}

function definirChip(el, texto, tipo) {
  el.textContent = texto || "";
  el.className = "chip" + (tipo === "aviso" ? " aviso" : "");
}

function renderizarFontes(el, fontes) {
  const vistos = new Set();
  const lista = (fontes || []).filter((f) => {
    if (!f || !f.url || vistos.has(f.url)) return false;
    vistos.add(f.url);
    return true;
  });
  if (!lista.length) return;

  const tituloCurto = (f) => {
    const texto = f.titulo || f.url;
    return texto.length > 72 ? `${texto.slice(0, 72).trimEnd()}…` : texto;
  };
  const criarLink = (f) => {
    const a = document.createElement("a");
    a.href = f.url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.textContent = tituloCurto(f);
    a.title = f.titulo || f.url;
    return a;
  };

  // Só as primeiras aparecem na linha; o resto fica no bloco expansível.
  const destaque = lista.slice(0, 3);
  const restantes = lista.slice(3);

  el.append("Fontes: ");
  destaque.forEach((f, i) => {
    if (i) el.append(" · ");
    el.append(criarLink(f));
  });
  if (restantes.length) el.append(` · +${restantes.length}`);

  if (!restantes.length && !lista.some((f) => f.trecho)) return;

  const detalhes = document.createElement("details");
  const resumo = document.createElement("summary");
  resumo.textContent = restantes.length
    ? `Ver todas as ${lista.length} fontes e trechos usados`
    : "Ver trechos usados pela IA";
  detalhes.append(resumo);

  if (restantes.length) {
    const listaCompleta = document.createElement("div");
    listaCompleta.style.cssText = "margin-top:8px;white-space:pre-wrap";
    restantes.forEach((f, i) => {
      if (i) listaCompleta.append("\n");
      const a = criarLink(f);
      a.style.whiteSpace = "normal";
      listaCompleta.append(a);
    });
    detalhes.append(listaCompleta);
  }

  lista.filter((f) => f.trecho).forEach((f) => {
    const bloco = document.createElement("div");
    bloco.style.cssText = "margin-top:8px;white-space:pre-wrap";
    bloco.textContent = `${f.titulo}\n${f.url}\n${f.trecho}`;
    detalhes.append(bloco);
  });

  el.append(detalhes);
}

/* ---------- leitura do stream SSE ---------- */

async function lerEventos(resposta, aoEvento) {
  const leitor = resposta.body.getReader();
  const decodificador = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await leitor.read();
    if (done) break;

    buffer += decodificador.decode(value, { stream: true });

    let corte;
    while ((corte = buffer.indexOf("\n\n")) !== -1) {
      const bloco = buffer.slice(0, corte);
      buffer = buffer.slice(corte + 2);

      let evento = "message";
      let dados = "";
      for (const linha of bloco.split("\n")) {
        if (linha.startsWith("event:")) evento = linha.slice(6).trim();
        else if (linha.startsWith("data:")) dados += linha.slice(5).trim();
      }
      if (!dados) continue;

      let payload;
      try {
        payload = JSON.parse(dados);
      } catch {
        continue;
      }
      aoEvento(evento, payload);
    }
  }
}

/* ---------- envio da pergunta ---------- */

async function enviar(texto) {
  texto = (texto || "").trim();
  if (!texto || ocupado) return;

  const modo = seletor.value || "crew";

  criar("user").txt.textContent = texto;
  entrada.value = "";
  entrada.style.height = "auto";
  ocupado = true;
  botao.disabled = true;

  const { row, txt, chip, fontes } = criar("bot");

  let resposta = "";
  let fontesRecebidas = [];

  try {
    const respostaHttp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mensagem: texto, historico: historico.slice(-10), modo }),
    });

    if (!respostaHttp.ok || !respostaHttp.body) {
      const detalhe = await respostaHttp.text().catch(() => "");
      throw new Error(`O servidor respondeu HTTP ${respostaHttp.status}. ${detalhe.slice(0, 200)}`);
    }

    let erro = null;

    await lerEventos(respostaHttp, (evento, dados) => {
      if (evento === "status") {
        definirChip(chip, dados.texto, dados.tipo === "aviso" ? "aviso" : "");
        rolarSePerto();
      } else if (evento === "fonte") {
        fontesRecebidas.push(dados);
      } else if (evento === "token") {
        resposta += dados.texto || "";
        txt.innerHTML = fmt(resposta);
        rolarSePerto();
      } else if (evento === "final") {
        resposta = dados.resposta ?? resposta;
        txt.innerHTML = fmt(resposta);
        if (Array.isArray(dados.fontes) && dados.fontes.length) fontesRecebidas = dados.fontes;
        renderizarFontes(fontes, fontesRecebidas);
        if (!chip.textContent.startsWith("📊") && !chip.classList.contains("aviso")) {
          definirChip(
            chip,
            fontesRecebidas.length
              ? `🔎 ${fontesRecebidas.length} ${fontesRecebidas.length === 1 ? "fonte consultada" : "fontes consultadas"}`
              : "",
            "",
          );
        }
        rolarSePerto();
      } else if (evento === "erro") {
        erro = new Error(dados.texto || "Erro desconhecido.");
      }
    });

    if (erro) throw erro;
    if (!resposta.trim()) throw new Error("A IA não retornou texto. Tente novamente.");

    historico.push(
      { role: "user", content: texto },
      {
        role: "assistant",
        content: resposta,
        chip: chip.textContent || "",
        fontes: fontesRecebidas.map((f) => ({
          titulo: f.titulo,
          url: f.url,
          trecho: f.trecho,
        })),
      },
    );
    salvar();
  } catch (e) {
    row.classList.add("erro");
    definirChip(chip, "", "");
    txt.textContent = "Algo deu errado: " + e.message;
  } finally {
    ocupado = false;
    botao.disabled = !entrada.value.trim();
    entrada.focus();
  }
}

/* ---------- configuração vinda da API ---------- */

async function carregarConfig() {
  try {
    const resposta = await fetch("/api/config");
    if (!resposta.ok) throw new Error("HTTP " + resposta.status);
    const config = await resposta.json();

    statusIA.textContent = config.configurado
      ? `CrewAI · ${config.modelo}`
      : "IA não configurada";

    const busca = { tavily: "Tavily", serper: "Google (Serper)", duckduckgo: "DuckDuckGo" };
    statusIA.parentElement.title =
      `Provedor: ${config.provedor} · Modelo: ${config.modelo} · ` +
      `Busca: ${busca[config.pesquisa_web] || config.pesquisa_web} · ` +
      `Dados oficiais: ${config.dados_oficiais ? "ativos" : "sem token"}`;

    if (!config.configurado && vazio.isConnected) {
      const aviso = document.createElement("div");
      aviso.className = "welcome-tag";
      aviso.style.cssText =
        "border-color:#f0d998;background:#fff8e7;color:#866314;margin-top:14px";
      aviso.textContent = "⚠️ IA NÃO CONFIGURADA — preencha o .env e reinicie o servidor";
      vazio.appendChild(aviso);
    }
  } catch {
    statusIA.textContent = "API offline";
    statusIA.parentElement.title = "O servidor FastAPI não respondeu em /api/config.";
    criar("erro").txt.textContent =
      "Não consegui falar com a API. Inicie o servidor (start.bat ou " +
      '"uvicorn server.main:app --port 8000") e recarregue esta página.';
  }
}

/* ---------- memória da conversa ---------- */

function salvar() {
  try {
    localStorage.setItem(CHAVE_MEMORIA, JSON.stringify(historico.slice(-20)));
  } catch {
    /* armazenamento indisponível */
  }
}

function restaurar() {
  try {
    historico = JSON.parse(localStorage.getItem(CHAVE_MEMORIA)) || [];
  } catch {
    historico = [];
  }

  historico.forEach((m) => {
    const { txt, fontes, chip } = criar(m.role === "user" ? "user" : "bot");
    if (m.role === "user") txt.textContent = m.content;
    else {
      txt.innerHTML = fmt(m.content);
      if (m.chip) definirChip(chip, m.chip, "");
      if (Array.isArray(m.fontes) && m.fontes.length) renderizarFontes(fontes, m.fontes);
    }
  });
}

/* ---------- ligações de interface ---------- */

form.addEventListener("submit", (e) => {
  e.preventDefault();
  enviar(entrada.value);
});

entrada.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

entrada.addEventListener("input", () => {
  entrada.style.height = "auto";
  entrada.style.height = Math.min(entrada.scrollHeight, 120) + "px";
});

document.querySelectorAll(".sugestoes button").forEach((b) => {
  b.addEventListener("click", () => enviar(b.textContent));
});

limparBotao.addEventListener("click", () => {
  historico = [];
  salvar();
  chat.replaceChildren(vazio);
  entrada.focus();
});

/* ---------- Central de futebol ---------- */

const CABECALHOS = {
  assistente: {
    kicker: "SEU COMPANHEIRO DE FUTEBOL",
    titulo: "Papo de Bola",
    sub: "Tática, história e dados do mundo da bola.",
    doc: "Papo de Bola | Assistente de Futebol",
  },
  central: {
    kicker: "DADOS OFICIAIS",
    titulo: "Central de futebol",
    sub: "Classificação, jogos e artilheiros — direto da football-data.org.",
    doc: "Central de futebol | Papo de Bola",
  },
};

const estadoCentral = {
  comp: localStorage.getItem("pdb-comp") || "BSA",
  secao: localStorage.getItem("pdb-secao") || "tabela",
  competicoes: [],
  cache: new Map(),
  requisicao: 0,
  vista: localStorage.getItem("pdb-vista") === "central" ? "central" : "assistente",
};

function trocarVista(vista, focar = false) {
  const central = vista === "central";
  const info = CABECALHOS[central ? "central" : "assistente"];

  workspace.dataset.vista = vista;
  centralEl.hidden = !central;
  chat.hidden = central;
  form.hidden = central;
  rodape.hidden = central;
  seletor.hidden = central;
  statusCaixa.hidden = central;
  limparBotao.hidden = central;

  kicker.textContent = info.kicker;
  tituloVista.textContent = info.titulo;
  subVista.textContent = info.sub;
  document.title = info.doc;
  estadoCentral.vista = vista;
  localStorage.setItem("pdb-vista", vista);

  navBotoes.forEach((b) => {
    const ativo = b.dataset.view === vista;
    if (b.classList.contains("side-link")) b.classList.toggle("active", ativo);
    if (ativo) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });

  if (central) {
    if (!estadoCentral.competicoes.length) carregarCompeticoes();
    else mostrarSecao();
  } else if (focar) {
    entrada.focus();
  }
}

async function carregarCompeticoes() {
  esqueleto();
  try {
    const resposta = await fetch("/api/competicoes");
    if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
    const dados = await resposta.json();

    if (!dados.dados_oficiais) {
      compChips.replaceChildren();
      atualizarBotao.hidden = true;
      semDadosOficiais();
      return;
    }

    atualizarBotao.hidden = false;
    estadoCentral.competicoes = dados.competicoes || [];
    if (!estadoCentral.competicoes.some((c) => c.code === estadoCentral.comp)) {
      estadoCentral.comp = estadoCentral.competicoes[0]?.code || "BSA";
      localStorage.setItem("pdb-comp", estadoCentral.comp);
    }
    desenharChips();
    mostrarSecao();
  } catch (e) {
    estadoErro("Não consegui carregar as competições.", e.message, carregarCompeticoes);
  }
}

function desenharChips() {
  compChips.replaceChildren();
  estadoCentral.competicoes.forEach((competicao) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "comp-chip";
    chip.setAttribute("role", "tab");
    chip.dataset.code = competicao.code;
    chip.textContent = competicao.nome;
    chip.setAttribute("aria-selected", String(competicao.code === estadoCentral.comp));
    chip.setAttribute("aria-controls", "central-conteudo");
    chip.tabIndex = competicao.code === estadoCentral.comp ? 0 : -1;
    chip.addEventListener("click", () => {
      if (estadoCentral.comp === competicao.code) return;
      estadoCentral.comp = competicao.code;
      localStorage.setItem("pdb-comp", competicao.code);
      compChips.querySelectorAll(".comp-chip").forEach((outro) => {
        const ativo = outro.dataset.code === competicao.code;
        outro.setAttribute("aria-selected", String(ativo));
        outro.tabIndex = ativo ? 0 : -1;
      });
      mostrarSecao();
    });
    compChips.append(chip);
  });
}

function marcarSecao(secao) {
  estadoCentral.secao = secao;
  localStorage.setItem("pdb-secao", secao);
  abasSecao.forEach((aba) => {
    const ativo = aba.dataset.secao === secao;
    aba.setAttribute("aria-selected", String(ativo));
    aba.tabIndex = ativo ? 0 : -1;
  });
}

/* Setas/Home/End navegam entre as abas, como manda o padrão ARIA.
   Com ativar:false, a seta só move o foco (Enter/Espaço ativam) — evita
   disparar uma requisição a cada tecla segurada. */
function teclasDeAbas(container, seletor, { ativar = true } = {}) {
  container.addEventListener("keydown", (evento) => {
    if (!["ArrowRight", "ArrowLeft", "ArrowUp", "ArrowDown", "Home", "End"].includes(evento.key)) {
      return;
    }
    const abas = [...container.querySelectorAll(seletor)];
    const atual = abas.indexOf(evento.target.closest(seletor));
    if (atual < 0) return;

    let destino = null;
    if (evento.key === "Home") destino = abas[0];
    else if (evento.key === "End") destino = abas[abas.length - 1];
    else {
      const passo = evento.key === "ArrowRight" || evento.key === "ArrowDown" ? 1 : -1;
      destino = abas[(atual + passo + abas.length) % abas.length];
    }
    if (!destino) return;
    evento.preventDefault();
    destino.focus();
    if (ativar) destino.click();
    else abas.forEach((aba) => (aba.tabIndex = aba === destino ? 0 : -1));
  });
}

async function mostrarSecao(forcar = false) {
  const { comp, secao, cache } = estadoCentral;
  const chave = `${comp}:${secao}`;

  if (!forcar && cache.has(chave)) {
    renderizarSecao(cache.get(chave));
    return;
  }

  const marca = ++estadoCentral.requisicao;
  esqueleto();
  try {
    const resposta = await fetch(
      `/api/competicao/${encodeURIComponent(comp)}?secao=${encodeURIComponent(secao)}`,
    );
    const dados = await resposta.json().catch(() => ({}));
    if (!resposta.ok) throw new Error(dados.detail || `HTTP ${resposta.status}`);
    if (marca !== estadoCentral.requisicao) return;
    cache.set(chave, dados);
    renderizarSecao(dados);
  } catch (e) {
    if (marca !== estadoCentral.requisicao) return;
    estadoErro("Não foi possível carregar os dados.", e.message, () => mostrarSecao(true));
  }
}function renderizarSecao(dados) {
  centralConteudo.setAttribute("aria-busy", "false");
  centralConteudo.replaceChildren();
  if (dados.secao === "jogos") renderizarJogos(dados);
  else if (dados.secao === "artilheiros") renderizarArtilheiros(dados);
  else renderizarTabela(dados);
  ajustarEscudos(centralConteudo);
}

function esqueleto() {
  centralConteudo.setAttribute("aria-busy", "true");
  centralConteudo.innerHTML =
    '<div class="painel"><div class="esqueleto">' + "<i></i>".repeat(8) + "</div></div>";
}

function semDadosOficiais() {
  centralConteudo.setAttribute("aria-busy", "false");
  centralConteudo.innerHTML =
    '<div class="painel"><div class="estado">' +
    '<span class="icone" aria-hidden="true">⚙️</span>' +
    "<strong>Dados oficiais desligados</strong>" +
    "<span>Coloque seu token da football-data.org em <code>FOOTBALL_DATA_TOKEN</code> no arquivo " +
    "<code>.env</code> e reinicie o servidor para ver classificação, jogos e artilheiros.</span>" +
    '<span><a href="https://www.football-data.org/client/register" target="_blank" rel="noopener noreferrer">Cadastro gratuito em football-data.org</a></span>' +
    "</div></div>";
}

function estadoErro(titulo, detalhe, acao) {
  centralConteudo.setAttribute("aria-busy", "false");
  centralConteudo.replaceChildren();

  const painel = document.createElement("div");
  painel.className = "painel";
  const estado = document.createElement("div");
  estado.className = "estado";
  estado.innerHTML =
    '<span class="icone" aria-hidden="true">⚠️</span>' +
    `<strong>${escapar(titulo)}</strong>` +
    `<span>${escapar(detalhe || "")}</span>`;

  if (acao) {
    const tentar = document.createElement("button");
    tentar.type = "button";
    tentar.textContent = "Tentar de novo";
    tentar.addEventListener("click", acao);
    estado.append(tentar);
  }

  painel.append(estado);
  centralConteudo.append(painel);
}

function criarPainel(titulo, meta, pergunta) {
  const painel = document.createElement("div");
  painel.className = "painel";
  const topo = document.createElement("div");
  topo.className = "painel-topo";
  topo.innerHTML = `<div class="painel-titulo">${escapar(titulo)}</div>`;

  const info = document.createElement("div");
  info.className = "painel-info";
  const detalhe = document.createElement("div");
  detalhe.className = "painel-meta";
  detalhe.textContent = meta || "";
  info.append(detalhe);

  if (pergunta) {
    const acao = document.createElement("button");
    acao.type = "button";
    acao.className = "painel-acao";
    acao.innerHTML = '<span aria-hidden="true">✦</span> Perguntar à IA';
    acao.title = `Levar para o assistente: ${pergunta}`;
    acao.addEventListener("click", () => perguntarSobre(pergunta));
    info.append(acao);
  }

  topo.append(info);
  painel.append(topo);
  return painel;
}

/* Leva uma pergunta pronta da Central para o assistente, sem enviar sozinho. */
function perguntarSobre(pergunta) {
  trocarVista("assistente", true);
  entrada.value = pergunta;
  entrada.dispatchEvent(new Event("input"));
  entrada.focus();
  entrada.setSelectionRange(pergunta.length, pergunta.length);
}

function escudoHTML(url, sigla) {
  if (!url) {
    return `<span class="escudo-sigla" aria-hidden="true">${escapar((sigla || "?").slice(0, 3))}</span>`;
  }
  return `<img src="${escapar(url)}" alt="" loading="lazy" data-sigla="${escapar(sigla || "")}">`;
}

function ajustarEscudos(raiz) {
  raiz.querySelectorAll("img[data-sigla]").forEach((img) => {
    img.addEventListener(
      "error",
      () => {
        const alternativa = document.createElement("span");
        alternativa.className = "escudo-sigla";
        alternativa.setAttribute("aria-hidden", "true");
        alternativa.textContent = img.dataset.sigla || "?";
        img.replaceWith(alternativa);
      },
      { once: true },
    );
  });
}

function sinalSaldo(valor) {
  if (valor === null || valor === undefined) return "–";
  return valor > 0 ? `+${valor}` : String(valor);
}

function renderizarTabela(dados) {
  const painel = criarPainel(
    dados.nome,
    `Atualizado em ${dados.atualizado_em}`,
    `Como está a tabela do ${dados.nome}?`,
  );
  const tabela = document.createElement("table");
  tabela.className = "tabela";
  tabela.innerHTML =
    `<caption>Classificação de ${escapar(dados.nome)}</caption>` +
    "<thead><tr>" +
    '<th scope="col">#</th><th scope="col">Equipe</th>' +
    '<th scope="col">P</th><th scope="col">J</th>' +
    '<th scope="col" class="col-extra">V</th><th scope="col" class="col-extra">E</th>' +
    '<th scope="col" class="col-extra">D</th><th scope="col" class="col-extra">SG</th>' +
    "</tr></thead>";

  const corpo = document.createElement("tbody");
  const zonas = dados.zonas;

  dados.grupos.forEach((grupo) => {
    if (grupo.grupo) {
      const linha = document.createElement("tr");
      linha.className = "grupo";
      linha.innerHTML = `<td colspan="8">${escapar(grupo.grupo)}</td>`;
      corpo.append(linha);
    }

    grupo.linhas.forEach((item) => {
      const linha = document.createElement("tr");
      if (zonas && item.posicao <= zonas.superior) linha.className = "zona-alta";
      else if (zonas && item.posicao > grupo.linhas.length - zonas.inferior) {
        linha.className = "zona-baixa";
      }
      linha.innerHTML =
        `<td class="pos">${escapar(item.posicao)}</td>` +
        `<td><div class="equipe">${escudoHTML(item.escudo, item.sigla)}<span>${escapar(item.time)}</span></div></td>` +
        `<td class="pontos">${escapar(item.pontos)}</td>` +
        `<td>${escapar(item.jogos)}</td>` +
        `<td class="col-extra">${escapar(item.vitorias)}</td>` +
        `<td class="col-extra">${escapar(item.empates)}</td>` +
        `<td class="col-extra">${escapar(item.derrotas)}</td>` +
        `<td class="col-extra">${sinalSaldo(item.saldo)}</td>`;
      corpo.append(linha);
    });
  });

  tabela.append(corpo);
  const moldura = document.createElement("div");
  moldura.className = "tabela-wrap";
  moldura.append(tabela);
  painel.append(moldura);

  if (zonas) {
    const legenda = document.createElement("div");
    legenda.className = "painel-legenda";
    legenda.innerHTML =
      `<span class="legenda"><i style="background:#2f9e5a"></i>${escapar(zonas.legenda_alta)} · topo da tabela</span>` +
      `<span class="legenda"><i style="background:#d4645a"></i>${escapar(zonas.legenda_baixa)} · parte de baixo</span>`;
    painel.append(legenda);
  }

  centralConteudo.append(painel);
}

function linhaJogo(jogo) {
  const linha = document.createElement("div");
  linha.className = "jogo";
  linha.setAttribute("role", "group");

  const [dia, hora] = String(jogo.data || "").split(" ");
  const temPlacar = jogo.gols_casa !== null && jogo.gols_casa !== undefined;
  const placar = temPlacar
    ? `<span class="jogo-placar" aria-label="${escapar(jogo.gols_casa)} a ${escapar(jogo.gols_fora)}">${escapar(jogo.gols_casa)} × ${escapar(jogo.gols_fora)}</span>`
    : `<span class="jogo-placar hora">${escapar(hora || "")}</span>`;

  linha.setAttribute(
    "aria-label",
    `${jogo.casa} ${temPlacar ? ` ${jogo.gols_casa} a ${jogo.gols_fora} ` : " contra "} ${jogo.fora}, ${jogo.data}`,
  );

  linha.innerHTML =
    `<div class="jogo-data">${jogo.rodada ? `R${escapar(jogo.rodada)}` : ""}<b>${escapar(dia || "")}</b></div>` +
    `<div class="jogo-time casa">${escapar(jogo.casa)}${escudoHTML(jogo.casa_escudo, jogo.casa_sigla)}</div>` +
    placar +
    `<div class="jogo-time fora">${escudoHTML(jogo.fora_escudo, jogo.fora_sigla)}${escapar(jogo.fora)}</div>`;
  return linha;
}

function renderizarJogos(dados) {
  const blocos = [
    ["Próximos jogos", dados.proximos, `Quais são os próximos jogos do ${dados.nome}?`],
    [
      "Últimos resultados",
      [...(dados.ultimos || [])].reverse(),
      `Quais foram os últimos resultados do ${dados.nome}?`,
    ],
  ];

  let mostrou = false;
  blocos.forEach(([titulo, lista, pergunta]) => {
    if (!lista || !lista.length) return;
    mostrou = true;
    const painel = criarPainel(
      `${dados.nome} · ${titulo}`,
      `Atualizado em ${dados.atualizado_em}`,
      pergunta,
    );
    lista.forEach((jogo) => painel.append(linhaJogo(jogo)));
    centralConteudo.append(painel);
  });

  if (!mostrou) {
    estadoErro("Sem jogos disponíveis", "A competição não retornou partidas agora.", () =>
      mostrarSecao(true),
    );
  }
}

function renderizarArtilheiros(dados) {
  const painel = criarPainel(
    `${dados.nome} · Artilheiros`,
    `Atualizado em ${dados.atualizado_em}`,
    `Quem são os artilheiros do ${dados.nome}?`,
  );
  const lista = document.createElement("div");

  dados.artilheiros.forEach((item) => {
    const linha = document.createElement("div");
    linha.className = "goleador";
    const assistencias = item.assistencias
      ? ` · ${item.assistencias} assistência${item.assistencias === 1 ? "" : "s"}`
      : "";
    linha.innerHTML =
      `<span class="pos${item.posicao <= 3 ? " destaque" : ""}">${escapar(item.posicao)}</span>` +
      escudoHTML(item.escudo, item.time) +
      `<div class="quem"><strong>${escapar(item.jogador)}</strong><small>${escapar(item.time)}${escapar(assistencias)}</small></div>` +
      `<span class="num">${escapar(item.gols)}<small>gols</small></span>`;
    lista.append(linha);
  });

  painel.append(lista);
  centralConteudo.append(painel);
}

/* ---------- inicialização ---------- */

abasSecao.forEach((aba) => {
  aba.addEventListener("click", () => {
    marcarSecao(aba.dataset.secao);
    mostrarSecao();
  });
});

teclasDeAbas(compChips, ".comp-chip", { ativar: false });
teclasDeAbas(document.querySelector(".central-tabs"), "button[data-secao]");

atualizarBotao.addEventListener("click", async () => {
  if (atualizarBotao.disabled) return;
  atualizarBotao.disabled = true;
  atualizarBotao.classList.add("girando");
  estadoCentral.cache.clear();
  try {
    await mostrarSecao(true);
  } finally {
    atualizarBotao.disabled = false;
    atualizarBotao.classList.remove("girando");
  }
});

navBotoes.forEach((botaoNav) => {
  botaoNav.addEventListener("click", () => trocarVista(botaoNav.dataset.view, true));
});

const modoSalvo = localStorage.getItem("pdb-modo");
if (modoSalvo) seletor.value = modoSalvo;
seletor.addEventListener("change", () => localStorage.setItem("pdb-modo", seletor.value));

entrada.addEventListener("input", () => {
  if (!ocupado) botao.disabled = !entrada.value.trim();
});
botao.disabled = !entrada.value.trim();

marcarSecao(estadoCentral.secao);
restaurar();
carregarConfig();
trocarVista(estadoCentral.vista);
