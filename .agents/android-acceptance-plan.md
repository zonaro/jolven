# Plano de aceite — Jolven Android (OpenEmux UX + Kwiq Gaming, frontend externo)

Data base: 10/11/2026. Os testes automatizados são apenas pré-requisitos; **não** substituem hardware Android nem QA de rede.

## Preparação

- Baixar `jolven-android-debug` do workflow [Jolven Android frontend](https://github.com/zonaro/jolven/actions/workflows/jolven-android.yml). Instalar no dispositivo de teste com `adb install -r app-debug.apk`, sem instalar sobre uma versão com dados importantes sem backup.
- Usar **ROMs e homebrews próprios/legais**, sem credenciais reais desnecessárias. Não compartilhar logcat contendo tokens do Nearby, nomes pessoais ou diretórios privados.
- Registrar aparelho/modelo, ABI, versão Android, versão Flutter/Jolven e pacotes/versões de RetroArch, PPSSPP, Dolphin e Moonlight (se instalados). Registrar também distro/Wayland/X11 e versão do Jolven Desktop.

## Casos de teste Android

| Caso | Procedimento | Critério de aceite |
|---|---|---|
| A01 — sem emuladores | Abrir Jolven sem RetroArch/PPSSPP/Dolphin | App abre, lista jogos Android, permite importar sem bloquear biblioteca |
| A02 — SAF pasta | Importar pasta de 30 ROMs próprias e reimportar | Sem duplicatas, plataformas identificáveis, formatos ambíguos pedem console |
| A03 — revogação | Revogar acesso à pasta/arquivo no Android | Feedback de indisponibilidade, originais e favoritos intactos |
| A04 — Android games | Abrir app classificado como jogo e adicionar um manualmente | Intents Android funcionam sem ser launcher HOME |
| A05 — RetroArch externo | Configurar RetroArch com core pela própria aplicação; abrir jogo | Sem binários/libretro incorporados; fallback manual e status não verificado quando necessário |
| A06 — PPSSPP externo | Abrir ROM própria por ACTION_VIEW | Resultado real conferido no PPSSPP, sem falso sucesso baseado em intent |
| A07 — gamepad | USB/BT: D-pad, sticks, A/B, foco, navegação, reconexão | Todos os controles do **hub** funcionam; não injetar input no jogo externo |
| A08 — i18n | Alterar idioma Android entre pt-BR/en/es | Fluxos centrais sem rótulos incorretos ou texto truncado |
| A09 — arte | Importar capa/etiqueta e usar busca Libretro | Arquivo original preservado; cache e fonte respeitados; falha de rede não sobrescreve |
| A10 — save vault | Importar/exportar saves por SAF e simular erro/arquivo inválido | Sem acesso a sandbox privado e sem sobrescrever original silenciosamente |
| A11 — patcher | IPS/UPS/BPS com fixtures legais e patch inválido | Resultado esperado, integridade do original, erro recuperável |
| A12 — gravação | Consentir MediaProjection; iniciar/parar e abrir MP4 | Sem captura silenciosa, vídeo correto, revogação tratada |
| A13 — tablets | Rotação/tela grande/fold emulador | Biblioteca responde e preserva seleção/foco |
| A14 — hardcore | RetroAchievements no emulador externo | Jolven só consulta progresso real, nunca fabrica desbloqueios |
| A15 — Nearby PC→Android | PC envia ROM própria por HTTPS, Android pin+token e SAF | Hash final igual, arquivo salvo após escolha explícita, cancelamento seguro |
| A16 — Nearby Android→PC | Desktop receptor aprova por YES; Android faz upload | Sem sobrescrita de nome, hash conferido, arquivo original intacto |
| A17 — Nearby host errado | Trocar fingerprint/token, IP público, pacote truncado | Conexão recusada antes do envio de arquivos; nenhum destino é alterado |
| A18 — Offline | Desligar Wi-Fi/dados durante biblioteca e ações locais | Navegação, favoritos, saves locais e importação continuam operacionais |

## Casos Desktop / Jolven Session

- D01: importar ROMs por arquivo/pasta/ZIP ambíguo, verificar biblioteca e estado após reiniciar.
- D02: RetroArch → **Diagnosticar**, escolher cfg pessoal; ler diretórios e cores sem alterar `retroarch.cfg`.
- D03: RetroArch → **Ações**, ativar manualmente Network Commands no RetroArch **restrito a localhost**, enviar pausa/screenshot/menu e verificar resultado físico no emulador; GUI nunca afirmar execução confirmada.
- D04: selecionar shader `.slangp` via file picker, confirmar aplicação e fallback num RetroArch real, incluindo Flatpak e núcleo incompatível.
- D05: testar backup e restauração de saves com ROM e core/versão diferentes; impedir sobrescrita silenciosa.
- D06: testar mesma sessão via teclado, gamepad e Jolven Session (Gamescope), Wayland/X11, loss-of-focus.

## Matriz e evidências

Anexar ao issue correspondente **resultado esperado/real**, versões/pacotes, log limitado e captura de tela sem segredos, com `PASS/FAIL/BLOCKED`. Não fechar #89 ou subissues por ter apenas CI verde. Para assinar release, configurar os quatro secrets documentados em `.agents/android-release-signing.md`; guardar a keystore fora do GitHub com backup. **Não promover o APK de debug a release pública.**
