# __init__.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Integração com o OpenRGB: protocolo do SDK, detecção e comando.

``protocol``
    O cliente do SDK em soquete puro, sem dependência externa: cabeçalho de 16
    bytes, negociação de versão, leitura da descrição dos controladores e os
    pacotes de escrita de cor e modo.
``detection``
    Se o OpenRGB está instalado (nativo ou Flatpak), se o servidor responde e
    em que estado — sempre fora da thread do GTK.

O pacote não importa GTK em nenhum nível: ele é usado pela página de
Integrações, pelas Preferências e pela thread de trabalho da iluminação.
"""
