# Android — seleção de emulador por console

Implementação incremental dos issues [#85](https://github.com/zonaro/jolven/issues/85) e [#151](https://github.com/zonaro/jolven/issues/151).

**Decisão:** o Jolven é exclusivamente frontend. A descoberta não instala, incorpora nem confirma o funcionamento de RetroArch ou de qualquer outro emulador.

O helper Dart `emulator_compatibility.dart` aplica uma matriz conservadora de famílias de console para ordenar os aplicativos detectados e distinguir `view_documented` (contrato documentado ainda sem QA físico), `view_unverified`, `manual` e `retroArchPathsUnverified`. Uma associação por extensão não comprova que o arquivo é ROM válida, e `RetroArch` não comprova que o core/BIOS exista.

O usuário define **um emulador padrão por console**, opcional, preservado no Android SharedPreferences, e pode sobrescrever o padrão **para um jogo específico**. Preferência por jogo tem maior prioridade. Se o emulador foi desinstalado, não aparece no seletor nem recebe intents; não há seleção automática de fallback silencioso. Emuladores indicados para outro console só aparecem ao expandir **Mostrar outros emuladores instalados**, e nesse caso o app apenas abre o emulador manualmente, sem solicitar execução do conteúdo.

Strings da experiência em pt-BR/en/es, com teste determinístico para rank, ausência de emulador, compatibilidade desconhecida, caminhos explícitos do RetroArch e preferência por jogo/console. Alterações são isoladas do catálogo Android e das coleções existentes.

**Pendente:** contratos versionados por emulador, validação em hardware Android real, gamepad no seletor, core/firmware verificados por API pública quando existir, BIOS livre de acesso ao sandbox e fluxo de retorno do app externo. Sem fechar os issues por essa entrega parcial.
