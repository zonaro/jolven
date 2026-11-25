# Dependências do GNOME no Jolven (issue #167)

Auditoria e plano para tornar o Jolven menos dependente do ecossistema GNOME,
mais independente e mais compatível com várias distribuições Linux. Este
documento registra fatos verificáveis no código; o objetivo não é remover o
GTK (escolhido) mas eliminar acoplamentos desnecessários.

## Objetivo do issue

> analisar todas as dependências que fazem parte do ambiente GNOME e procurar
> alternativas para elas, dependendo cada vez menos do GNOME e tornando o
> Jolven mais agnóstico.

## Veredicto em uma frase

O Jolven é GTK 4 + libadwaita (o stack do GNOME para aplicativos), com
persistência em GSettings e algumas integrações GNOME-específicas, mas a
maioria das dependências "de sistema" (logind, WirePlumber, PipeWire, polkit,
GameMode, Gamescope, PipeWire, D-Bus/freedesktop) não é GNOME e permanece
válida em qualquer distro e no KDE/Xfce/etc.

## Inventário por camada

### 1. Toolkit e UI (fundamento do app; biblioteca independente do desktop)

| Dependência | Onde | Criticidade |
| --- | --- | --- |
| GTK 4 ≥ 4.15 | `meson.build` (`dependency('gtk4')`), 32+ arquivos | Altíssima — é o toolkit |
| libadwaita ≥ 1.6 beta | `meson.build`, 28 arquivos importam `Adw` | Alta — widgets e tema de toda a UI |
| PyGObject (`gi`) | em todo o app | Altíssima |
| Blueprint Compiler | build-time apenas (`.blp` → `.ui`) | Baixa (só build) |
| Pango / Cairo / Graphene / Gsk / GdkPixbuf | via GTK 4 | Altíssima |
| GDK (`Gdk`) | janelas, GdkPixbuf, monitores | Altíssima |

GTK 4 roda em GNOME, KDE, Xfce, Sway etc. — não impede nenhuma distro.
libadwaita segue a mesma linha: biblioteca independente, empacotada por todas
as distros; a UI do Jolven usa widgets Adw (`ExpanderRow`, `SwitchRow`,
`HeaderBar`, `Toast` etc.) em todo o catálogo. Note que o libadwaita é parte
do próprio GTK e não exige que o ambiente seja o GNOME.

**Alternativa de saída**: GTK 4 puro + CSS próprio, ou Qt 6/PySide6. Ambos
exigem reescrever a UI inteira; não são passos, são outro projeto. Não estão
no escopo de #167 sem decisão explícita do mantenedor.

### 2. Persistência e configuração

| Dependência | Onde | Criticidade |
| --- | --- | --- |
| GSettings (`Gio.Settings`) — schema `io.github.zonaro.Jolven` | `shared.schema`, ~142 get e ~71 set no código | Média: é o mecanismo de preferências |
| `glib-compile-schemas` no install | `meson gnome.post_install`, `install.sh` | Baixa: ferramenta do GLib, padrão em toda distro |
| `gsettings` CLI | `session/jolven-session.in` (2 chamadas) | Baixa — já degrada para os padrões da sessão; decidido manter (ver fase 1) |
| Backend dconf | implícito quando o GLib roda sobre o GNOME | Baixa: o **keyfile backend** funciona em qualquer GLib e já é o caminho da porta Windows |

Pontos verificáveis:
- O Windows já usa o backend keyfile (`%APPDATA%\glib-2.0\settings\`), ver
  `.agents/compatibility.md` ("GSettings usa o backend keyfile, não dconf").
- Nada no app depende de `dconf` diretamente; `gsettings` CLI só existia no
  script da sessão.
- O backend padrão pode ser forçado com `GSETTINGS_BACKEND=keyfile` em
  qualquer distro, sem mudança de código.
- **Alternativa de saída** (grande): camada de settings própria com
  migração GSettings → JSON/TOML. Alta complexidade (213 pontos de acesso,
  binding para `Adw`/`Gio.SettingsBind` na UI), sem ganho proporcional.
  Recomendado: manter GSettings; ele é GLib, não GNOME Shell.

### 3. Integrações desktop opcionais (todas degradam graciosamente)

| Capacidade | GNOME | Alternativa / estado |
| --- | --- | --- |
| Atalho global Super+G | `org.gnome.settings-daemon.plugins.media-keys` (dconf) | caminho KDE: `kwriteconfig6` com `X-KDE-Shortcuts` e ajuste em `kglobalshortcutsrc`, ativado via D-Bus `org.kde.KGlobalAccel`; outros ambientes: comando manual mostrado na UI |
| Wallpaper por monitor na sessão | `org.gnome.desktop.background` (GSettings) | só GNOME; no KDE deveria ler/escrever `plasmashell` via `kreadconfig6` (Plasma 6) ou D-Bus `org.kde.plasmashell` |
| Provedor de busca do Shell | D-Bus `org.gnome.Shell.SearchProvider2` | GNOME Shell apenas; já não faz nada em outros desktops |
| Accent da skin da Steam | `org.gnome.desktop.interface` com fallback `org.freedesktop.appearance` | ✅ fallback freedesktop já implementado |
| Sessão Jolven | Gamescope + display manager | não é GNOME; requer Gamescope e, no Linux, integração com o display manager (ver `.agents/compatibility.md`) |
| Tema claro/escuro e accent | `org.gnome.desktop.interface` | leitura com fallback (`org.freedesktop.appearance`) |

### 4. Empacotamento e runtime

| Dependência | Onde | Criticidade |
| --- | --- | --- |
| Flatpak `org.gnome.Platform` 49 | `build-aux/flatpak/*.json` | Média |
| `install.sh` — pacotes só via `dnf` (Fedora) | `install.sh` (runtime + devel) | Média: compatibilidade de instalação com outras distros |
| `adwaita-icon-theme` | `install.sh` | Baixa |
| `gtk_update_icon_cache`, `update_desktop_database` | `meson gnome.post_install` | Baixa (GLib/GTK) |
| Ícones simbólicos próprios no GResource | `data/icons/` | ✅ empacotados — não dependem do Adwaita (mas nomes `folder-symbolic` vêm do tema do sistema) |

### 5. O que **não** é GNOME

- systemd-logind (`org.freedesktop.login1`) — `cartridges/power.py`.
- polkit (autorização das Preferências e helpers) — usada pelo Jolven Session
  e pelo helper privilegiado; no Windows é substituída por Hello.
- WirePlumber/PipeWire (`wpctl`) — controle de áudio da sessão.
- Gamemode, MangoHud, gamescope, Steamworks CLI, TDLib, TinyTuya, requests,
  Pillow, PyYAML, Feedparser — externos.
- D-Bus em si (`org.freedesktop.*`) — freedesktop, não GNOME.

## Classificação de risco e plano em fases

### Fase 1 — imediato, sem mudança de comportamento
- [x] Avaliado: o `gsettings` CLI em `session/jolven-session.in` **degrada
  graciosamente** (exit 1, sem abortar) quando o schema não está instalado; um
  substituto em Python com `Gio.Settings.new` abortaria o processo
  (GLib-GIO-ERROR) em instalações quebradas. Decisão: **manter o CLI**, que
  é GLib (não GNOME Shell) e já cai para os padrões da sessão.
- [ ] Documentar que o backend keyfile é aceito e testado no Windows
  (`.agents/compatibility.md` já registra) — nada a mudar.

### Fase 2 — baixo risco, issue próprio
- [ ] Flatpak: avaliar `org.freedesktop.Platform` + módulos `gtk4` e
  `libadwaita`; justificar manter o GNOME Platform caso a reprodução fique
  pior do que hoje. O manifesto é a referência reprodutível de runtime.
- [ ] `install.sh`: decidir com o mantenedor entre (a) manter Fedora-only
  (política atual — ver `.agents/compatibility.md`) ou (b) acrescentar
  `pacman`/`apt`/`zypper` para as bibliotecas de runtime, mantendo o helper
  privilegiado e a sessão Fedora-only.
- [ ] Ícones: mapear todo nome de ícone simbólico usado na UI que hoje vem do
  Adwaita (`folder-symbolic` etc.) e empacotar fallback no GResource, ou
  documentar o Adwaita como dependência de runtime (não como GNOME, como
  "tema de ícones padrão livredesktop/hicolor-compatível").
- [ ] Provedor de busca: manter opcional; garantir que o pacote só o instala
  com GNOME Shell detectado.

### Fase 3 — médio risco, issues próprios
- [ ] Backend KDE para `session_wallpaper` (Plasma 6 via `kreadconfig6`/
  D-Bus `org.kde.plasmashell`; Plasma 5 análogo) — hoje a função só opera em
  GNOME e lê o estado principal de monitores de lá.
- [ ] Backend KDE para `global_shortcut`: já existe; falta cobrir o caminho
  inverso (remoção completa) e documentar os dois fluxos no issue.
- [ ] Avaliar `adwaita-icon-theme` no `install.sh`: o GNOME 50+ migrou
  ícones simbólicos para o GResource do app em vários softwares; documentar
  o requisito mínimo de ícones.

### Fase 4 — grande, épico separado (não iniciar sem issue próprio)
- [ ] libadwaita → GTK 4 puro + CSS com fallback de aparência (ver seção 1).
- [ ] Camada de persistência própria (GSettings → TOML/JSON) com migração
  única e drop-in. Reutilizada pela porta Windows, que já usa keyfile.

## Fora de escopo de #167

- Remover GTK 4/PyGObject/libadwaita (decisão de produto, não de bugfix);
- Portar para KDE/Plasma como plataforma primária;
- Windows/macOS — o port é governado pelo épico #26–#31 (ver
  `.agents/compatibility.md`).

## Aceite do issue

Cada item das fases 2–4 só será fechado com um sub-issue próprio,
implementação e validação correspondentes — #167 registra a direção, não
autoriza remoções sem migração.
