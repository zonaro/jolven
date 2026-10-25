# SPDX-License-Identifier: GPL-3.0-or-later
"""Detecção de navegadores e abertura de uma janela em modo quiosque.

O Xbox Cloud Gaming do Jolven não embute mais WebView nem player nativo: cada
título abre no navegador escolhido pelo usuário, numa janela nova em tela
cheia. Este módulo cuida das duas partes sem GTK:

- descobrir os navegadores instalados (entradas desktop que registram
  ``https`` e binários conhecidos no ``PATH``);
- montar e executar o comando de quiosque adequado à família do navegador.

O perfil dedicado por navegador é intencional: quando o navegador do usuário
já está aberto, a instância existente ignora ``--kiosk`` e abre só mais uma
aba. Um diretório de dados próprio força uma instância nova de verdade e, de
quebra, preserva o login do xbox.com entre as sessões.

Nada aqui toca a thread GTK: ``launch_kiosk`` apenas dispara um processo
destacado e devolve ``(ok, mensagem)``.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence

logger = logging.getLogger(__name__)

KIND_CHROMIUM = "chromium"
KIND_FIREFOX = "firefox"
KIND_OTHER = "other"
KIOSK_KINDS = frozenset({KIND_CHROMIUM, KIND_FIREFOX})

CHROMIUM_BINARIES = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "brave-browser",
    "brave",
    "microsoft-edge",
    "microsoft-edge-stable",
    "vivaldi",
    "vivaldi-stable",
    "opera",
    "thorium-browser",
    "ungoogled-chromium",
)
FIREFOX_BINARIES = (
    "firefox",
    "firefox-esr",
    "librewolf",
    "waterfox",
    "floorp",
    "firefox-developer-edition",
)
OTHER_BINARIES = ("epiphany", "falkon", "qutebrowser", "nyxt", "surf", "netsurf")

_BINARY_NAMES = {
    "chromium": "Chromium",
    "chromium-browser": "Chromium",
    "google-chrome": "Google Chrome",
    "google-chrome-stable": "Google Chrome",
    "brave-browser": "Brave",
    "brave": "Brave",
    "microsoft-edge": "Microsoft Edge",
    "microsoft-edge-stable": "Microsoft Edge",
    "vivaldi": "Vivaldi",
    "vivaldi-stable": "Vivaldi",
    "opera": "Opera",
    "thorium-browser": "Thorium",
    "ungoogled-chromium": "ungoogled-chromium",
    "firefox": "Firefox",
    "firefox-esr": "Firefox ESR",
    "librewolf": "LibreWolf",
    "waterfox": "Waterfox",
    "floorp": "Floorp",
    "firefox-developer-edition": "Firefox Developer Edition",
    "epiphany": "Web",
    "falkon": "Falkon",
    "qutebrowser": "qutebrowser",
    "nyxt": "Nyxt",
    "surf": "surf",
    "netsurf": "NetSurf",
}

_CHROMIUM_MARKERS = (
    "chromium",
    "chrome",
    "brave",
    "vivaldi",
    "microsoft-edge",
    "msedge",
    "opera",
    "thorium",
    "ungoogled",
)
_FIREFOX_MARKERS = ("firefox", "librewolf", "waterfox", "floorp", "icecat")
_OTHER_MARKERS = (
    "epiphany",
    "falkon",
    "qutebrowser",
    "nyxt",
    "surf",
    "netsurf",
    "webkit",
)

# Entradas que registram https mas não são navegadores de verdade.
_NON_BROWSER_EXECUTABLES = frozenset(
    {
        "xdg-open",
        "gio",
        "kioclient",
        "kioclient5",
        "sensible-browser",
        "x-www-browser",
        "wslview",
        "open",
        "dms",
        "chatgpt",
        "code",
    }
)
_BROWSER_HINTS = ("browser", "navegador", "navegador web", "webbrowser")

_PROFILE_PREFERENCE = """\
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.aboutwelcome.enabled", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
"""


@dataclass(frozen=True)
class Browser:
    """Navegador detectado, com o prefixo de comando já resolvido."""

    id: str
    name: str
    kind: str
    command: tuple[str, ...]
    kiosk: bool


def _normalize(value: str) -> str:
    return (value or "").casefold()


def classify_browser(text: str) -> str:
    """Classifica um navegador em ``chromium``, ``firefox`` ou ``other``.

    Recebe livremente id, nome, executável ou linha de comando; a primeira
    família que casar vence.
    """
    normalized = _normalize(text)
    if any(marker in normalized for marker in _CHROMIUM_MARKERS):
        return KIND_CHROMIUM
    if any(marker in normalized for marker in _FIREFOX_MARKERS):
        return KIND_FIREFOX
    if any(marker in normalized for marker in _OTHER_MARKERS):
        return KIND_OTHER
    return KIND_OTHER


def _looks_like_browser(text: str) -> bool:
    normalized = _normalize(text)
    if any(
        marker in normalized
        for marker in (
            *_CHROMIUM_MARKERS,
            *_FIREFOX_MARKERS,
            *_OTHER_MARKERS,
            *_BROWSER_HINTS,
        )
    ):
        return True
    return False


def _strip_desktop_suffix(desktop_id: str) -> str:
    return (desktop_id or "").removesuffix(".desktop")


def _app_infos_from_gio() -> list[Any]:
    """Entradas desktop registradas para http/https, sem exigir GTK."""
    try:
        import gi  # noqa: PLC0415

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio  # noqa: PLC0415
    except (ImportError, ValueError) as error:
        logger.debug("Gio indisponível para detectar navegadores: %s", error)
        return []

    infos: list[Any] = []
    seen: set[str] = set()
    for content_type in ("x-scheme-handler/https", "x-scheme-handler/http"):
        try:
            candidates = Gio.AppInfo.get_all_for_type(content_type)
        except Exception as error:  # pylint: disable=broad-exception-caught
            logger.debug("Falha listando handlers de %s: %s", content_type, error)
            continue
        for info in candidates:
            try:
                key = info.get_id() or info.get_executable() or id(info)
            except Exception:  # pylint: disable=broad-exception-caught
                continue
            if key in seen:
                continue
            seen.add(key)
            infos.append(info)
    return infos


def _default_app_id_from_gio() -> str:
    try:
        import gi  # noqa: PLC0415

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio  # noqa: PLC0415

        info = Gio.AppInfo.get_default_for_type("x-scheme-handler/https", False)
    except Exception as error:  # pylint: disable=broad-exception-caught
        logger.debug("Não foi possível ler o navegador padrão: %s", error)
        return ""
    if info is None:
        return ""
    try:
        return _strip_desktop_suffix(info.get_id() or "")
    except Exception:  # pylint: disable=broad-exception-caught
        return ""


def _resolve_executable(executable: str, which: Callable[[str], Optional[str]]) -> str:
    if not executable:
        return ""
    if os.path.isabs(executable):
        return executable
    return which(executable) or ""


def _command_for(
    app_id: str,
    executable: str,
    which: Callable[[str], Optional[str]],
) -> tuple[str, ...]:
    basename = Path(executable).name
    if basename == "flatpak":
        # ``flatpak run`` aceita o id do app e depois os argumentos dele.
        return ("flatpak", "run", app_id) if app_id else ()
    resolved = _resolve_executable(executable, which)
    return (resolved,) if resolved else ()


def _browser_from_app_info(
    info: Any, which: Callable[[str], Optional[str]]
) -> Optional[Browser]:
    try:
        app_id = _strip_desktop_suffix(info.get_id() or "")
        name = (info.get_display_name() or app_id or "").strip()
        executable = info.get_executable() or ""
        commandline = info.get_commandline() or ""
    except Exception as error:  # pylint: disable=broad-exception-caught
        logger.debug("Entrada de navegador inválida ignorada: %s", error)
        return None

    if not name or not executable:
        return None
    if Path(executable).name in _NON_BROWSER_EXECUTABLES:
        return None
    if not _looks_like_browser(" ".join((app_id, name, executable, commandline))):
        return None

    command = _command_for(app_id, executable, which)
    if not command:
        return None
    kind = classify_browser(" ".join((app_id, name, executable, commandline)))
    return Browser(
        id=app_id or Path(executable).name,
        name=name,
        kind=kind,
        command=command,
        kiosk=kind in KIOSK_KINDS,
    )


def _browsers_from_path(
    which: Callable[[str], Optional[str]],
) -> Iterable[Browser]:
    for binary in (*CHROMIUM_BINARIES, *FIREFOX_BINARIES, *OTHER_BINARIES):
        resolved = which(binary)
        if not resolved:
            continue
        kind = classify_browser(binary)
        yield Browser(
            id=binary,
            name=_BINARY_NAMES.get(binary, binary),
            kind=kind,
            command=(resolved,),
            kiosk=kind in KIOSK_KINDS,
        )


def detect_browsers(
    *,
    app_infos: Optional[Iterable[Any]] = None,
    which: Callable[[str], Optional[str]] = shutil.which,
    default_app_id: str = "",
) -> list[Browser]:
    """Lista os navegadores instalados, sem duplicar a mesma família.

    ``app_infos`` e ``which`` existem para os testes: em produção as entradas
    desktop vêm do Gio e os binários do ``PATH``.
    """
    del default_app_id  # reservado para chamadas futuras; a seleção é à parte
    infos = _app_infos_from_gio() if app_infos is None else list(app_infos)

    found: list[Browser] = []
    seen: set[tuple[str, str]] = set()
    seen_commands: set[str] = set()

    for info in infos:
        browser = _browser_from_app_info(info, which)
        if browser is None:
            continue
        key = (_normalize(browser.name), browser.kind)
        command_key = Path(browser.command[-1]).name if browser.command else ""
        if key in seen or (command_key and command_key in seen_commands):
            continue
        seen.add(key)
        if command_key:
            seen_commands.add(command_key)
        found.append(browser)

    for browser in _browsers_from_path(which):
        key = (_normalize(browser.name), browser.kind)
        if key in seen:
            continue
        seen.add(key)
        found.append(browser)

    return sorted(found, key=lambda item: item.name.casefold())


def _normalized_id(value: str) -> str:
    return _strip_desktop_suffix((value or "").strip()).casefold()


def default_browser(
    browsers: Optional[Sequence[Browser]] = None,
    *,
    default_app_id: str = "",
) -> Optional[Browser]:
    """Navegador padrão do sistema, ou o primeiro detectado."""
    items = list(browsers) if browsers is not None else detect_browsers()
    if not items:
        return None
    wanted = _normalized_id(default_app_id) or _normalized_id(_default_app_id_from_gio())
    if wanted:
        for browser in items:
            ids = {_normalized_id(browser.id)}
            if browser.command:
                ids.add(_normalized_id(browser.command[-1]))
                ids.add(_normalized_id(Path(browser.command[-1]).name))
            if wanted in ids:
                return browser
    return items[0]


def resolve_browser(
    browser_id: str,
    browsers: Optional[Sequence[Browser]] = None,
    *,
    default_app_id: str = "",
) -> Optional[Browser]:
    """Resolve o id salvo nas preferências; vazio/desconhecido cai no padrão."""
    items = list(browsers) if browsers is not None else detect_browsers()
    wanted = _normalized_id(browser_id)
    if wanted:
        for browser in items:
            if _normalized_id(browser.id) == wanted:
                return browser
        logger.info("Navegador configurado (%s) não está instalado", browser_id)
    return default_browser(items, default_app_id=default_app_id)


def _safe_profile_name(browser_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", browser_id or "").strip("-.")
    return safe or "browser"


def _is_flatpak(browser: Browser) -> bool:
    return bool(browser.command) and Path(browser.command[0]).name == "flatpak"


def profile_dir_for(browser: Browser, base: Optional[Path] = None) -> Path:
    """Diretório de dados dedicado do navegador (visível dentro do sandbox).

    Para Flatpak o caminho devolvido é o que o processo enxerga dentro do
    sandbox; ``_host_profile_dir`` devolve onde criá-lo no host.
    """
    name = _safe_profile_name(browser.id)
    if _is_flatpak(browser):
        return Path.home() / ".local" / "share" / "jolven" / "browser-profiles" / name
    if base is not None:
        return Path(base) / name
    from cartridges import shared  # noqa: PLC0415

    return Path(shared.data_dir) / "jolven" / "browser-profiles" / name


def _host_profile_dir(browser: Browser, sandbox_dir: Path) -> Path:
    """Caminho real no host equivalente ao diretório visto pelo navegador."""
    if not _is_flatpak(browser):
        return sandbox_dir
    relative = sandbox_dir.relative_to(Path.home())
    app_id = browser.command[-1]
    return Path.home() / ".var" / "app" / app_id / relative


def _prepare_profile(browser: Browser, sandbox_dir: Path) -> None:
    host_dir = _host_profile_dir(browser, sandbox_dir)
    host_dir.mkdir(parents=True, exist_ok=True)
    if browser.kind == KIND_FIREFOX:
        preferences = host_dir / "user.js"
        try:
            preferences.write_text(_PROFILE_PREFERENCE, encoding="utf-8")
        except OSError as error:
            logger.debug("Não foi possível preparar o perfil do Firefox: %s", error)


def kiosk_command(browser: Browser, url: str, profile_dir: Path) -> list[str]:
    """Monta o argv de uma janela nova em modo quiosque (URL sempre no fim)."""
    if browser.kind == KIND_CHROMIUM:
        return [
            *browser.command,
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--kiosk",
            url,
        ]
    if browser.kind == KIND_FIREFOX:
        return [
            *browser.command,
            "-no-remote",
            "-profile",
            str(profile_dir),
            "-kiosk",
            url,
        ]
    return [*browser.command, url]


def _valid_url(url: str) -> bool:
    from urllib.parse import urlsplit  # noqa: PLC0415

    parsed = urlsplit((url or "").strip())
    return parsed.scheme == "https" and bool(parsed.netloc)


def launch_kiosk(
    browser_id: str,
    url: str,
    *,
    browsers: Optional[Sequence[Browser]] = None,
    popen: Callable[..., Any] = subprocess.Popen,
    profile_base: Optional[Path] = None,
) -> tuple[bool, str]:
    """Abre ``url`` numa janela quiosque do navegador configurado.

    Retorna ``(True, "")`` quando o processo foi disparado. Nunca levanta por
    falha do navegador: a UI recebe a mensagem pronta para o toast.
    """
    if not _valid_url(url):
        return False, _("Endereço inválido para abrir o jogo")

    browser = resolve_browser(browser_id, browsers)
    if browser is None:
        return False, _("Nenhum navegador encontrado. Instale um navegador ou escolha outro nas preferências.")

    profile = profile_dir_for(browser, profile_base)
    try:
        _prepare_profile(browser, profile)
    except OSError as error:
        logger.warning("Perfil do navegador indisponível (%s): %s", profile, error)
        return False, _("Não foi possível preparar o perfil do navegador: %s") % error

    argv = kiosk_command(browser, url.strip(), profile)
    logger.info("Abrindo xCloud em modo quiosque com %s", browser.name)
    try:
        popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as error:
        logger.warning("Falha ao abrir %s: %s", browser.name, error)
        return False, _("Não foi possível abrir o navegador: %s") % error
    return True, ""
