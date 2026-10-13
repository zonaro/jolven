# Temas e personalização visual

Este documento descreve o sistema nativo de personalização visual do Jolven e a
integração opcional com a Steam. Ele é a referência para a página **Aparência**,
para os módulos `cartridges/themes/` e `cartridges/integrations/steam_skin/` e
para o vendor `data/vendor/adwaita-for-steam/`.

Instruções obrigatórias e resumidas permanecem em [`../AGENTS.md`](../AGENTS.md);
aqui ficam o contexto, os contratos e as decisões.

## Visão geral

Existem dois motores independentes que compartilham o mesmo perfil de aparência:

- **ThemeManager** (`cartridges/themes/`) — aplica temas ao próprio Jolven com
  GTK4/libadwaita, em tempo real e sem reinicialização.
- **SteamSkinManager** (`cartridges/integrations/steam_skin/`) — instala,
  sincroniza, repara e remove a skin da Steam, adaptando os recursos do
  [Adwaita-for-Steam](https://github.com/tkashkin/Adwaita-for-Steam).

O **perfil compartilhado** (`ThemeManager.perfil_compatilhado()`) é a única
fonte de verdade para os dois:

```python
{
    "theme_slug": "catppuccin-mocha",   # slug do catálogo
    "accent": "#c6d0f5",                 # destaque efetivo (custom se válido)
    "accent_custom": "",                 # hex custom ou vazio
    "mode": "dark",                      # light | dark | auto
    "glows": False,                      # glows RGB (só no tema jolven)
}
```

## ThemeManager (Jolven)

- `cartridges/themes/palette.py` — dataclass frozen `Palette` (slug, name,
  is_dark_only, bg, headerbar_bg, accent_bg, accent_fg, supplementary),
  `validar_hex()` e `load_palette_from_css()` (extrai apenas valores de cor de
  um `.css`, sem carregar CSS da Steam no GTK).
- `cartridges/themes/catalog.py` — `CATALOGO: dict[str, Palette]` com 24 temas
  (23 do upstream + `jolven`). API: `carregar_catalogo()`, `obter_tema(slug)`,
  `tema_padrao()`, `slug_é_dark_only(slug)`, `nome_do_tema(slug)`,
  `DEFAULT_SLUG == "jolven"`.
- `cartridges/themes/palette.py` (continuação) — `Palette.gtk_variables(modo)`
  monta, sem tocar em GTK, as **35 variáveis de cor do libadwaita 1.9.4**
  (`--window-bg-color`, `--view-bg-color`, `--dialog-bg-color`,
  `--headerbar-bg-color`, `--sidebar-bg-color`, `--card-bg-color`,
  `--popover-bg-color`, `--accent-bg-color`, `--accent-fg-color`,
  `--border-color`, `--shade-color`, fundos *backdrop* e variantes
  escurecidas). Os `*-fg-color` são calculados por luminância (nunca se confia
  no `fg` do modo) e as **cores semânticas** (`--destructive-*`, `--success-*`,
  `--warning-*`, `--error-*`) **nunca** são emitidas — o libadwaita segue
  dono delas.
- `cartridges/themes/gtk_engine.py` — `aplicar(slug, modo, glows=False,
  acento_custom=None)` e `remover()`. Instala um `Gtk.CssProvider` dedicado com
  prioridade `STYLE_PROVIDER_PRIORITY_USER` (vence o `style.css` do app) e
  reescreve `:root { … }` com `gtk_variables()`; o modo `auto` resolve pelo
  `Adw.StyleManager`. **`--accent-color` não é emitido**: a libadwaita o deriva
  de `--accent-bg-color`, então o contorno de foco, `-gtk-icon-palette: accent`
  e `needs-attention` acompanham o tema com contraste correto em claro e escuro.
  A aplicação é idempotente (cache da última assinatura) e a troca é ao vivo,
  sem reiniciar o app.
- `cartridges/themes/manager.py` — `ThemeManager` (GObject) com os sinais
  `theme-changed (str, str, bool)`, `mode-changed (str)` e `glows-changed (bool)`;
  singleton via `ThemeManager.instance()`; `bind_to_schema(schema)` escuta
  `changed::theme-slug`, `changed::theme-mode` e `changed::steam-skin-enabled`;
  setters `set_palette`, `set_mode`, `set_glows`, `set_acento_custom`.
  A aplicação é coalescida (debounce) para evitar reescritas repetidas.

O `ThemeManager` é instanciado no startup, logo após `apply_windows_theme()`
(`cartridges/main.py`), e ligado ao `shared.schema`. Toda a aplicação é
envolta em `try/except`: uma falha de tema nunca impede o uso do Jolven.

## Tema padrão Jolven

O tema `jolven` é o padrão (`theme-slug` default) e preserva a identidade
roxa/lilás atual:

- Paleta em `data/themes/palettes/jolven.css`: `--accent-bg-color: #c9a7f5`
  (e `--accent-color: #813d9c`, que o catálogo lê como `accent_fg`). No GTK, o
  provider emite `--accent-bg-color`/`--accent-fg-color` e deixa a libadwaita
  derivar `--accent-color`.
- Glows RGB opcionais em `data/gtk/style.css` (classes `.jolven-glow-accent`,
  `.jolven-glow-card`, `.jolven-rgb-border`), usando `--accent-color` em
  `box-shadow`/`border`. Só valem no tema `jolven`.
- Os glows degradam com `@media (prefers-reduced-motion: reduce)` (sem
  animação) e `@media (prefers-contrast: more)` (reforço de contorno).
- Não alteram ícones nem a identidade visual do projeto e são seguros em
  layouts a partir de 360 px e na sessão Gamescope.

Os demais temas não herdam glows; o visual deles é definido só pela paleta.

## Catálogo de temas

Os 23 temas do upstream: `adwaita`, `adwaita-gray`, `breeze`, `canta`,
`catppuccin-frappe`, `catppuccin-latte`, `catppuccin-macchiato`,
`catppuccin-mocha`, `dracula`, `everforest`, `gruvbox`, `kate`, `metro`, `nord`,
`oled`, `one-dark`, `pop`, `rose-pine`, `tokyo-night`, `tomorrow-night`,
`vapor`, `vgui2`, `yaru` — mais `jolven`.

- Paletas GTK instaladas em `data/themes/palettes/<slug>.css` e empacotadas no
  GResource.
- Miniaturas em `data/themes/previews/<slug>.svg` (a de `jolven` mostra o glow
  lilás).
- Temas marcados `is_dark_only=True` (ex.: `oled`, `everforest`) não são
  forçados no modo claro; a UI esconde/esmaece conforme o modo.

## Integração com a Steam

Módulos em `cartridges/integrations/steam_skin/`:

- `detector.py` — detecta instalações nativa (`~/.steam/steam`), Flatpak
  (`~/.var/app/com.valvesoftware.Steam/.steam/steam`), Snap
  (`~/snap/steam/common/.steam/steam`) e caminho custom (GSettings
  `steam-install-path`, com fallback em `steam-location`). Valida pela presença
  de `steamui/css/` + arquivos esperados. Múltiplas instalações são permitidas e
  a UI deixa escolher. O caminho da biblioteca de jogos nunca é tratado como o
  caminho dos recursos de interface.
- `installer.py` — `instalar(steam_path, tema_slug, accent, mode,
  opcoes_avancadas=None)`, `restaurar()`, `esta_instalada()`,
  `totalmente_instalada()`, `info_do_patch()`. Copia a skin para
  `<steam>/steamui/adwaita/`, gera `config.css` e patcha
  `steamui/css/{library,gamerecording,gamenotes}.css` com o cabeçalho
  `/* Adwaita-for-Steam */`, guardando `*.original.css` na primeira aplicação.
  O patch faz *padding* até o tamanho exato do arquivo original (nunca maior).
  As escritas são atômicas (tmp + `os.replace`), com rollback e idempotência
  (uma segunda execução sem diferenças não reescreve nada).
- `recovery.py` — `Estado` (ver abaixo), `verificar_estado()`,
  `precisa_reparo()`, `reparar_se_seguro()`, `steam_em_execucao()`.
- `manager.py` — `SteamSkinManager` com `aplicar_perfil()`,
  `sincronizar_se_habilitado()`, `reparar(perfil)` (repara estados
  `INCOMPATIVEL`/`ATUALIZACAO_NECESSARIA` fora do fluxo de *toggle*),
  `desabilitar()`, `restaurar_original()`, `estado()`, `precisa_reiniciar()` e
  `opcoes_suportadas()` (conjunto das opções finas realmente aplicáveis, hoje as
  9: `fontes`, `extras` e `windowcontrols`, `window-controls-theme`,
  `window-controls-layout`, `rounded-corners`, `cursor-pointer`,
  `hide-whats-new`, `sidebar-hover`, `uncrop-covers`, `hide-qr`). Toda falha é
  contida com `try/except` + log; a integração nunca derruba o Jolven.

### Estados da interface

`NAO_ENCONTRADA`, `NAO_INSTALADA`, `SINCRONIZADA`, `ATUALIZACAO_NECESSARIA`,
`AGUARDANDO_REINICIO`, `INCOMPATIVEL`, `PERMISSAO`, `CONFLITO_TERCEIROS`.

### Sincronização

Quando **Aplicar skin à Steam** está habilitado (`steam-skin-enabled`,
**default false**), mudanças de tema, destaque ou modo geram a atualização
correspondente na Steam. O manager usa *debounce*, compara a assinatura do
perfil antes de gravar (evita gravações desnecessárias) e registra a última
configuração aplicada. A assinatura inclui `theme_slug`, `accent` e
`accent_custom`, então **qualquer** mudança de destaque re-sincroniza — inclusive
voltar para **Padrão**, quando passa a valer o destaque do próprio tema. O Jolven
**não** inicia, fecha ou reinicia a Steam; apenas informa quando uma
reinicialização é necessária. Se a Steam não existir, estiver inacessível ou
falhar, o Jolven continua funcionando normalmente.

### Recuperação após atualização da Steam

Atualizações do cliente substituem os CSS internos e removem o cabeçalho do
patch. O recovery então reporta `ATUALIZACAO_NECESSARIA` e, se a recuperação
automática estiver habilitada, reaplica com segurança. Regras:

1. Identifica se a skin continua aplicada (cabeçalho do patch).
2. Diferencia instalação válida de arquivos modificados ou incompatíveis.
3. Nunca sobrescreve silenciosamente modificações desconhecidas de terceiros
   (`CONFLITO_TERCEIROS`).
4. Nunca usa um backup antigo para sobrescrever CSS atualizados sem verificar
   compatibilidade.
5. Se a Steam estiver em execução, adia operações inseguras e informa o usuário.
6. O processo é idempotente, com operações atômicas e rollback.

Não existe serviço permanente: a verificação roda na inicialização, ao abrir as
preferências e antes de sincronizar.

## Paridade Jolven ↔ Steam

O mesmo perfil alimenta os dois softwares. Trocar de tema, de destaque ou de
modo no Jolven reflete na Steam (quando habilitado), respeitando as limitações
de cada paleta.

O **destaque acompanha o tema** nos dois lados. No Jolven, `--accent-bg-color`
(botões *suggested*, switches, seleção) vem de `Palette.accent_bg`; na Steam, o
acento efetivo do perfil — `accent_custom` válido ou, quando vazio,
`Palette.accent_bg` resolvido por `ThemeManager.perfil_compatilhado()` — vira
`--adw-system-accent` no `config.css`. Todos os 24 temas definem um `accent_bg`
próprio (jolven `#c9a7f5`, dracula `#bd93f9`, oled `#ff6e4a`, nord `#88c0d0`),
então **trocar de tema troca o destaque nos dois softwares**; uma cor custom
sobrepõe a do tema em ambos.

**Importante:** os CSS da Steam **não** são carregados no GTK — os motores de
renderização são diferentes. O Jolven reutiliza apenas as *definições de cor*
(`palette.css` e `colorthemes/<slug>/<slug>.css`, que são blocos puros de
`:root { --adw-*: … }`) e as converte em variáveis GTK. O destaque lilás do tema
Jolven vira um destaque *purple* equivalente na skin da Steam.

## Vendor: Adwaita-for-Steam

Snapshot curado em `data/vendor/adwaita-for-steam/`, instalado em
`<pkgdatadir>/vendor/adwaita-for-steam/` e lido por
`cartridges/integrations/steam_skin/vendor.py`
(`extras_dir()`, `windowcontrols_dir()`, `fonts_dir()`, `list_fonts()`).

- Versão incorporada: **4.4** (commit `1e92107a51f6ed53c59c38646444c9eb3a52b030`).
- Licença: **MIT** (`LICENSE`, Copyright © 2022 Anatoliy Kashkin). As fontes
  vendoradas são **SIL OFL 1.1** e mantêm os respectivos `LICENSE.md`/`COPYING`.
- Inclui: `LICENSE`, `VERSION`, `palette.css`, `colorthemes/<slug>/<slug>.css`
  (23 temas), além de `extras/**`, `windowcontrols/**` e `fonts/**` — que dão
  efeito real às opções finas da skin (fontes, controles de janela, `extras`).
  O conteúdo é copiado byte a byte da tag upstream.
- Excluído de propósito: `adwaita/css/**` estrutural (~608 KB), previews PNG
  (~19 MB), `injectors/**`, `screenshots/**`, `scripts/**`, `install.py`,
  `skin.json`, `theme.json`. Motivos detalhados em
  `data/vendor/adwaita-for-steam/UPSTREAM.md`.

### Como atualizar o vendor

1. Escolha a tag alvo e resolva o SHA:
   `curl -sL https://api.github.com/repos/tkashkin/Adwaita-for-Steam/git/ref/tags/<tag>`.
2. Baixe o arquivo da tag:
   `curl -sL https://codeload.github.com/tkashkin/Adwaita-for-Steam/tar.gz/refs/tags/<tag> -o afs.tar.gz`.
3. Copie apenas os arquivos vendorados, preservando o layout plano.
4. Confirme o tamanho: `du -sb data/vendor/adwaita-for-steam`.
5. Atualize a tabela em `UPSTREAM.md` (tag, SHA, data) e, se necessário,
   `_ADW_VERSION_FALLBACK` em `constants.py`.

A atualização do vendor acompanha as releases do Jolven. **Não** há download ou
execução de código remoto em tempo de execução.

## Limitações conhecidas

- **Flatpak:** o Jolven empacotado como Flatpak não consegue escrever no Steam
  flatpak (`~/.var/app/...` somente leitura no sandbox). O detector retorna
  `accessible=False` e o recovery reporta `PERMISSAO`; os arquivos esperados não
  são alterados. O manifest não requisita filesystem indiscriminado.
- **Snap:** suporte best-effort, dependente da disposição dos diretórios.
- **Opções avançadas:** a árvore vendorada inclui `fonts/`, `extras/` e
  `windowcontrols/`, então fontes, controles de janela e `extras` têm efeito. As
  opções efetivas vêm de `SteamSkinManager.opcoes_suportadas()`; quando não há
  gerenciador, a UI cai na lista estática e nunca promete o que não funciona.
- **Windows:** a interface de detecção é reutilizável, mas o suporte a
  instalações Windows ainda não está concluído; o funcionamento no Linux não
  depende disso.
- **Páginas Store/Community/Profile** da Steam não são personalizadas por este
  método; o Jolven não promete isso.

## Interface (página Aparência)

- A **galeria de temas** fica no topo da página (`tema_group`), antes do grupo
  de aparência (`appearance_group`) e do grupo da Steam (`steam_group`). É um
  `FlowBox` `homogeneous` (3 a 6 miniaturas por linha) dentro de um
  `ScrolledWindow` com `height-request: 520`; o scroll interno rola quando há
  mais temas que o espaço visível e a altura fixa evita o colapso do clamp
  interno do `AdwPreferencesPage` (sem ela, a grade recebia só ~58 px).
- As miniaturas são geradas em código (`_criar_miniatura` / `_figura_do_tema`),
  com área de desenho `188×118` e legenda; a miniatura desenha o fundo e o
  destaque da paleta do tema.
- A janela de Preferências tem `content-width: 920`. Como cada
  `AdwPreferencesPage` embute um `AdwClamp` com `maximum_size = 600` que **não**
  é exposto ao CSS (e o GTK não suporta media query por largura),
  `CartridgesPreferences._alargar_paginas()` eleva esse teto para `856` no
  sinal `map` do diálogo, para o conteúdo acompanhar a largura da janela. O
  `AdwClamp` continua encolhendo em janelas estreitas — o valor é um teto, não
  um piso — então o layout permanece íntegro a partir de 360 px.

## Uso

1. Abra **Preferências → Aparência**.
2. Escolha um tema na galeria, o modo (Claro/Escuro/Automático) e o destaque
   (pré-definido ou custom). A prévia é ao vivo.
3. Opcionalmente habilite **Aplicar skin à Steam** (desabilitado por padrão).
   Escolha a instalação, se houver mais de uma.
4. **Aplicar agora** força a sincronização; **Reparar após atualização**
   reaplica depois de uma atualização da Steam; **Restaurar aparência original
   da Steam** desfaz a skin.
5. Desabilitar o toggle interrompe a sincronização **sem** remover a skin já
   instalada.

## Testes

- `tests/test_theme_catalog.py`, `tests/test_theme_persist.py`,
  `tests/test_theme_gtk_variables.py`, `tests/test_steam_detect.py`,
  `tests/test_steam_install.py`, `tests/test_steam_estados.py` e
  `tests/test_steam_opcoes.py` cobrem catálogo, persistência, as variáveis GTK do
  libadwaita (35 por tema × modo, sem cores semânticas, contraste legível), os
  rótulos de estado, as opções suportadas, detecção, instalação, idempotência,
  backup, restauração, reparo, conflito de terceiros e falhas de escrita —
  sempre em diretórios temporários, nunca sobre a Steam real.
- Rodam junto da suíte padrão (`unittest discover` via `meson test`).
