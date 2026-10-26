# __init__.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Os jeitos de controlar luz que o Jolven conhece.

``base``
    :class:`~.base.Provedor`, o contrato de cinco métodos. Nenhum método
    levanta: quem falha devolve vazio, ``None`` ou ``False``.
``openrgb``
    O servidor do SDK do OpenRGB, com a conexão reaproveitada entre chamadas.
``tuya``
    As fitas que o :mod:`cartridges.utils.session_fita` já controla, vistas
    como dispositivos de um perfil.
"""
