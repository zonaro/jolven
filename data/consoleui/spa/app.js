// app.js — Jolven Console SPA (mínima, offline)
// Referência visual: Aurora Launcher (GPL-3.0, codebyallan), adaptado ao Jolven.
// A ponte com o Python usa window.webkit.messageHandlers.jolven (WebKitGTK).

(function () {
  "use strict";

  // ---------- Canal bidirecional com o Python ----------
  let __cbContador = 0;
  window.__jolven_cb = {};

  function enviarComando(comando, parametros = {}) {
    const handler = window.webkit && window.webkit.messageHandlers
      ? window.webkit.messageHandlers.jolven
      : null;
    if (!handler) {
      avisarPonte("indisponível");
      return Promise.reject(new Error("ponte indisponível"));
    }
    const id = "cmd_" + (++__cbContador) + "_" + Date.now().toString(36);
    return new Promise((resolve, reject) => {
      window.__jolven_cb[id] = { resolve, reject };
      const msg = { versao: "1", comando, parametros, id };
      handler.postMessage(JSON.stringify(msg));
    });
  }

  function avisarPonte(status) {
    const el = document.getElementById("status-ponte");
    if (el) el.textContent = "Ponte WebKit: " + status;
  }

  // Sinaliza que a SPA está pronta (recebido pelo console_shell).
  function sinalizarPronto() {
    const evento = new CustomEvent("jolven-pronto", { detail: { origem: "spa" } });
    window.dispatchEvent(evento);
    avisarPonte("ativa");
  }

  // ---------- Dados de jogos (adaptador #183) ----------
  const JOGOS = [];
  let indiceSelecionado = 0;
  let jogoEmExecucao = false;

  // ---------- Render ----------
  const triagem = document.getElementById("triagem");
  const heroTitulo = document.getElementById("hero-titulo");
  const heroDescricao = document.getElementById("hero-descricao");
  const heroCapa = document.getElementById("hero-capa");
  const btnJogar = document.getElementById("btn-jogar");
  const btnParar = document.getElementById("btn-parar");

  function criarTile(jogo, indice) {
    const tile = document.createElement("div");
    tile.className = "tile";
    tile.tabIndex = indice === indiceSelecionado ? 0 : -1;
    tile.setAttribute("role", "listitem");
    tile.setAttribute("aria-label", jogo.nome + ", " + (jogo.plataforma || jogo.base_source));
    tile.dataset.id = jogo.id;

    const img = document.createElement("img");
    img.src = jogo.capa;
    img.alt = jogo.nome;
    img.loading = "lazy";

    const rotulo = document.createElement("div");
    rotulo.className = "rotulo";
    rotulo.textContent = jogo.nome;

    tile.appendChild(img);
    tile.appendChild(rotulo);

    tile.addEventListener("click", () => selecionar(indice));
    tile.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        selecionar(indice);
      }
      if (ev.key === "ArrowRight") proximo();
      if (ev.key === "ArrowLeft") anterior();
    });

    return tile;
  }

  function renderCarrossel() {
    triagem.innerHTML = "";
    JOGOS.forEach((jogo, i) => {
      triagem.appendChild(criarTile(jogo, i));
    });
    aplicarSelecao();
  }

  function aplicarSelecao() {
    const tiles = triagem.querySelectorAll(".tile");
    tiles.forEach((tile, i) => {
      const selecionado = i === indiceSelecionado;
      tile.classList.toggle("selecionado", selecionado);
      tile.tabIndex = selecionado ? 0 : -1;
      if (selecionado) {
        tile.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
      }
    });
    const jogo = JOGOS[indiceSelecionado];
    if (jogo) atualizarHero(jogo);
  }

  function atualizarHero(jogo) {
    heroTitulo.textContent = jogo.nome;
    heroDescricao.textContent = jogo.descricao;
    heroCapa.style.backgroundImage = "url('" + jogo.capa + "')";
    btnJogar.disabled = jogoEmExecucao;
    btnParar.disabled = !jogoEmExecucao;
  }

  function selecionar(indice) {
    if (indice < 0 || indice >= JOGOS.length) return;
    indiceSelecionado = indice;
    aplicarSelecao();
  }

  function proximo() {
    if (!JOGOS.length) return;
    selecionar((indiceSelecionado + 1) % JOGOS.length);
  }

  function anterior() {
    if (!JOGOS.length) return;
    selecionar((indiceSelecionado - 1 + JOGOS.length) % JOGOS.length);
  }

  // ---------- Navegação por teclado global ----------
  document.addEventListener("keydown", (ev) => {
    if (ev.target.tagName === "BUTTON" && ev.target.id === "btn-modo") return;
    if (ev.key === "ArrowRight") { ev.preventDefault(); proximo(); }
    if (ev.key === "ArrowLeft") { ev.preventDefault(); anterior(); }
  });

  // ---------- Ações ----------
  btnJogar.addEventListener("click", () => {
    const jogo = JOGOS[indiceSelecionado];
    if (!jogo) return;
    jogoEmExecucao = true;
    btnJogar.disabled = true;
    btnParar.disabled = false;
    heroDescricao.textContent = jogo.nome + " está em execução…";
    enviarComando("jogar", { jogo_id: jogo.id, nome: jogo.nome }).catch(() => {});
  });

  btnParar.addEventListener("click", () => {
    jogoEmExecucao = false;
    btnJogar.disabled = false;
    btnParar.disabled = true;
    const jogo = JOGOS[indiceSelecionado];
    if (jogo) heroDescricao.textContent = jogo.descricao;
    enviarComando("parar", { jogo_id: jogo ? jogo.id : "" }).catch(() => {});
  });

  // ---------- Relógio no header ----------
  function atualizarRelogio() {
    const agora = new Date();
    document.getElementById("relogio").textContent = agora.toLocaleTimeString("pt-BR", {
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  }
  setInterval(atualizarRelogio, 1000);
  atualizarRelogio();

  // ---------- Inicialização ----------
  sinalizarPronto();

  // Carrega a biblioteca real do Jolven via adaptador (#183).
  enviarComando("library.list", { offset: 0, limit: 500 })
    .then((snap) => {
      const itens = (snap && snap.items) || [];
      JOGOS.length = 0;
      for (const jogo of itens) {
        JOGOS.push({
          id: jogo.game_id,
          nome: jogo.name || "Sem nome",
          descricao: jogo.description || "Sem descrição.",
          plataforma: jogo.base_source || jogo.source || "desconhecida",
          base_source: jogo.base_source,
          capa: "https://placehold.co/400x600/1a1a22/e8e8f0?text=" + encodeURIComponent(jogo.name || jogo.game_id),
        });
      }
      indiceSelecionado = 0;
      renderCarrossel();
      avisarPonte(itens.length ? `${itens.length} jogo(s)` : "biblioteca vazia");
    })
    .catch((erro) => {
      console.error("Falha ao carregar a biblioteca do Console", erro);
      triagem.innerHTML = '<p class="vazio">Não foi possível carregar a biblioteca.</p>';
    });
})();