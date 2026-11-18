// app.js — Jolven Console SPA (mínima, offline)
// Referência visual: Aurora Launcher (GPL-3.0, codebyallan), adaptado ao Jolven.
// A ponte com o Python usa window.webkit.messageHandlers.jolven (WebKitGTK).
// Artes: esquema interno jolven-art:// (issue #184) — nunca URLs remotas.

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

  // ---------- Artes (jolven-art://) ----------
  function arteUrl(kind, id, tag) {
    return (
      "jolven-art://" + kind + "/" +
      encodeURIComponent(String(id || "")) +
      "?v=" + encodeURIComponent(String(tag || "0"))
    );
  }

  function cssUrl(url) {
    return "url('" + String(url).replace(/'/g, "%27") + "')";
  }

  // Só o item ativo e os vizinhos próximos ganham URL de imagem.
  const PRELOAD_RAIO = 2;

  // ---------- Dados de jogos (adaptadores #183/#184) ----------
  const JOGOS = [];
  let indiceSelecionado = 0;
  let jogoEmExecucao = false;
  let carregando = false;

  // ---------- Render ----------
  const triagem = document.getElementById("triagem");
  const heroTitulo = document.getElementById("hero-titulo");
  const heroDescricao = document.getElementById("hero-descricao");
  const heroCapa = document.getElementById("hero-capa");
  const heroLogo = document.getElementById("hero-logo");
  const fundo = document.getElementById("fundo");
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
    img.alt = jogo.nome;
    img.dataset.indice = String(indice);
    img.dataset.src = arteUrl("cover", jogo.id, jogo.art_tag);
    img.addEventListener("load", () => img.classList.add("carregada"));
    img.addEventListener("error", () => {
      if (img.dataset.fallback) return;
      img.dataset.fallback = "1";
      img.classList.remove("carregada");
      img.src = arteUrl("placeholder", "cover", "0");
    });

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
    atualizarPreload();
    const jogo = JOGOS[indiceSelecionado];
    if (jogo) atualizarHero(jogo);
  }

  function atualizarPreload() {
    const imgs = triagem.querySelectorAll(".tile img");
    imgs.forEach((img) => {
      const indice = Number(img.dataset.indice);
      const perto = Math.abs(indice - indiceSelecionado) <= PRELOAD_RAIO;
      if (perto && !img.getAttribute("src")) {
        img.src = img.dataset.src;
      } else if (!perto && img.hasAttribute("src") && !img.classList.contains("carregada")) {
        img.removeAttribute("src");
      }
    });
  }

  function atualizarHero(jogo) {
    heroTitulo.textContent = jogo.nome;
    heroDescricao.textContent = jogo.descricao;

    const tag = jogo.art_tag || "0";
    const heroUrl = arteUrl("hero", jogo.id, tag);
    heroCapa.style.backgroundImage =
      "linear-gradient(to right, #0f0f13, transparent 60%), " +
      cssUrl(heroUrl) + " center/cover no-repeat";
    if (fundo) {
      fundo.style.backgroundImage =
        "linear-gradient(rgba(15,15,19,0.55), rgba(15,15,19,0.78)), " +
        cssUrl(heroUrl) + " center/cover no-repeat";
    }
    if (heroLogo) {
      heroLogo.hidden = true;
      heroLogo.onload = () => { heroLogo.hidden = heroLogo.naturalWidth <= 4; };
      heroLogo.onerror = () => { heroLogo.hidden = true; };
      heroLogo.src = arteUrl("logo", jogo.id, tag);
    }

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

  // Carrega a biblioteca real do Jolven via adaptador (#183). Recarregada ao
  // voltar o foco (#184) para refletir mudanças de capa feitas na Flat.
  function carregarBiblioteca(manterSelecao) {
    if (carregando) return;
    carregando = true;
    const selecionadoId = manterSelecao && JOGOS[indiceSelecionado]
      ? JOGOS[indiceSelecionado].id
      : null;

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
            art_tag: jogo.art_tag || "0",
          });
        }
        if (selecionadoId) {
          const novo = JOGOS.findIndex((j) => j.id === selecionadoId);
          indiceSelecionado = novo >= 0 ? novo : 0;
        } else {
          indiceSelecionado = 0;
        }
        renderCarrossel();
        avisarPonte(itens.length ? `${itens.length} jogo(s)` : "biblioteca vazia");
      })
      .catch((erro) => {
        console.error("Falha ao carregar a biblioteca do Console", erro);
        if (!JOGOS.length) {
          triagem.innerHTML = '<p class="vazio">Não foi possível carregar a biblioteca.</p>';
        }
      })
      .finally(() => { carregando = false; });
  }

  let focoTimer = null;
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    clearTimeout(focoTimer);
    focoTimer = setTimeout(() => carregarBiblioteca(true), 300);
  });

  carregarBiblioteca(false);
})();
