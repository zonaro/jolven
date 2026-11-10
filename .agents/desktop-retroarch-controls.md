# Controles opcionais de RetroArch no Jolven Desktop (#156)

RetroArch é um **aplicativo externo**; o Jolven não incorpora cores nem intercepta foco ou controles de jogos. Esta etapa integra o [Network Control Interface oficial](https://docs.libretro.com/development/retroarch/network-control-interface/) ao Desktop, somente com consentimento e configuração manual pelo usuário.

## Como usar

1. Em RetroArch → Configurações → Rede → Comandos de rede, habilite o protocolo UDP opcional e **restrinja a escuta ao loopback** (127.0.0.1), quando essa opção existir. Não exponha a porta 55355 à rede Wi-Fi/LAN.
2. Abra Jolven → Integrações → RetroArch → **Ações**. A tela consulta `GET_STATUS` e habilita controles apenas se encontrar um jogo ativo.
3. São permitidos apenas comandos oficiais de menu, pausa, captura, áudio e velocidade. Nenhum comando de escrita de memória, execução arbitrária, troca de core, `QUIT` ou carregamento de estado é emitido pela tela. O botão **Escolher shader personalizado** permite um único `SET_SHADER` para arquivo local `.slangp`, `.glslp` ou `.cgp` explicitamente escolhido pelo usuário, com validação estrita de caminho e limite de 4 MiB.

## Segurança e limitações

- `cartridges/utils/retroarch_nci.py` só usa UDP destino **127.0.0.1**, porta inteira 1024–65535 e comandos de uma allowlist estrita.
- O Jolven não altera `retroarch.cfg`, não ativa o serviço e não abre portas. As ações são manuais e só são enviadas quando a interface pública responde a `GET_STATUS`.
- UDP não confirma a execução. A UI exibe **comando enviado (execução não verificada)**. Não alterar estado dos botões assumindo que uma ação foi efetivamente realizada.
- Respostas UDP locais não são autenticadas; uma aplicação local maliciosa pode simular o NCI. Esta integração é opcional e nunca controla um host remoto.
- O diálogo é de desktop, **não overlay garantido dentro da Jolven Session**. Gamepad na sessão, FPS/shader por core, modo hardcore, Wayland/Gamescope e perda de foco ainda exigem testes físicos. Não fechar #156 até esses critérios.
- O comando RESET e as ações potencialmente destrutivas não são exibidos na UI. Não habilitar SAVE/LOAD_STATE se não houver verificação de hardcore.

## Testes
`python -m unittest tests.test_retroarch_nci -v` inclui um servidor UDP temporário de loopback, tratamento de interface ausente, parâmetros inválidos e rejeição de comandos perigosos.

## Shader temporário (10/11/2026)
O usuário pode selecionar um preset local no diálogo de controles; a ponte só transmite `SET_SHADER /caminho/absoluto` para 127.0.0.1:55355 depois de verificar `GET_STATUS` com conteúdo em execução. Paths com quebra de linha, ponto-e-vírgula, NUL ou formatos inesperados são rejeitados. **Não** altera globalmente `retroarch.cfg`, nem salva preferência por jogo, nem valida o resultado no emulador. O arquivo deve ser acessível ao processo externo do RetroArch, inclusive através do Flatpak quando for o caso. Testes de fixtures locais não substituem teste real com Vulkan/OpenGL e hardcore.
