# xcloud_deps.py
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Dependências de sistema do player nativo do xCloud (GStreamer WebRTC/ICE).

Detecta a cadeia completa de WebRTC/SCTP, RTP, codecs e sinks e instala via o
helper privilegiado `jolven-xcloud-deps` (pkexec abre o diálogo de senha do
sistema). Sem GTK aqui: o chamador entrega o resultado à UI.
"""

from __future__ import annotations

import logging
import shlex
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from cartridges.platform import system_integration

logger = logging.getLogger(__name__)

REQUIRED_ELEMENTS = (
    "webrtcbin",
    "nicesrc",
    "nicesink",
    "sctpenc",
    "sctpdec",
    "rtph264depay",
    "h264parse",
    "rtpopusdepay",
    "opusdec",
    "videoconvert",
    "audioconvert",
    "appsink",
    "autoaudiosink",
)
H264_DECODERS = ("vah264dec", "nvh264dec", "avdec_h264", "openh264dec")
HELPER_OPERATION = "install-xcloud-deps"
XCLOUD_DEPS_ACTION_ID = system_integration.XCLOUD_DEPS_ACTION_ID


def build_restart_command(argv: List[str]) -> List[str]:
    """Relança o app após 2s via shell destacada (o processo atual sai antes).

    Puro e testável: recebe argv, devolve a lista para Popen.
    """
    relauncher = "sleep 2; exec " + " ".join(shlex.quote(arg) for arg in argv)
    return ["setsid", "nohup", "sh", "-c", relauncher]

try:
    import gi

    gi.require_version("Gst", "1.0")
    from gi.repository import Gst as _Gst
except (ImportError, ValueError):
    _Gst = None  # type: ignore[assignment]


def _helper_path() -> Optional[Path]:
    """Único caminho privilegiado aceitável: o helper da policy polkit.

    Fail-closed: devolve None quando a policy ou o binário executável
    estão ausentes. Nunca deriva caminho do prefixo de instalação, do
    repositório (``session/*.in``) ou do ``PATH``: executar helper em
    caminho controlado pelo usuário permitiria a qualquer processo do
    usuário obter root via pkexec/auth_admin_keep.
    """
    return system_integration.helper_for(XCLOUD_DEPS_ACTION_ID)


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


def missing_elements(elements: Tuple[str, ...] = REQUIRED_ELEMENTS) -> List[str]:
    """Elementos GStreamer ausentes. Lista vazia = tudo presente."""
    if _Gst is None:
        return list(elements)
    try:
        _Gst.init(None)
        registry = _Gst.Registry.get()
        missing = [
            name
            for name in elements
            if registry.find_feature(name, _Gst.ElementFactory) is None
        ]
        if elements == REQUIRED_ELEMENTS and not any(
            registry.find_feature(name, _Gst.ElementFactory) is not None
            for name in H264_DECODERS
        ):
            missing.append("h264-decoder")
        return missing
    except Exception as error:
        logger.debug("Falha sondando GStreamer: %s", error)
        return list(elements)


def policy_registered() -> bool:
    """True se a action polkit do helper existe no sistema."""
    return (
        system_integration.find_policy(XCLOUD_DEPS_ACTION_ID) is not None
    )


def install_async(
    callback: Callable[[bool, str], None],
    on_output: Optional[Callable[[str], None]] = None,
) -> bool:
    """Roda o helper via pkexec numa thread; callback(ok, mensagem) no fim.

    on_output(linha) recebe cada linha do helper (thread worker — o chamador
    entrega à UI). Retorna False se nem tentou (helper ausente) — nesse caso
    o callback não é chamado e o chamador deve orientar o setup manual.
    """
    helper = _helper_path()
    if helper is None:
        return False
    pkexec = shutil.which("pkexec")
    if pkexec is None:
        callback(False, _("pkexec indisponível neste sistema"))
        return True

    def work() -> None:
        proc = None
        try:
            proc = subprocess.Popen(
                [pkexec, str(helper), HELPER_OPERATION],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            lines: List[str] = []
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.strip()
                if not line:
                    continue
                lines.append(line)
                if on_output is not None:
                    try:
                        on_output(line)
                    except Exception:
                        pass
            code = proc.wait(timeout=600)
            message = lines[-1] if lines else ""
            if code == 0:
                callback(True, message or _("Dependências instaladas."))
            elif "dismissed" in message.lower() or "cancel" in message.lower():
                callback(False, _("Instalação cancelada."))
            else:
                callback(
                    False,
                    message or _("Falha na instalação (código %s).") % code,
                )
        except subprocess.TimeoutExpired:
            if proc is not None:
                try:
                    proc.kill()
                except Exception:
                    pass
            callback(False, _("Tempo esgotado instalando dependências."))
        except Exception as error:
            callback(False, _("Não foi possível instalar: %s") % error)

    threading.Thread(target=work, daemon=True, name="xcloud-deps").start()
    return True
