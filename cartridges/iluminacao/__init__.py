# __init__.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Iluminação por jogo: perfis, diário, coordenador e provedores.

O pacote é dividido por responsabilidade, e importar o pacote **não** importa
GTK nem abre rede:

``cores``
    A cor RGB de 8 bits e as conversões que o resto do pacote usa.
``modelo``
    O que é um dispositivo (:class:`~.modelo.Alvo`), o que um perfil manda
    fazer (:class:`~.modelo.Plano`) e o que estava valendo antes
    (:class:`~.modelo.Estado`).
``perfis``
    Leitura e escrita de ``iluminacao/perfis.json``, com escrita atômica e
    campos desconhecidos preservados.
``diario``
    Leitura e escrita de ``iluminacao/sessao.json``, o retrato do que existia
    antes de cada dispositivo ser tocado.
``coordenador``
    A thread única, a pilha de jogos e as operações ``comecar``/``terminar``.
``provedores``
    O contrato e as duas implementações: OpenRGB e Tuya.

``coordenador`` é importado pelo nome do módulo
(``from cartridges.iluminacao import coordenador``) em vez de reexportado aqui:
cada submódulo importa os vizinhos, e reexportar tudo criaria um ciclo de
importação entre o pacote e os provedores.
"""
