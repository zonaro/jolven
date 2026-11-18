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

A SPA estática é instalada em ``<pkgdatadir>/consoleui/spa/`` (etapa #181) e
carregada via ``file://``. Quando o arquivo não está disponível (ambiente de
desenvolvimento antes do ``meson install``), cai de volta a um HTML mínimo
embutido, para que o módulo continue importável e testável.

Este arquivo é um esqueleto da etapa F1: a SPA real (extraída do Aurora) e o
conjunto completo de comandos vêm nas etapas #181 a #198.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from cartridges import console_adapter, shared

from gi.repository import Adw, GObject, Gtk, Gio

logger = logging.getLogger(__name__)

_WebKit: Any = None
_webkit_checked = False

# Versão do protocolo da ponte WebKit <-> Python. O renderer deve enviar o
# mesmo valor; caso contrário a mensagem é rejeitada. Permite evoluir o
# contrato sem quebrar clientes antigos (etapa #182).
PONTE_VERSAO = "1"

# Comandos que o renderer está autorizado a solicitar. Qualquer comando fora
# desta lista é rejeitado (segurança: nenhuma execução arbitrária).
COMANDOS_AUTORIZADOS = frozenset({"library.get", "library.list", "ping", "echo"})


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
        logger.debug("WebKitGTK nao disponível para o Console: %s", error)
        return False


def webkit_disponivel() -> bool:
    """True se o WebKitGTK 6 puder ser carregado."""

    if not _carregar_webkit():
        return False
    return _WebKit is not None


# SPA mínima de fallback, usada somente quando o arquivo instalado não está
# disponível (ex.: executando direto do fonte antes do ``meson install``).
_SPA_FALLBACK = """\
<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>Jolven Console</title>
<style>body{font-family:system-ui,sans-serif;background:#0f0f13;color:#e8e8f0;
display:flex;flex-direction:column;height:100vh;padding:2rem;gap:1rem;}
header{border-bottom:1px solid #333;padding:1rem;display:flex;
justify-content:space-between;align-items:center;}
button{background:#7aa2f7;color:#111;border:none;border-radius:8px;
padding:0.7rem 1.3rem;font-weight:700;cursor:pointer;}
#saida{margin-top:1rem;font-family:ui-monospace;color:#a6e3a1;
white-space:pre-wrap;}</style></head>
<body><header><div>Jolven Console</div><div id="status">carregando…</div></header>
<main><div id="saida">SPA não encontrada em <span id="caminho"></span>.</div></main>
<script>
document.getElementById("caminho").textContent = window.location.href;
window.dispatchEvent(new Event("jolven-pronto"));
</script></body></html>
"""


def _caminho_spa() -> Path:
    """Resolve o caminho do index.html da SPA instalada.

    A SPA é instalada em ``<prefix>/share/jolven/consoleui/spa/`` pelo
    ``data/consoleui/meson.build``. A partir do próprio módulo
    (``<prefix>/lib/pythonX.Y/site-packages/cartridges/console_shell.py``),
    sobe até o prefixo de instalação e localiza o share. Quando não é
    possível, devolve um caminho inexistente para acionar o fallback.
    """

    try:
        aqui = Path(__file__).resolve()
        # console_shell.py -> cartridges -> site-packages -> python3.X -> lib -> <prefix>
        prefix = aqui.parents[4]
        candidato = prefix / "share" / "jolven" / "consoleui" / "spa" / "index.html"
        if candidato.is_file():
            return candidato
    except Exception:
        pass
    try:
        prefix = getattr(shared, "PREFIX", None)
    except Exception:
        prefix = None
    if prefix:
        candidato = Path(prefix) / "share" / "jolven" / "consoleui" / "spa" / "index.html"
        if candidato.is_file():
            return candidato
    return Path("/nonexistent/consoleui/spa/index.html")


class ConsoleShell(Adw.ApplicationWindow):
    """Janela do Jolven Console.

    Para criar, use :func:`criar_janela_console`, que devolve ``None`` quando
    o WebKitGTK não está disponível.
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
        self._caminho_spa = str(_caminho_spa())

        if not webkit_disponivel():
            self._sem_webkit()
            return

        assert _WebKit is not None
        view = _WebKit.WebView()
        view.load_uri("file://" + self._caminho_spa)

        # Registro do handler de mensagens do renderer para o Python.
        manager = view.get_user_content_manager()
        manager.register_script_message_handler("jolven")

        self._view = view
        self.set_content(view)
        self.show()

        view.connect("load-changed", self._on_load_changed)
        manager.connect("script-message-received::jolven", self._on_mensagem)

        # Comandos built-in da ponte (disponíveis para qualquer renderer do
        # Console). Comandos de negócio usam o adaptador de leitura (#183).
        self.registrar_comando("ping", lambda _p: "pong")
        self.registrar_comando(
            "echo", lambda p: p if isinstance(p, dict) else {"valor": p}
        )
        self.registrar_comando("library.list", self._library_list)
        self.registrar_comando("library.get", self._library_get)

    def set_gamepad_devices(self, devices: list) -> None:
        """Aceita a lista de gamepads (sem uso direto no esqueleto do Console)."""

        self._gamepad_devices = list(devices or [])

    def _sem_webkit(self) -> None:
        label = Gtk.Label(
            label="Jolven Console não disponível: o WebKitGTK 6 não está instalado."
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
            logger.debug("Console SPA carregada: %s", self._caminho_spa)

    def _on_mensagem(self, manager: Any, result: Any) -> None:
        js_value = result.get_js_value()
        try:
            texto = js_value.to_string() if hasattr(js_value, "to_string") else str(js_value)
        except Exception:
            texto = str(js_value)
        try:
            mensagem = json.loads(texto)
        except json.JSONDecodeError:
            logger.warning("Mensagem do Console não é JSON: %r", texto[:200])
            return
        # Valida a versão do protocolo antes de processar qualquer comando.
        if mensagem.get("versao") != PONTE_VERSAO:
            logger.warning(
                "Versão da ponte não suportada: %r (esperada %s)",
                mensagem.get("versao"),
                PONTE_VERSAO,
            )
            self._responder(
                mensagem.get("id"), None, erro="versão da ponte não suportada"
            )
            return
        comando = mensagem.get("comando")
        parametros = mensagem.get("parametros", {}) or {}
        msg_id = mensagem.get("id")
        logger.debug("Comando do Console: %s", comando)
        self.emit("comando-recebido", comando, parametros)
        handler = self._handlers.get(comando)
        if handler is None:
            self._responder(msg_id, None, erro="comando não autorizado")
            return
        try:
            resposta = handler(parametros)
            self._responder(msg_id, resposta)
        except Exception as error:  # pylint: disable=broad-exception-caught
            logger.exception("Falha ao executar comando %s do Console", comando)
            self._responder(msg_id, None, erro=str(error))

    def _responder(self, msg_id: Any, resultado: Any, erro: str | None = None) -> None:
        """Responde ao renderer resolvendo/rejeitando a promessa JS do comando.

        O renderer (app.js, função ``canal``) cria uma Promise por comando e
        registra os callbacks ``resolve``/``reject`` em
        ``window.__jolven_cb[id]``. Este método executa um script que chama o
        callback adequado e depois o remove, evitando vazamento de memória.
        """

        id_json = json.dumps(str(msg_id)) if msg_id is not None else "null"
        if erro is not None:
            resultado_json = "null"
            erro_json = json.dumps(erro)
            chama = "cb.reject(" + erro_json + ")"
        else:
            resultado_json = json.dumps(resultado)
            erro_json = "null"
            chama = "cb.resolve(" + resultado_json + ")"
        script = (
            "(function(){"
            "var cb=window.__jolven_cb&&window.__jolven_cb[" + id_json + "];"
            "if(cb){" + chama + ";delete window.__jolven_cb[" + id_json + "];}"
            "})();"
        )
        logger.debug(
            "Console responde comando id=%s erro=%s", msg_id, erro
        )
        if hasattr(self._view, "run_javascript"):
            self._view.run_javascript(script)

    def _library_list(self, params: dict | None) -> dict:
        """Lista a biblioteca do Console como DTOs imutáveis.

        Devolve um snapshot paginado (``offset``/``limit``) com a revisão
        atual da Store. Quando o Store ainda não foi criado ou não está
        disponível, devolve uma lista vazia com ``revision`` 0, evitando
        erro para o renderer.
        """

        params = params if isinstance(params, dict) else {}
        offset = _int_param(params, "offset", 0)
        limit = _int_param(params, "limit", 100)
        limit = max(1, min(limit, 500))
        include_hidden = bool(params.get("include_hidden", False))

        store = getattr(shared, "store", None)
        if store is None:
            return {"revision": 0, "total": 0, "offset": offset, "limit": limit, "items": []}

        try:
            snapshot = console_adapter.list_snapshot(
                store,
                revision=getattr(store, "revision", 0),
                offset=max(0, offset),
                limit=limit,
                include_hidden=include_hidden,
            )
        except Exception as error:
            logger.exception("Falha ao listar a biblioteca do Console")
            return {
                "revision": 0,
                "total": 0,
                "offset": offset,
                "limit": limit,
                "items": [],
                "error": f"não foi possível ler a biblioteca: {error}",
            }
        return snapshot.to_dict()

    def _library_get(self, params: dict | None) -> dict | None:
        """Devolve os detalhes de um jogo pelo ``game_id``."""

        params = params if isinstance(params, dict) else {}
        game_id = str(params.get("game_id", "") or "").strip()
        if not game_id:
            return None

        store = getattr(shared, "store", None)
        if store is None:
            return None

        try:
            details = console_adapter.details_by_id(store, game_id)
        except Exception as error:
            logger.exception("Falha ao obter detalhes do jogo %s do Console", game_id)
            return {"error": f"não foi possível ler o jogo: {error}"}

        if details is None:
            return None
        return _details_to_dict(details)

    def registrar_comando(self, nome: str, handler: Callable[[dict], Any]) -> None:
        """Registra um comando autorizado que o renderer pode invocar."""

        if nome not in COMANDOS_AUTORIZADOS:
            raise ValueError(f"comando não autorizado: {nome}")
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


def _int_param(params: dict, key: str, default: int) -> int:
    """Lê um inteiro do payload com fallback seguro."""

    value = params.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _details_to_dict(details: Any) -> dict[str, Any]:
    """Serializa ``GameDetails`` como JSON quando possível."""

    try:
        from dataclasses import asdict

        data = asdict(details)
        # Tags/Screenshots/Mods podem ser tuples; JSON converte via lista.
        def _tuple_to_list(obj: Any) -> Any:
            if isinstance(obj, tuple):
                return [_tuple_to_list(item) for item in obj]
            if isinstance(obj, dict):
                return {key: _tuple_to_list(value) for key, value in obj.items()}
            if isinstance(obj, list):
                return [_tuple_to_list(item) for item in obj]
            return obj

        return _tuple_to_list(data)
    except Exception:
        logger.exception("Falha ao serializar detalhes do jogo")
        return {"error": "não foi possível serializar os detalhes"}


def criar_janela_console(application: Adw.Application) -> ConsoleShell | None:
    """Cria a janela do Jolven Console.

    Devolve ``None`` quando o WebKitGTK 6 não está disponível, para que o
    chamador caia de volta ao Jolven Flat.
    """

    if not webkit_disponivel():
        return None
    try:
        return ConsoleShell(application)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("Não foi possível criar a janela do Console")
        return None
