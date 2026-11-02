# adapter.py
#
# Copyright 2026 Jolven contributors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Adaptador de alto nível para o cliente JSON da TDLib.

Toda comunicação com a biblioteca nativa (``libtdjson``) e com a rede do
Telegram acontece fora da thread do GTK. A classe se degrada com elegância
quando a TDLib não está instalada: todos os métodos reportam indisponibilidade
sem quebrar o Jolven.

Não há envio de convites, anúncios ou qualquer ação automática em nome do
usuário: cada requisição à TDLib é feita apenas em resposta a um gesto explícito
(cadastrar telefone, digitar código, digitar senha, enviar mensagem).
"""

from __future__ import annotations

import ctypes
import json
import logging
import threading
from typing import Any, Callable, Optional

from cartridges.integrations.telegram import biblioteca, disponivel
from cartridges.integrations.telegram.auth import EstadoAutorizacao
from cartridges.integrations.telegram.errors import (
    TelegramApiLimitsError,
    TelegramIntegrationError,
    TelegramNetworkError,
    TelegramNotAuthorizedError,
    TelegramUnavailableError,
)
from cartridges.integrations.telegram.sessao import (
    apagar_sessao,
    carregar_chave_encriptacao,
    salvar_chave_encriptacao,
)

log = logging.getLogger(__name__)

#: Tamanho máximo aceito para uma resposta JSON da TDLib (barra payloads deformados).
_MAX_RESPOSTA = 16 * 1024 * 1024


class _ClienteTdlib:
    """Envelope fino sobre ``libtdjson`` via ctypes.

    Não é reentrante: pertence à thread que o criou. A rede bloqueia, portanto só
    deve ser usado em workers. Os ponteiros ``char *`` devolvidos são copiados
    imediatamente pelo ctypes (``c_char_p``), então não há risco de buffer
    pendente entre chamadas.
    """

    def __init__(self) -> None:
        lib = biblioteca()
        if lib is None:
            raise TelegramUnavailableError()
        self._lib = lib

        self._lib.td_json_client_create.restype = ctypes.c_void_p
        self._lib.td_json_client_create.argtypes = []

        self._lib.td_json_client_send.restype = None
        self._lib.td_json_client_send.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
        ]

        self._lib.td_json_client_receive.restype = ctypes.c_char_p
        self._lib.td_json_client_receive.argtypes = [
            ctypes.c_void_p,
            ctypes.c_double,
        ]

        self._lib.td_json_client_execute.restype = ctypes.c_char_p
        self._lib.td_json_client_execute.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
        ]

        self._lib.td_json_client_destroy.restype = None
        self._lib.td_json_client_destroy.argtypes = [ctypes.c_void_p]

        self._lib.td_set_log_verbosity_level.restype = None
        self._lib.td_set_log_verbosity_level.argtypes = [ctypes.c_int]

        self._cliente: Optional[int] = None
        self._ativo = False

    def criar(self) -> None:
        if self._cliente is not None:
            return
        cliente = self._lib.td_json_client_create()
        if not cliente:
            raise TelegramNetworkError("Não foi possível criar o cliente TDLib")
        self._cliente = cliente
        self._ativo = True

    def definir_verbosidade(self, nivel: int) -> None:
        if self._lib is None:
            return
        try:
            self._lib.td_set_log_verbosity_level(nivel)
        except OSError:  # pragma: no cover - defesa em profundidade
            pass

    def enviar(self, requisicao: dict[str, Any]) -> None:
        if not self._ativo:
            raise TelegramNetworkError("Cliente TDLib não está ativo")
        payload = json.dumps(requisicao, ensure_ascii=False).encode("utf-8")
        try:
            self._lib.td_json_client_send(self._cliente, payload)  # type: ignore[arg-type]
        except OSError as erro:
            self._ativo = False
            raise TelegramNetworkError(
                f"Falha ao enviar requisição à TDLib: {erro}"
            ) from erro

    def receber(self, timeout: float = 5.0) -> Optional[dict[str, Any]]:
        if not self._ativo:
            return None
        try:
            bruto = self._lib.td_json_client_receive(
                self._cliente,  # type: ignore[arg-type]
                ctypes.c_double(timeout),
            )
        except OSError as erro:
            self._ativo = False
            raise TelegramNetworkError(
                f"Falha ao receber da TDLib: {erro}"
            ) from erro
        if not bruto:
            return None
        texto = bytes(bruto).decode("utf-8", "replace")[:_MAX_RESPOSTA]
        try:
            return json.loads(texto)
        except json.JSONDecodeError:
            log.debug("TDLib devolveu payload não-JSON ignorado: %r", texto[:200])
            return None

    def executar(self, requisicao: dict[str, Any]) -> Optional[dict[str, Any]]:
        if not self._ativo:
            return None
        payload = json.dumps(requisicao, ensure_ascii=False).encode("utf-8")
        try:
            bruto = self._lib.td_json_client_execute(
                self._cliente,  # type: ignore[arg-type]
                payload,
            )
        except OSError as erro:
            self._ativo = False
            raise TelegramNetworkError(
                f"Falha ao executar na TDLib: {erro}"
            ) from erro
        if not bruto:
            return None
        texto = bytes(bruto).decode("utf-8", "replace")[:_MAX_RESPOSTA]
        try:
            return json.loads(texto)
        except json.JSONDecodeError:
            return None

    def fechar(self) -> None:
        if self._cliente is not None:
            try:
                self._lib.td_json_client_destroy(self._cliente)  # type: ignore[arg-type]
            except OSError:
                pass
            self._cliente = None
            self._ativo = False


class TelegramAdapter:
    """Coordena o cliente TDLib e o estado de autorização da conta.

    Usado pela página de Preferências e, no futuro, pelas telas de chat e voz.
    Não toca GTK: os resultados chegam à UI pelos callbacks do construtor ou
    por ``entregar_na_tela`` no chamador.
    """

    def __init__(
        self,
        *,
        on_estado: Optional[Callable[[EstadoAutorizacao], None]] = None,
        on_atualizacao: Optional[Callable[[dict[str, Any]], None]] = None,
        on_erro: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._on_estado = on_estado
        self._on_atualizacao = on_atualizacao
        self._on_erro = on_erro
        self._cliente: Optional[_ClienteTdlib] = None
        self._estado = EstadoAutorizacao.DESLIGADO
        self._telefone: Optional[str] = None
        self._codigo_hash: Optional[str] = None
        self._api_id: Optional[str] = None
        self._api_hash: Optional[str] = None
        # Loop de recepção em background (td_json_client_receive bloqueia).
        self._receber_thread: Optional[threading.Thread] = None
        self._receber_parar = threading.Event()
        self._receber_lock = threading.Lock()

    # -- propriedades ---------------------------------------------------

    @property
    def estado(self) -> EstadoAutorizacao:
        return self._estado

    @property
    def conectado(self) -> bool:
        return self._estado is EstadoAutorizacao.AUTORIZADO

    @property
    def telefone(self) -> Optional[str]:
        return self._telefone

    @property
    def precisa_acao(self) -> bool:
        return self._estado.necessita_acao_do_usuario

    # -- ciclo de vida --------------------------------------------------

    def esta_disponivel(self) -> bool:
        """Se a TDLib nativa pode ser carregada (pré-requisito)."""
        return disponivel()

    def conectar(self, api_id: str, api_hash: str) -> None:
        """Inicia o cliente TDLib e começa o fluxo de autorização."""
        if not disponivel():
            self._definir_estado(EstadoAutorizacao.ERRO)
            self._reportar_erro(
                "A biblioteca TDLib (libtdjson) não está instalada."
            )
            raise TelegramUnavailableError()
        if self._cliente is not None:
            return
        self._api_id = api_id
        self._api_hash = api_hash
        self._definir_estado(EstadoAutorizacao.CONECTANDO)
        try:
            cliente = _ClienteTdlib()
            cliente.definir_verbosidade(2)  # erro/fatal apenas; não polui o console
            cliente.criar()
            self._cliente = cliente
        except TelegramUnavailableError:
            self._definir_estado(EstadoAutorizacao.ERRO)
            self._reportar_erro("Não foi possível carregar a biblioteca TDLib.")
            raise
        except Exception as erro:  # pylint: disable=broad-exception-caught
            logging.exception("Falha ao iniciar o cliente TDLib")
            self._definir_estado(EstadoAutorizacao.ERRO)
            self._reportar_erro(str(erro) or "Falha ao iniciar o cliente TDLib")
            raise TelegramNetworkError(str(erro)) from erro

        # Configura os parâmetros da TDLib, incluindo a chave de criptografia
        # salva no cofre (se houver), para não exigir login do zero.
        self._enviar_tdlib_parametros(chave_salva=carregar_chave_encriptacao())
        # Consulta o estado de autorização atual da sessão.
        self._enviar({"@type": "getAuthorizationState", "@extra": None})
        self.iniciar_recepcao()

    def desconectar(self) -> None:
        """Encerra o cliente TDLib e limpa o estado local.

        Não remove mensagens nem a conta remota: apenas encerra a sessão local.
        """
        self._api_id = None
        self._api_hash = None
        self._telefone = None
        self._codigo_hash = None
        self.parar_recepcao()
        # Remove apenas a sessão local do cofre, sem tocar na conta remota.
        apagar_sessao()
        if self._cliente is not None:
            try:
                self._cliente.fechar()
            finally:
                self._cliente = None
        self._definir_estado(EstadoAutorizacao.DESLIGADO)

    @property
    def recebendo(self) -> bool:
        """Se o loop de recepção em background está ativo."""
        return self._receber_thread is not None and self._receber_thread.is_alive()

    def enviar(self, requisicao: dict[str, Any]) -> None:
        """Envia uma requisição bruta à TDLib (ex: sendMessage)."""
        if self._cliente is None:
            raise TelegramNetworkError("Cliente TDLib não iniciado")
        self._cliente.enviar(requisicao)

    def iniciar_recepcao(self) -> None:
        """Inicia o loop de recepção da TDLib em uma thread de background.

        O loop chama ``td_json_client_receive`` com timeout, processando
        atualizações até que ``parar_recepcao()`` seja chamado ou o cliente
        seja destruído. Não bloqueia a thread do GTK.
        """
        if self.recebendo:
            return
        if self._cliente is None:
            raise TelegramNetworkError("Cliente TDLib não iniciado")
        self._receber_parar.clear()

        def loop() -> None:
            while not self._receber_parar.is_set():
                try:
                    resposta = self.processar_uma(timeout=2.0)
                except TelegramNetworkError:
                    # A conexão caiu: encerra o loop e avisa.
                    self._definir_estado(EstadoAutorizacao.ERRO)
                    self._reportar_erro("Conexão com a TDLib perdida.")
                    break
                except Exception:  # pylint: disable=broad-exception-caught
                    logging.exception("Erro no loop de recepção do Telegram")
                    break
                if resposta is None:
                    continue

        self._receber_thread = threading.Thread(target=loop, daemon=True, name="telegram-receber")
        self._receber_thread.start()

    def parar_recepcao(self) -> None:
        """Pede ao loop de recepção para encerrar e aguarda seu término."""
        self._receber_parar.set()
        thread = self._receber_thread
        if thread is not None and thread.is_alive():
            try:
                thread.join(timeout=5.0)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.debug("Não foi possível aguardar o loop de recepção")
        self._receber_thread = None

    # -- requisições ----------------------------------------------------

    def _enviar(self, requisicao: dict[str, Any]) -> None:
        if self._cliente is None:
            raise TelegramNetworkError("Cliente TDLib não iniciado")
        self._cliente.enviar(requisicao)

    def processar_uma(self, timeout: float = 5.0) -> Optional[dict[str, Any]]:
        """Processa uma atualização da TDLib. Chamado em loop por um worker."""
        if self._cliente is None:
            return None
        resposta = self._cliente.receber(timeout)
        if resposta is None:
            return None
        self._tratar_resposta(resposta)
        return resposta

    def _tratar_resposta(self, resposta: dict[str, Any]) -> None:
        tipo = resposta.get("@type")
        if tipo == "updateAuthorizationState":
            estado = resposta.get("authorization_state", {}) or {}
            self._interpretar_estado_autorizacao(estado, estado.get("@type"))
        elif tipo == "error":
            mensagem = resposta.get("message", "erro desconhecido")
            self._reportar_erro(str(mensagem))
            if self._estado is EstadoAutorizacao.CONECTANDO:
                self._definir_estado(EstadoAutorizacao.ERRO)
        elif tipo == "databaseEncryptionKey":
            chave = resposta.get("key", "")
            if chave:
                salvar_chave_encriptacao(chave)
                log.info("Telegram: chave de criptografia persistida no cofre")
        elif self._on_atualizacao is not None:
            self._on_atualizacao(resposta)

    def _interpretar_estado_autorizacao(
        self, estado: dict[str, Any], estado_tipo: Optional[str]
    ) -> None:
        if estado_tipo == "authorizationStateWaitTdlibParameters":
            self._definir_estado(EstadoAutorizacao.CONECTANDO)
            self._enviar_tdlib_parametros()
        elif estado_tipo == "authorizationStateWaitEncryptionKey":
            self._definir_estado(EstadoAutorizacao.CONECTANDO)
            self._enviar({"@type": "checkDatabaseEncryptionKey", "@extra": None})
        elif estado_tipo == "authorizationStateWaitPhoneNumber":
            self._definir_estado(EstadoAutorizacao.AUTORIZANDO_TELEFONE)
        elif estado_tipo == "authorizationStateWaitCode":
            self._codigo_hash = estado.get("phone_number_hash")
            self._telefone = estado.get("phone_number")
            self._definir_estado(EstadoAutorizacao.AUTORIZANDO_CODIGO)
        elif estado_tipo == "authorizationStateWaitPassword":
            self._definir_estado(EstadoAutorizacao.AUTORIZANDO_SENHA)
        elif estado_tipo == "authorizationStateWaitQrCode":
            self._definir_estado(EstadoAutorizacao.AUTORIZANDO_QR)
        elif estado_tipo == "authorizationStateReady":
            self._definir_estado(EstadoAutorizacao.AUTORIZADO)
            log.info("Telegram: conta autorizada")
            # Obtém e persiste a chave de criptografia do banco TDLib.
            try:
                self._cliente.executar({"@type": "getDatabaseEncryptionKey"})
            except Exception:  # pylint: disable=broad-exception-caught
                logging.debug("Não foi possível solicitar a chave de criptografia")
        elif estado_tipo in ("authorizationStateClosing", "authorizationStateClosed"):
            self._definir_estado(EstadoAutorizacao.DESLIGADO)
        else:
            log.debug("TDLib: estado de autorização %s", estado_tipo)

    def _enviar_tdlib_parametros(self, *, chave_salva: str = "") -> None:
        if self._api_id is None or self._api_hash is None:
            self._definir_estado(EstadoAutorizacao.ERRO)
            self._reportar_erro(
                "api_id e api_hash do Telegram não configurados."
            )
            return
        try:
            api_id_int = int(self._api_id)
        except (TypeError, ValueError):
            api_id_int = 0
            log.warning("api_id do Telegram não numérico: %r", self._api_id)
        parametros: dict[str, object] = {
            "@type": "setTdlibParameters",
            "@extra": None,
            "api_id": api_id_int,
            "api_hash": self._api_hash,
            "device_model": "Jolven",
            "system_version": "Linux",
            "application_version": "1.0",
            "use_chat_info_database": True,
            "use_message_database": True,
            "use_secret_chats": False,
            "use_file_database": True,
            "use_push_receiver_database": True,
            "database_directory": "",
        }
        if chave_salva:
            parametros["database_encryption_key"] = chave_salva
        self._enviar(parametros)

    # -- ações do usuário (apenas por gesto explícito) ------------------

    def cadastrar_telefone(self, telefone: str) -> None:
        """Envia o número de telefone para iniciar o código de verificação."""
        if self._cliente is None:
            raise TelegramNetworkError("Cliente TDLib não iniciado")
        self._telefone = telefone
        self._enviar(
            {
                "@type": "setAuthenticationPhoneNumber",
                "@extra": None,
                "phone_number": telefone,
                "allow_flash_call": False,
                "is_current_phone_number": True,
            }
        )

    def enviar_codigo(self, codigo: str) -> None:
        """Envia o código de verificação recebido por SMS/Telegram."""
        if self._cliente is None:
            raise TelegramNetworkError("Cliente TDLib não iniciado")
        self._enviar(
            {
                "@type": "checkAuthenticationCode",
                "@extra": None,
                "code": codigo,
            }
        )

    def enviar_senha(self, senha: str) -> None:
        """Envia a senha de verificação em duas etapas (2FA)."""
        if self._cliente is None:
            raise TelegramNetworkError("Cliente TDLib não iniciado")
        self._enviar(
            {
                "@type": "checkAuthenticationPassword",
                "@extra": None,
                "password": senha,
            }
        )

    # -- helpers internos -----------------------------------------------

    def _definir_estado(self, estado: EstadoAutorizacao) -> None:
        if self._estado is estado:
            return
        self._estado = estado
        if self._on_estado is not None:
            try:
                self._on_estado(estado)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("Callback de estado do Telegram falhou")

    def _reportar_erro(self, mensagem: str) -> None:
        log.error("Telegram: %s", mensagem)
        if self._on_erro is not None:
            try:
                self._on_erro(mensagem)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("Callback de erro do Telegram falhou")


__all__ = [
    "TelegramAdapter",
    "EstadoAutorizacao",
    "TelegramIntegrationError",
    "TelegramUnavailableError",
    "TelegramNotAuthorizedError",
    "TelegramNetworkError",
    "TelegramApiLimitsError",
]
