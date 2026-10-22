# Compatibilidade e plataforma

## Escopo suportado

Jolven é um produto Linux. O aplicativo desktop se comporta em GNOME, KDE e
outros ambientes que ofereçam GTK/portais adequados. Integrações específicas do
desktop precisam detectar suporte e oferecer orientação manual quando
indisponíveis.

O Windows é um alvo em port, como aplicativo **standalone**: a mesma biblioteca
local, sem Jolven Session e sem Gamescope. A decisão é explícita e vive nas fases
do épico do port (fases #26–#31); a camada de plataforma reconhece o layout do
Windows por causa dela, não como promessa genérica de multiplataforma. Não amplie
essa camada além do que uma fase define.

macOS não é alvo, mesmo que helpers antigos reconheçam seu layout.

## Stack mínima

O build de fonte declara aproximadamente:

- Python 3;
- Meson 0.59 ou posterior;
- GTK 4.15 ou posterior;
- libadwaita 1.6 beta ou posterior;
- Blueprint Compiler;
- PyGObject e bibliotecas Python instaladas pelo projeto.

No Windows o build roda no toolchain **MSYS2 UCRT64**, com os pacotes
`mingw-w64-ucrt-x86_64-*` (`gtk4`, `libadwaita`, `python`, `python-gobject`,
`meson`, `ninja`, `binutils`) e `blueprint-compiler`. O job do CI usa o
`meson`/`ninja` do MinGW: o `meson` do MSYS2 recusa o Python do MinGW.

O manifesto Flatpak usa a plataforma GNOME 49 e é a referência mais reprodutível
do ambiente de runtime. Se a versão do manifesto divergir da CI ou dos requisitos
Meson, trate como dívida a ser resolvida, não como três fontes independentes de
verdade.

## Wayland, X11 e Gamescope

Wayland é o caminho primário. O Flatpak ainda expõe sockets Wayland e X11 para
compatibilidade com desktops e launchers. Jolven Session é baseada em Gamescope e
portanto tem requisitos mais estritos que o aplicativo desktop.

O instalador automatiza dependências e a integração com o display manager em
Fedora. Outras distribuições podem executar o desktop e, se fornecerem as
dependências, a sessão; não prometa instalação automática fora do que o helper
privilegiado realmente implementa.

Em sessão dedicada:

- não aninhe Gamescope ao lançar jogos;
- restaure áudio e estado alterado ao encerrar;
- preserve fallback de parâmetros de monitor/FPS;
- nunca execute a sessão como root;
- mantenha a instalação privilegiada pequena e auditável.

## Windows

O port é standalone: sem sessão dedicada, sem Wayland/X11 e sem Flatpak. O que já
é real na camada de plataforma (`cartridges/platform/`):

- Dados e configuração ficam em `%APPDATA%` (Roaming); cache e logs em
  `%LOCALAPPDATA%`. Os caminhos não vêm de `GLib.get_user_cache_dir()` porque no
  Windows ele resolve para `INetCache`, que a Limpeza de Disco/Storage Sense
  esvazia por padrão — o log de um crash seria apagado justamente ali. No Linux os
  caminhos XDG continuam idênticos.
- Instância única por **mutex nomeado**
  (`Local\io.github.zonaro.Jolven.SingleInstance`) e um evento `...Present`. O
  `GApplication` só garante unicidade pelo barramento de sessão do D-Bus, que o
  Windows não tem: o GLib tenta subir `gdbus.exe`, falha e o `GApplication` volta a
  se comportar como não-único — duas janelas gravando os mesmos arquivos de jogo.
  No Linux nada muda (os helpers seguem no-op).
- Tema e cor de realce lidos do registro (`...\Themes\Personalize\AppsUseLightTheme`
  e `...\DWM\AccentColor`) via `winreg`, com `RegNotifyChangeKeyValue` para
  acompanhar mudanças sem reiniciar.
- GSettings usa o backend **keyfile** (`%APPDATA%\glib-2.0\settings\keyfile`), não
  dconf. Os schemas são encontrados porque a árvore instalada mantém `bin/` e
  `share/glib-2.0/schemas` como irmãos, que é onde o GLib procura em relação à
  própria DLL — sem `GSETTINGS_SCHEMA_DIR` no app empacotado.

Ainda sem equivalente no Windows, conforme o épico do port:

- sem Jolven Session/Gamescope, sem integração de display manager e sem helper
  privilegiado por polkit;
- o portão das Preferências troca polkit por Windows Hello
  (`UserConsentVerifier`, no pacote opcional
  `winrt-Windows.Security.Credentials.UI`); sem o pacote, sem Hello configurado
  ou com Hello desabilitado por política, as Preferências abrem com aviso no
  log (fail-open restrito a plataformas sem polkit);
- gamepads por libmanette dão lugar a XInput (`ctypes`);
- xCloud embutido, GameMode, MangoHud, `wpctl`/WirePlumber e libei/snegg não têm
  equivalente direto;
- distribuição por MSYS2 UCRT64 + Inno Setup, com patch DComp no GTK (sem ele as
  janelas GTK no Windows podem não pintar fora do monitor principal).

## Dependências opcionais

| Capacidade | Dependência | Comportamento sem ela | Windows |
| --- | --- | --- | --- |
| xCloud embutido | WebKitGTK 6.0 ou 4.1 | recurso oculto/desabilitado com orientação | sem WebKitGTK; indisponível no port |
| gamepad | libmanette | teclado e mouse continuam funcionais | sem libmanette; XInput planejado |
| emulação de entrada | libei/snegg + portal | ação específica indisponível | sem equivalente |
| Jolven Session | Gamescope | desktop funciona; sessão não instala/inicia | fora do escopo (standalone) |
| perfil de desempenho | GameMode | jogo inicia sem wrapper | sem equivalente |
| overlay | MangoHud | jogo inicia sem overlay | sem equivalente |
| controle de áudio | `wpctl`/WirePlumber | não ajustar automaticamente | sem equivalente |
| luzes inteligentes | `tinytuya` e Secret Service | integração desabilitada | sem Secret Service; segredos por DPAPI (planejado) |
| autenticação das Preferências | polkit (`pkcheck`) / `winrt-Windows.Security.Credentials.UI` | integração de sistema (helpers + policies) vem instalada com o Jolven pelo `install.sh`; sem ela o recurso fica indisponível com aviso de reinstalar o Jolven (no Windows, abre sem exigir autenticação, com aviso no log) | pywinrt opcional, via CPython oficial (o do MSYS2 UCRT64 recusa os wheels `win_amd64`) |

Imports dessas capacidades devem ser lazy ou protegidos. Nunca transforme uma
dependência opcional em falha na importação global de `main.py`.

## Flatpak e host

O sandbox recebe permissões de rede, IPC, display, DRI e caminhos necessários
para descobrir launchers e bibliotecas. Antes de ampliar `--filesystem`, sockets
ou acesso a dispositivos, justifique o dado exato e procure um portal.

Um Flatpak não deve tentar gravar diretamente a configuração de sessão gráfica
do host. Integrações de host usam launchers, `flatpak-spawn` quando previsto, ou o
helper instalado fora do sandbox. Teste caminhos nativos e Flatpak separadamente.

## IDs, caminhos e legado

O perfil release usa `io.github.zonaro.Jolven`; desenvolvimento usa um ID com
sufixo `.Devel`. App ID, schema ID, nome de desktop file, D-Bus, prefixo de
GResource e diretórios instalados formam um contrato conjunto.

O projeto migrou de Cartridges para Jolven. Permanecem referências legadas em
variáveis, schemas e diretórios para encontrar dados de usuários existentes.
Regras:

- leia o nome antigo quando necessário;
- escreva no formato/local atual;
- copie antes de migrar e nunca apague automaticamente a fonte;
- torne a migração idempotente;
- não remova aliases apenas porque uma instalação nova não os usa.

## Formato de dados

Jogos têm `spec_version`; backups têm versão própria. A compatibilidade é
conservadora:

- campo novo recebe padrão seguro ao ler registro antigo;
- campo removido não deve destruir dados desconhecidos incidentalmente;
- versão futura é recusada/ignorada, não reinterpretada;
- mudanças incompatíveis exigem migração explícita, teste e documentação;
- arquivos externos e ZIPs passam por validação de caminho e tamanho.

## Desktop e atalhos

Atalhos globais têm backends específicos para GNOME/GSettings e KDE
KGlobalAccel. Em ambientes não reconhecidos, mostre instruções manuais em vez de
alterar arquivos arbitrários. Integração com systemd-logind para energia deve usar
D-Bus e respeitar autorização do sistema.

