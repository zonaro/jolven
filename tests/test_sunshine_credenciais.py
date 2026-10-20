# test_sunshine_credenciais.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for the Sunshine keyring credentials (libsecret mocked).

No real keyring, no GTK, no libsecret typelib: both ``Secret`` and
``_SCHEMA`` are injected, so the suite is honest on a bare machine.
"""

import unittest

from contextlib import contextmanager
from typing import Any, Iterator
from unittest.mock import patch

from cartridges.utils import sunshine_credenciais


class FakeSecret:
    """Minimal stand-in for ``gi.repository.Secret``."""

    COLLECTION_DEFAULT = "default"
    SchemaFlags = type("SchemaFlags", (), {"NONE": 0})
    SchemaAttributeType = type("SchemaAttributeType", (), {"STRING": 0})

    class Schema:
        @staticmethod
        def new(*_args: Any, **_kwargs: Any) -> str:
            return "schema"

    def __init__(self) -> None:
        self.stored: dict = {}
        self.fail_store: Any = None
        self.fail_lookup: Any = None

    def password_store_sync(
        self,
        _schema: Any,
        _attrs: Any,
        _collection: Any,
        _label: str,
        password: str,
        _cancellable: Any,
    ) -> None:
        if self.fail_store is not None:
            raise self.fail_store
        self.stored["password"] = password

    def password_lookup_sync(
        self, _schema: Any, _attrs: Any, _cancellable: Any
    ) -> Any:
        if self.fail_lookup is not None:
            raise self.fail_lookup
        return self.stored.get("password")


@contextmanager
def cofre(fake: FakeSecret) -> Iterator[FakeSecret]:
    """Inject the fake Secret Service, including a fake schema.

    Both ``Secret`` and ``_SCHEMA`` are replaced: on a machine without the
    libsecret typelib the module-level ``_SCHEMA`` is ``None``, and patching
    only ``Secret`` would leave every test degrading to ``""``.
    """
    with (
        patch.object(sunshine_credenciais, "Secret", fake),
        patch.object(sunshine_credenciais, "_SCHEMA", "fake-schema"),
    ):
        yield fake


class SunshineCredenciaisTests(unittest.TestCase):
    def test_save_then_load_round_trip(self) -> None:
        with cofre(FakeSecret()) as fake:
            sunshine_credenciais.salvar_senha("s3cr3t!")
            self.assertEqual(fake.stored.get("password"), "s3cr3t!")
            self.assertEqual(sunshine_credenciais.carregar_senha(), "s3cr3t!")

    def test_load_empty_vault_returns_empty(self) -> None:
        with cofre(FakeSecret()):
            self.assertEqual(sunshine_credenciais.carregar_senha(), "")

    def test_store_failure_never_raises(self) -> None:
        fake = FakeSecret()
        fake.fail_store = RuntimeError("cofre trancado")
        with cofre(fake):
            sunshine_credenciais.salvar_senha("s3cr3t!")

    def test_lookup_failure_returns_empty_without_raising(self) -> None:
        fake = FakeSecret()
        fake.fail_lookup = RuntimeError("D-Bus fora do ar")
        with cofre(fake):
            self.assertEqual(sunshine_credenciais.carregar_senha(), "")

    def test_corrupt_value_returns_empty(self) -> None:
        fake = FakeSecret()
        fake.stored["password"] = b"\xff\xfe ileg\xedvel"
        with cofre(fake):
            self.assertEqual(sunshine_credenciais.carregar_senha(), "")
        fake.stored["password"] = None
        with cofre(fake):
            self.assertEqual(sunshine_credenciais.carregar_senha(), "")

    def test_undecodable_lookup_returns_empty(self) -> None:
        fake = FakeSecret()
        fake.fail_lookup = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")
        with cofre(fake):
            self.assertEqual(sunshine_credenciais.carregar_senha(), "")

    def test_missing_secret_service_degrades(self) -> None:
        with (
            patch.object(sunshine_credenciais, "Secret", None),
            patch.object(sunshine_credenciais, "_SCHEMA", None),
        ):
            sunshine_credenciais.salvar_senha("s3cr3t!")
            self.assertEqual(sunshine_credenciais.carregar_senha(), "")

    def test_hermetico_sem_typelib(self) -> None:
        """Pin: a suite passa mesmo sem o typelib do libsecret instalado.

        Simula a máquina nua (módulo importado com ``Secret``/``_SCHEMA``
        ``None``) e prova que injetar o cofre falso basta para o round-trip.
        """
        with (
            patch.object(sunshine_credenciais, "Secret", None),
            patch.object(sunshine_credenciais, "_SCHEMA", None),
        ):
            sunshine_credenciais.salvar_senha("antes")
            self.assertEqual(sunshine_credenciais.carregar_senha(), "")
        with cofre(FakeSecret()):
            sunshine_credenciais.salvar_senha("s3cr3t!")
            self.assertEqual(sunshine_credenciais.carregar_senha(), "s3cr3t!")


if __name__ == "__main__":
    unittest.main()
