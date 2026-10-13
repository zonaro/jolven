# manager.py
#
# SPDX-License-Identifier: GPL-3.0-or-later
#
# SteamSkinManager — the single entry point the UI talks to.
#
# It reads the ``steam-skin-enabled`` / ``steam-install-path`` GSettings keys,
# resolves the target Steam installation, debounces rapid profile changes and
# delegates the actual file work to :mod:`installer` / :mod:`recovery`.
#
# It never starts, stops or restarts Steam: after an apply it only reports
# ``precisa_reiniciar`` so the UI can tell the user.  Every public method is
# wrapped in try/except + logging, so a skin problem can never take Jolven
# down with it.

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from cartridges.integrations.steam_skin import detector, installer, recovery
from cartridges.integrations.steam_skin.constants import DEBOUNCE_MS, DEFAULT_COLORTHEME
from cartridges.integrations.steam_skin.recovery import Estado

_ENABLED_KEY = "steam-skin-enabled"
_INSTALL_PATH_KEY = "steam-install-path"


class SteamSkinManager:
    """Coordinates the Steam skin with the shared Jolven theme profile.

    Parameters
    ----------
    schema:
        Optional ``Gio.Settings`` to use instead of ``shared.schema`` (tests,
        alternate profiles).
    """

    def __init__(self, schema: Optional[object] = None) -> None:
        self._schema = schema
        self._pending: Optional[dict] = None
        self._debounce_id: Optional[int] = None
        self._last_signature: Optional[tuple] = None
        self._sync_enabled = True
        self._precisa_reiniciar = False

    # ── Settings ─────────────────────────────────────────────────────

    def _settings(self) -> object:
        if self._schema is not None:
            return self._schema
        from cartridges import shared  # local import: keeps manager GI-optional

        return shared.schema

    @staticmethod
    def _has_key(settings: object, key: str) -> bool:
        """Whether *settings* declares *key*.

        A stale compiled schema makes ``get_*`` abort the process, so every
        read is gated on :meth:`list_keys` first.
        """
        try:
            return key in settings.list_keys()
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.debug("Could not list settings keys: %s", error)
            return False

    def habilitado(self) -> bool:
        """Whether the user enabled the Steam skin."""
        try:
            settings = self._settings()
            if not self._has_key(settings, _ENABLED_KEY):
                return False
            return bool(settings.get_boolean(_ENABLED_KEY))
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.debug("Could not read %s: %s", _ENABLED_KEY, error)
            return False

    def caminho_configurado(self) -> Optional[Path]:
        """The custom install path from GSettings, or ``None`` when auto."""
        try:
            settings = self._settings()
            if not self._has_key(settings, _INSTALL_PATH_KEY):
                return None
            raw = settings.get_string(_INSTALL_PATH_KEY).strip()
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.debug("Could not read %s: %s", _INSTALL_PATH_KEY, error)
            return None
        return Path(raw).expanduser() if raw else None

    def _resolver_caminho(self) -> Optional[Path]:
        """Custom path when set, otherwise the first accessible detection."""
        configured = self.caminho_configurado()
        if configured is not None:
            return configured
        for installation in detector.detect_all():
            if installation.accessible:
                return installation.path
        return None

    # ── Profile signature ────────────────────────────────────────────

    @staticmethod
    def _assinatura(perfil: dict) -> tuple:
        options = perfil.get("opcoes_avancadas") or {}
        return (
            perfil.get("theme_slug"),
            perfil.get("accent"),
            perfil.get("accent_custom"),
            perfil.get("mode"),
            bool(perfil.get("glows")),
            tuple(sorted((str(key), str(value)) for key, value in options.items())),
        )

    @staticmethod
    def _accent_efetivo(perfil: dict) -> object:
        return perfil.get("accent_custom") or perfil.get("accent") or "auto"

    # ── Public API ───────────────────────────────────────────────────

    def aplicar_perfil(self, perfil: dict) -> bool:
        """Schedule a skin apply for *perfil* (debounced, diff-based).

        Returns ``True`` when the request was scheduled, ``False`` when it
        was a no-op or failed to schedule.
        """
        try:
            perfil = dict(perfil or {})
            if self._assinatura(perfil) == self._last_signature:
                logging.debug("Steam skin profile unchanged; nothing to apply")
                return False
            self._pending = perfil
            return self._agendar()
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Could not schedule Steam skin apply: %s", error)
            return False

    def sincronizar_se_habilitado(self, perfil: dict) -> bool:
        """Apply *perfil* only when ``steam-skin-enabled`` is on."""
        try:
            if not self.habilitado():
                logging.debug("Steam skin disabled; not syncing")
                return False
            self._sync_enabled = True
            return self.aplicar_perfil(perfil)
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Steam skin sync failed: %s", error)
            return False

    def desabilitar(self) -> None:
        """Stop syncing. The installed skin is intentionally left in place."""
        self._sync_enabled = False
        self._pending = None
        self._cancelar_debounce()
        logging.info("Steam skin sync disabled (skin left installed)")

    def restaurar_original(self) -> bool:
        """Remove the skin and restore Steam's original CSS files."""
        try:
            self._pending = None
            self._cancelar_debounce()
            path = self._resolver_caminho()
            if path is None:
                logging.info("No Steam installation found; nothing to restore")
                return False
            changed = installer.restaurar(path)
            self._last_signature = None
            self._precisa_reiniciar = recovery.steam_em_execucao()
            logging.info("Steam skin restore requested (changed=%s)", changed)
            return changed
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Steam skin restore failed: %s", error)
            return False

    def estado(self) -> Estado:
        """Current health of the skin for the resolved installation."""
        try:
            path = self._resolver_caminho()
            if path is None:
                return Estado.NAO_ENCONTRADA
            return recovery.verificar_estado(path)
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Could not determine Steam skin state: %s", error)
            return Estado.NAO_ENCONTRADA

    @property
    def precisa_reiniciar(self) -> bool:
        """Set after an apply/restore performed while Steam was running."""
        return self._precisa_reiniciar

    # ── Debounce / apply ─────────────────────────────────────────────

    def _agendar(self) -> bool:
        self._cancelar_debounce()
        try:
            from gi.repository import GLib  # local import: optional in tests

            self._debounce_id = GLib.timeout_add(DEBOUNCE_MS, self._processar_pendente)
            return True
        except Exception:  # no GI available — apply synchronously
            self._processar_pendente()
            return True

    def _cancelar_debounce(self) -> None:
        if self._debounce_id is None:
            return
        try:
            from gi.repository import GLib

            GLib.source_remove(self._debounce_id)
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.debug("Could not cancel skin debounce: %s", error)
        self._debounce_id = None

    def _processar_pendente(self) -> bool:
        """GLib timeout callback. Returns ``False`` to run only once."""
        self._debounce_id = None
        perfil = self._pending
        if perfil is None:
            return False
        if not self._sync_enabled:
            logging.debug("Steam skin sync disabled; skipping pending apply")
            return False
        self._aplicar(perfil)
        return False

    def _aplicar(self, perfil: dict) -> bool:
        try:
            path = self._resolver_caminho()
            if path is None:
                logging.info("No Steam installation found; skin not applied")
                return False

            estado = recovery.verificar_estado(path)
            if estado in (Estado.NAO_ENCONTRADA, Estado.PERMISSAO, Estado.CONFLITO_TERCEIROS):
                logging.warning("Skipping Steam skin apply in state %s", estado)
                return False

            changed = installer.instalar(
                path,
                perfil.get("theme_slug") or DEFAULT_COLORTHEME,
                self._accent_efetivo(perfil),
                perfil.get("mode", "auto"),
                perfil.get("opcoes_avancadas"),
            )
            self._last_signature = self._assinatura(perfil)
            if recovery.steam_em_execucao():
                self._precisa_reiniciar = True
            logging.info("Steam skin applied to %s (changed=%s)", path, changed)
            return changed
        except installer.SkinError as error:
            logging.error("Steam skin apply failed: %s", error)
            return False
        except Exception as error:  # pylint: disable=broad-exception-caught
            logging.error("Unexpected Steam skin apply error: %s", error)
            return False
