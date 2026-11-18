# Auditoria visual do ConsoleUI (issue #177)

Inventário 1:1 dos componentes do [Aurora Launcher]
(https://github.com/codebyallan/aurora-launcher, commit
`bf0a6b845638bd044f9f5c067f53e549929e0932`) e mapeamento para o Jolven.
Este documento é o resultado da etapa **F0** do épico #176 (ConsoleUI):
referência, escopo e licença. Não é implementação.

## Como usar

Cada entrada abaixo nomeia um componente do Aurora, o equivalente (ou a
ausência) no Jolven hoje e a decisão de adaptação para o Console. As telas do
Console herdam a identidade Jolven (cores semânticas libadwaita, ícones
simbólicos, i18n pt-BR/en/es) e não reimplementam backend, persistência ou
execução de jogos.

## Componentes do Aurora e contrapartida no Jolven

| Componente Aurora | O que faz | Contrapartida no Jolven / decisão |
|---|---|---|
| `AppBackground` | Imagem full-bleed com degradês de fundo | Fundo da sessão já existe (`session_wallpaper`); reusar com fallback cor sólida |
| `AppHeader` | Header com relógio e controles globais | Header da `window.blp`; adicionar relógio e seletor Flat/Console |
| `GameCarouselItem` | Tile de jogo no carrossel horizontal | Cartão da biblioteca (`game.blp`); portar foco e seleção por gamepad |
| `GameHeroSection` | Título, descrição e botões Play/Stop | Hero da sessão; ligar a `Game.launch` / `ProcessSession` |
| `GameContextMenu` | Menu de contexto do item | Menu contexto existente na biblioteca |
| `AddGameModal` | Cadastro/edição de jogo | Telas de edição já existem; adaptar ao Console |
| `ConfirmModal` | Confirmação de exclusão/ação | Dialog de confirmação já existe |
| `GameLoadingOverlay` | Overlay de carregamento | Overlay de carga da sessão |
| `ControllerHints` | Dicas de gamepad na UI | Dicas de gamepad já existem (libmanette) |
| `AppSidebar` (implicito) | Navegação entre bibliotecas/filtros | Sidebar da biblioteca já existe |

## Estados de tela exigidos pelo Console

- Carregamento (loader, spinner) e vazio (empty state).
- Hero com capa full-bleed, título, descrição, botão Play/Stop.
- Carrossel horizontal de capas com foco visível, item ativo ampliado, navegação
  por gamepad (d-pad/analógico) e teclado.
- Menu de contexto (jogar/parar/editar/remover) e modais (confirmação, edição).
- Header com relógio, seletor de modo (Flat/Console) e ações do sistema.
- Toast para erros e confirmações.

## Requisitos não funcionais (do épico #176)

- Navegável a 100% por gamepad e teclado; foco visível e previsível.
- i18n pt-BR/en/es; integração com tema do Jolven (escuro/alto contraste).
- Fallback ao Jolven Flat quando WebKitGTK ausente ou o renderer crashe.
- Sem Electron/Node em runtime; o WebView não acessa FS, shell, segredos nem
  comandos arbitrários.
- Licença GPL-3.0 para o frontend adaptado do Aurora; manter avisos de autoria.

Refs #176
Refs #177
