# game_session.py
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Instalação e remoção da Jolven Session (sessão do display manager).

A Jolven Session é o arquivo ``.desktop`` de sessão Wayland que o display
manager oferece na tela de login. Gravar (ou apagar) esse arquivo exige
root, então a operação passa pelo helper privilegiado
``jolven-game-mode-setup``, executado via ``pkexec`` (o polkit abre o
diálogo de senha do sistema).

Espelha ``cartridges/xcloud_deps.py``: o caminho do helper vem da policy
polkit (fail-closed — nunca do prefixo de instalação nem do ``PATH``), a
execução sai da thread principal e o resultado volta por callback. Sem
GTK aqui: o chamador entrega o resultado à UI.
"""

from __future__ import annotations

import builtins
import logging
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable, List, Optional, TextIO

from cartridges.platform import system_integration

logger = logging.getLogger(__name__)

# O launcher roda ``gettext.install`` antes de importar qualquer módulo do
# app; o fallback mantém este módulo importável em testes e ferramentas sem
# catálogo — o mesmo guarda de ``cartridges/integrations_page.py``.
if not hasattr(builtins, "_"):
    builtins._ = lambda text: text  # type: ignore[attr-defined]

#: Action polkit do helper da Jolven Session (fonte canônica do id).
GAME_MODE_ACTION_ID: str = system_integration.GAME_MODE_ACTION_ID

#: Operações aceitas pelo helper. Qualquer outra é recusada sem executar
#: nada: o helper privilegiado valida a mesma lista no seu lado.
HELPER_OPERATIONS: tuple[str, ...] = ("install", "uninstall")

#: Timeout do helper. No Fedora a instalação roda ``dnf install`` e pode
#: demorar minutos; 600 s dá folga sem travar a UI para sempre.
HELPER_TIMEOUT_SECONDS = 600


def _helper_path() -> Optional[Path]:
    """Único caminho privilegiado aceitável: o helper da policy polkit.

    Fail-closed: devolve None quando a policy ou o binário executável
    estão ausentes. Nunca deriva caminho do prefixo de instalação, do
    repositório (``session/*.in``) ou do ``PATH``: executar helper em
    caminho controlado pelo usuário permitiria a qualquer processo do
    usuário obter root via pkexec/auth_admin_keep.
    """
    return system_integration.helper_for(GAME_MODE_ACTION_ID)


def helper_available() -> bool:
    """True quando o helper autorizado está pronto para execução."""
    return _helper_path() is not None


def unavailable_reason() -> Optional[str]:
    """Motivo da indisponibilidade do instalador, para a UI exibir.

    None quando o helper autorizado está pronto. Delega o texto à fonte
    única (`system_integration.unavailable_message`); nunca orienta a
    rodar scripts com sudo — a apresentação final do texto é de outra
    camada.
    """
    if helper_available():
        return None
    return system_integration.unavailable_message()


def _session_file() -> Path:
    """Arquivo de sessão instalado no sistema.

    Fonte da verdade: ``shared.GAME_SESSION_FILE``. O import é tardio
    (``shared`` exige GTK e o schema compilado) para este módulo continuar
    importável sem ``gi`` — e o chamador trata a falha como "sessão
    ausente".
    """
    from cartridges import shared  # noqa: PLC0415

    return shared.GAME_SESSION_FILE


def session_installed() -> bool:
    """True quando o arquivo de sessão da Jolven Session existe no sistema.

    Qualquer falha (sem ``shared``, sem permissão, caminho ilegível)
    devolve False: a UI só habilita a ação de desinstalação quando a
    sessão está comprovadamente presente.
    """
    try:
        return _session_file().is_file()
    except Exception as error:  # pylint: disable=broad-exception-caught
        logger.debug("Falha verificando a Jolven Session: %s", error)
        return False


def _success_message(operation: str) -> str:
    """Texto de sucesso da operação, pronto para a UI."""
    if operation == "install":
        return _("Jolven Session installed. It will appear at the next login.")
    return _("Jolven Session uninstalled")


def setup_async(
    operation: str,
    callback: Callable[[bool, str], None],
    on_output: Optional[Callable[[str], None]] = None,
) -> bool:
    """Roda o helper via pkexec numa thread; callback(ok, mensagem) no fim.

    ``on_output(linha)`` recebe cada linha do helper (thread worker — o
    chamador entrega à UI). O ``callback`` também roda na thread worker:
    quem chama entrega o resultado à thread principal.

    Devolve False quando a operação não foi iniciada — helper ausente,
    operação fora de `HELPER_OPERATIONS` ou ``pkexec`` indisponível. Nesse
    caso o callback **não** é chamado e o chamador decide a mensagem
    (`unavailable_reason()` cobre o caso de helper ausente).
    """
    if operation not in HELPER_OPERATIONS:
        logger.error("Operação inválida para o helper da Jolven Session: %s", operation)
        return False
    helper = _helper_path()
    if helper is None:
        return False
    pkexec = shutil.which("pkexec")
    if pkexec is None:
        logger.error("pkexec indisponível neste sistema")
        return False

    def work() -> None:
        proc = None
        try:
            proc = subprocess.Popen(
                [pkexec, str(helper), operation],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            stdout = proc.stdout
            assert stdout is not None
            lines: List[str] = []

            def read_output(stream: TextIO) -> None:
                for raw in stream:
                    line = raw.strip()
                    if not line:
                        continue
                    lines.append(line)
                    if on_output is not None:
                        try:
                            on_output(line)
                        except Exception:  # pylint: disable=broad-exception-caught
                            pass

            # A leitura do stdout fica numa thread própria: o `wait` abaixo
            # é quem mede o timeout, e o pipe precisa ser drenado enquanto o
            # helper roda (senão ele trava escrevendo).
            reader = threading.Thread(
                target=read_output,
                args=(stdout,),
                daemon=True,
                name="game-session-output",
            )
            reader.start()
            try:
                code = proc.wait(timeout=HELPER_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:  # pylint: disable=broad-exception-caught
                    pass
                callback(False, _("Tempo esgotado na Jolven Session."))
                return
            reader.join(timeout=5)
            message = lines[-1] if lines else ""
            if code == 0:
                callback(True, _success_message(operation))
            elif "dismissed" in message.lower() or "cancel" in message.lower():
                callback(False, _("Operação cancelada."))
            else:
                callback(
                    False,
                    message or _("Falha na Jolven Session (código %s).") % code,
                )
        except Exception as error:  # pylint: disable=broad-exception-caught
            callback(False, _("Não foi possível concluir a Jolven Session: %s") % error)

    threading.Thread(target=work, daemon=True, name="game-session").start()
    return True
