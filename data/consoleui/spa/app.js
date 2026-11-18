// app.js — Jolven Console SPA (mínima, offline)
// Referência visual: Aurora Launcher (GPL-3.0, codebyallan), adaptado ao Jolven.
// A ponte com o Python usa window.webkit.messageHandlers.jolven (WebKitGTK).

(function () {
  "use strict";

  // ---------- Canal bidirecional com o Python ----------
  function enviarComando(comando, parametros = {}) {
    const handler = window.webkit && window.webkit.messageHandlers
      ? window.webkit.messageHandlers.jolven
      : null;
    if (!handler) {
      avisarPonte("indisponível");
      return;
    }
    const msg = { comando, parametros, id: Math.random().toString(36).slice(2) };
    handler.postMessage(JSON.stringify(msg));
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

  // ---------- Dados de jogos (mock — substituído pelo adaptador #183) ----------
  const JOGOS = [
    { id: "1", nome: "Beneath a Steel Sky", descricao: "Aventura point-and-click cyberpunk.", plataforma: "linux", capa: "https://placehold.co/400x600/1a1a22/e8e8f0?text=Beneath+a+Steel+Sky" },
    { id: "2", nome: "Disco Elysium", descricao: "RPG de detetive com mundo aberto e habilidades.", plataforma: "linux", capa: "https://placehold.co/400x600/1a1a22/e8e8f0?text=Disco+Elysium" },
    { id: "3", nome: "Celeste", descricao: "Plataforma desafiadora sobre montanhas internas.", plataforma: "linux", capa: "https://placehold.co/400x600/1a1a22/e8e8f0?text=Celeste" },
    { id: "4", nome: "Hades", descricao: "Roguelike de ação no submundo grego.", plataforma: "linux", capa: "https://placehold.co/400x600/1a1a22/e8e8f0?text=Hades" },
    { id: "5", nome: "Stardew Valley", descricao: "Simulador de fazenda e vida no interior.", plataforma: "linux", capa: "https://placehold.co/400x600/1a1a22/e8e8f0?text=Stardew+Valley" },
  ];

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
    tile.setAttribute("aria-label", jogo.nome + ", " + jogo.plataforma);
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
    atualizarHero(jogo);
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
    selecionar((indiceSelecionado + 1) % JOGOS.length);
  }

  function anterior() {
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
    jogoEmExecucao = true;
    btnJogar.disabled = true;
    btnParar.disabled = false;
    heroDescricao.textContent = jogo.nome + " está em execução…";
    enviarComando("jogar", { jogo_id: jogo.id, nome: jogo.nome });
  });

  btnParar.addEventListener("click", () => {
    jogoEmExecucao = false;
    btnJogar.disabled = false;
    btnParar.disabled = true;
    const jogo = JOGOS[indiceSelecionado];
    heroDescricao.textContent = jogo.descricao;
    enviarComando("parar", { jogo_id: jogo.id });
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
  renderCarrossel();
  sinalizarPronto();
})();
