# console_shell.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Janela do Jolven Console: frontend WebKitGTK com ponte tipada para o Python.

Este módulo é o shell nativo GTK4/libadwaita do Jolven Console (issue #180 do
épico #176). Hospeda a SPA do Console em um ``WebKit.WebView`` GTK4 e expõe
uma ponte mínima e tipada WebView <-> Python:

* comandos autorizados, vindos do renderer, executados no Python;
* eventos serializados, vindos do Python para o renderer;
* o renderer nunca acessa filesystem, shell, segredos nem comandos arbitrários.

A WebKitGTK só é importada sob demanda: se não estiver instalada, o módulo
segue importável e :func:`criar_janela_console` devolve ``None``, cabendo ao
chamador (``cartridges/main.py``) cair de volta ao Jolven Flat.

Este arquivo é um esqueleto da etapa F1: a SPA real e o conjunto completo de
comandos vêm nas etapas #181 a #198. Até lá, a janela carrega uma página mínima
que demonstra a ponte (``ping`` / ``echo``).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from gi.repository import Adw, GObject, Gtk, Gio

logger = logging.getLogger(__name__)

_WebKit: Any = None
_webkit_checked = False


def _carregar_webkit() -> bool:
    """Importa WebKitGTK 6.0 apenas quando necessário."""

    global _WebKit, _webkit_checked
    if _webkit_checked:
        return _WebKit is not None
    _webkit_checked = True
    try:
        from gi.repository import WebKit as _wk  # type: ignore[import-not-found]

        _WebKit = _wk
        return True
    except (ValueError, ImportError) as error:
        logger.debug("WebKitGTK nao disponivel para o Console: %s", error)
        return False


def webkit_disponivel() -> bool:
    """True se o WebKitGTK 6 puder ser carregado."""

    if not _carregar_webkit():
        return False
    return _WebKit is not None


# Minha SPA de demonstração embutida. Substituída pela SPA extraída do Aurora
# na etapa #181 (Extrair frontend Vue e gerar SPA estática offline).
_SPA_HTML = """\
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Jolven Console</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, sans-serif; background: #1e1e2e; color: #cdd6f4;
         height: 100vh; display: flex; flex-direction: column; }
  header { padding: 1rem 1.5rem; border-bottom: 1px solid #45475a;
           display: flex; justify-content: space-between; align-items: center; }
  h1 { font-size: 1.25rem; font-weight: 700; letter-spacing: 0.05em; }
  main { flex: 1; padding: 2rem; display: grid; gap: 1rem; }
  .card { background: #313244; border: 1px solid #45475a; border-radius: 12px;
          padding: 1.5rem; }
  button { background: #89b4fa; color: #11111b; border: none; border-radius: 8px;
           padding: 0.75rem 1.5rem; font-weight: 700; cursor: pointer; }
  button:hover { background: #b4befe; }
  #saida { margin-top: 1rem; font-family: ui-monospace, monospace; font-size: 0.9rem;
           color: #a6e3a1; white-space: pre-wrap; }
</style>
</head>
<body>
<header><h1>Jolven Console</h1><div id="status">ponte: aguardando</div></header>
<main>
  <section class="card">
    <h2>Ponte WebKit <-> Python</h2>
    <p>Escolha uma acao para validar o canal bidirecional.</p>
    <button id="ping">Ping</button>
    <button id="echo">Echo</button>
    <div id="saida"></div>
  </section>
</main>
<script>
// Canal de comandos: chama o Python via window.webkit.messageHandlers.jolven.
function canal(comando, parametros = {}) {
  return new Promise((resolve, rejeitar) => {
    const msg = { comando, parametros, id: Math.random().toString(36).slice(2) };
    const handler = window.webkit?.messageHandlers?.jolven;
    if (!handler) { rejeitar(new Error("ponte nao disponível")); return; }
    window.__jolven_cb = window.__jolven_cb || {};
    window.__jolven_cb[msg.id] = { resolve, rejeitar };
    handler.postMessage(JSON.stringify(msg));
  });
}
async function acao(id, label) {
  const saida = document.getElementById("saida");
  try {
    const resposta = await canal(id, { origem: "console-demo" });
    saida.textContent = label + " => " + JSON.stringify(resposta);
  } catch (erro) {
    saida.textContent = "erro: " + erro.message;
  }
}
document.getElementById("ping").onclick = () => acao("ping", "ping");
document.getElementById("echo").onclick = () => acao("echo", { texto: "ola do console" });
window.dispatchEvent(new Event("jolven-pronto"));
</script>
</body>
</html>
"""


class ConsoleShell(Adw.ApplicationWindow):
    """Janela do Jolven Console.

    Para criar, use :func:`criar_janela_console`, que devolve ``None`` quando
    o WebKitGTK nao esta disponivel.
    """

    __gsignals__ = {
        "comando-recebido": (
            GObject.SignalFlags.RUN_FIRST,
            None,
            (str, object),
        ),
    }

    def __init__(self, application: Adw.Application, **kwargs: Any) -> None:
        super().__init__(application=application, **kwargs)
        self.set_title("Jolven Console")
        self.set_default_size(1280, 800)
        self.set_size_request(900, 600)

        self._handlers: dict[str, Callable[[dict], Any]] = {}
        self._pendentes: dict[str, tuple[Callable, Callable]] = {}
        self._contador = 0

        if not webkit_disponivel():
            self._sem_webkit()
            return

        assert _WebKit is not None
        view = _WebKit.WebView()
        view.load_html(_SPA_HTML, "file:///")

        # Registro do handler de mensagens do renderer para o Python.
        manager = view.get_user_content_manager()
        manager.register_script_message_handler("jolven")

        self._view = view
        self.set_content(view)
        self.show()

        view.connect("load-changed", self._on_load_changed)
        manager.connect("script-message-received::jolven", self._on_mensagem)

    def set_gamepad_devices(self, devices: list) -> None:
        """Aceita a lista de gamepads (sem uso direto no esqueleto do Console)."""

        self._gamepad_devices = list(devices or [])
        manager.connect("script-message-received::jolven", self._on_mensagem)

    def _sem_webkit(self) -> None:
        label = Gtk.Label(
            label="Jolven Console nao disponível: o WebKitGTK 6 não está instalado."
        )
        label.set_hexpand(True)
        label.set_vexpand(True)
        label.set_halign(Gtk.Align.CENTER)
        label.set_valign(Gtk.Align.CENTER)
        self.set_content(label)
        self.show()
        logger.warning("Console sem WebKitGTK; exibindo aviso em vez da SPA")

    def _on_load_changed(self, view: Any, event: Any) -> None:
        if event == _WebKit.LoadEvent.FINISHED:
            logger.debug("Console SPA carregada")

    def _on_mensagem(self, manager: Any, result: Any) -> None:
        js_value = result.get_js_value()
        try:
            texto = js_value.to_string() if hasattr(js_value, "to_string") else str(js_value)
        except Exception:
            texto = str(js_value)
        try:
            mensagem = json.loads(texto)
        except json.JSONDecodeError:
            logger.warning("Mensagem do Console nao e JSON: %r", texto[:200])
            return
        comando = mensagem.get("comando")
        parametros = mensagem.get("parametros", {}) or {}
        msg_id = mensagem.get("id")
        logger.debug("Comando do Console: %s", comando)
        self.emit("comando-recebido", comando, parametros)
        handler = self._handlers.get(comando)
        if handler is None:
            self._responder(msg_id, None, erro="comando nao autorizado")
            return
        try:
            resposta = handler(parametros)
            if hasattr(resposta, "__await__"):
                # Handlers assíncronos não são esperados neste esqueleto.
                resposta = None
            self._responder(msg_id, resposta)
        except Exception as error:  # pylint: disable=broad-exception-caught
            logger.exception("Falha ao executar comando %s do Console", comando)
            self._responder(msg_id, None, erro=str(error))

    def _responder(self, msg_id: Any, resultado: Any, erro: str | None = None) -> None:
        """Ainda sem callback JS completo: registre o resultado no log.

        O tratamento completo de promessas JS (resolver/rejeitar callbacks do
        renderer) fica para a etapa #182 (ponte tipada e assíncrona).
        """

        logger.debug(
            "Console resposta ao comando (sem callback JS ainda): id=%s erro=%s",
            msg_id,
            erro,
        )

    def registrar_comando(self, nome: str, handler: Callable[[dict], Any]) -> None:
        """Registra um comando autorizado que o renderer pode invocar."""

        self._handlers[nome] = handler

    def enviar_evento(self, nome: str, payload: Any = None) -> None:
        """Envia um evento serializado do Python para o renderer."""

        script = (
            "window.dispatchEvent(new CustomEvent("
            + json.dumps(nome)
            + ", {detail: "
            + json.dumps(payload)
            + "});"
        )
        if hasattr(self._view, "run_javascript"):
            self._view.run_javascript(script)


def criar_janela_console(application: Adw.Application) -> ConsoleShell | None:
    """Cria a janela do Jolven Console.

    Devolve ``None`` quando o WebKitGTK 6 nao esta disponível, para que o
    chamador caia de volta ao Jolven Flat.
    """

    if not webkit_disponivel():
        return None
    try:
        return ConsoleShell(application)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("Não foi possível criar a janela do Console")
        return None
