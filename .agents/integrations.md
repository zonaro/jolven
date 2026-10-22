# Serviços e integrações

## Política geral

Integrações externas enriquecem a biblioteca, mas não são autoridade sobre os
dados locais. Todas devem seguir estas regras:

- rede fora da thread GTK;
- HTTPS, timeout, limite de resposta e parsing defensivo;
- cache local utilizável durante indisponibilidade quando fizer sentido;
- erro isolado, mensagem amigável e nenhuma falha na inicialização;
- autenticação opcional e armazenamento apropriado à sensibilidade;
- nenhum token, segredo, chave local ou URL autenticada em logs;
- mocks nos testes, sem depender da rede pública;
- validação estrita antes de abrir URI ou executar conteúdo retornado.

## Metadados e arte

### Steam

O projeto consulta endpoints públicos da Steam Store para busca, dados e reviews.
Não há chave de usuário. Respeite o limitador persistente já existente e mantenha
resultados parciais: falha da Steam não pode apagar nome, capa ou metadados locais.

### SteamGridDB

A API v2 fornece capas e logos. A chave é informada pelo usuário e guardada em
GSettings. Não a inclua em logs, backups de diagnóstico ou mensagens de erro.
Trate ausência e erro de autenticação como recurso não configurado.

### TheGamesDB

A API v1 fornece metadados, screenshots, fanart e fallback de capa. Usa chave do
usuário. Respostas incompletas e limites do serviço são normais; preserve dados
existentes e apresente erro de autenticação de forma acionável.

### IGDB / Twitch OAuth

IGDB v4 é usado em seletores de metadados e imagens, autenticado por Client ID e
Client Secret via Twitch OAuth. A implementação atual armazena essas preferências
em GSettings, não no Secret Service. Trate-as como segredo mesmo assim e, se o
armazenamento mudar, inclua migração sem expor valores.

### Wallhaven

Fornece wallpapers. A chave é opcional e necessária a determinados filtros de
pureza. Filtros e preferências ficam em GSettings. Downloads precisam verificar
tipo, tamanho e URL antes de substituir um wallpaper local.

### HowLongToBeat

A consulta usa o site público, sem API oficial ou chave. O formato pode mudar sem
aviso; parsing deve falhar de forma silenciosa/explicável, sem impedir a edição do
jogo. Não considere dados raspados estáveis para migrações ou identidade.

## xCloud e Better xCloud

O catálogo xCloud usa feeds públicos de catálogo/Game Pass e cria variantes
como gratuito, Game Pass e adquirido. O jogo abre em WebKit quando disponível;
sem WebKit, a biblioteca local continua operacional. O catálogo JSON é
persistido em cache versionado com TTL de 24 h (`xcloud_catalog.py`):
boot e habilitação instalam do cache e só buscam rede quando obsoleto ou via
botão Atualizar (forçado); sem rede e sem cache, o erro é reportado sem
derrubar a biblioteca. Rede e escrita de capas/JSON rodam fora da thread GTK;
a UI recebe resultados via `entregar_na_tela`.

Better xCloud é um userscript remoto obtido da versão mais recente no GitHub,
armazenado em cache e injetado na página. Isso é execução de código remoto e deve
ser tratado como uma fronteira de segurança:

- aceite apenas origens e domínios esperados;
- valide status, conteúdo e tamanho antes de gravar/injetar;
- mantenha cache conhecido para indisponibilidade;
- torne a funcionalidade lazy e opcional;
- não amplie a lista de URLs nem permissões WebKit por conveniência;
- mantenha navegação fora do domínio permitido bloqueada ou externalizada.

## Tuya / Smart Life

A integração de fitas usa `tinytuya`. Descoberta inicial pode consultar a nuvem;
o uso diário prefere controle local na LAN. Access ID, secret e região ficam no
Secret Service. Chaves locais por dispositivo ficam no arquivo de configuração
de fitas porque são necessárias ao controle LAN, mas continuam sendo segredos.

Credenciais de nuvem não entram no backup. Logs não podem conter payloads de
autenticação, chaves ou identificadores desnecessários. Ao aplicar iluminação de
sessão, registre estado suficiente para restaurar a condição anterior mesmo após
erro parcial.

## Feed de atualizações e notícias

Há consumo opcional de RSS do FitGirl para avisos de atualização por jogo e
notícias. A página Novidades agrega fontes em uma lista
(`cartridges/utils/news_feed.py:NEWS_FEEDS`): FitGirl, GamerPower
(`https://www.gamerpower.com/rss/giveaways`, agregado "all" — os sub-feeds
por plataforma/tipo sobrepõem-se a ele e não são consultados) e FreeToKeep
(`https://freetokeep.gg/feed.xml`, agregado geral — os feeds por loja
sobrepõem-se a ele; a API JSON segue fora de escopo). Cada post carrega o
rótulo da fonte, exibido no subtítulo da linha. O poll busca cada feed com
falha isolada (um feed fora não esvazia a página nem derruba os outros),
deduplica por guid/link entre feeds e ordena por pubDate.

Uma quarta fonte é restrita por idioma. O feed do TrinityWeb Games
(`https://games.thetrinityweb.com.br/feed.xml`) publica só em português,
então fica em `_PT_BR_FEEDS` (fora de `NEWS_FEEDS`) e só é consultado quando
`feeds_for_language` confirma interface pt-BR: preferência `language` do
GSettings igual a `pt_BR` ou `auto` com locale do sistema pt-BR, seguindo a
precedência do gettext (LANGUAGE, LC_ALL, LC_MESSAGES, LANG) e o mesmo padrão
de `jolven.in`. Em qualquer outro idioma a fonte não é consultada nem exibida.
`news_checker.py:_ui_language` lê o idioma na thread principal e o repassa ao
worker. Por ser conteúdo remoto não confiável e potencialmente sensível a
políticas locais:

- mantenha o acompanhamento opt-in por jogo;
- aceite apenas HTTPS e URLs seguras;
- use parser sem DTD/entidades externas e imponha limites;
- trate título, descrição e links como texto não confiável;
- não faça download de conteúdo ou executáveis a partir do feed;
- falha do feed nunca deve interferir no lançamento de jogos.

## GitHub

GitHub Releases e conteúdo raw são usados na distribuição do aplicativo e na
obtenção do Better xCloud. Fixe repositório/origem esperados, siga redirects com
limite e diferencie “versão não encontrada” de falha de rede. Publicação de
release é responsabilidade dos workflows e scripts do repositório, não de código
executado durante a inicialização do aplicativo.

## Launchers e protocolos

Importadores e launchers integram Steam, Lutris, Heroic, Bottles, itch,
Legendary, RetroArch, Dolphin, Cemu, Yuzu, Eden, UZDoom, TwinTail, Quiver,
Waydroid, Flatpak e arquivos `.desktop`. Valores vindos dessas fontes são não
confiáveis.

- Preserve argumentos como lista sempre que possível; evite `shell=True`.
- Valide esquemas de URI e IDs antes de compor protocolos.
- Não execute o campo genérico de um `.desktop` sem o parser/sanitização existente.
- Resolva instalações nativas e Flatpak pelos helpers de `Locations`.
- Ausência de launcher significa “fonte indisponível”, não biblioteca corrompida.

### Eden

Fonte local, sem rede e sem segredos. O importador lê o `qt-config.ini` do
Eden (mesmo formato do yuzu) em `~/.var/app/dev.eden_emu.eden/config/eden/`
(Flatpak) ou `~/.config/eden/` (nativo) e obtém os diretórios de jogos em
`[UI]`, chaves `Paths\gamedirs\{i}\path` e `Paths\gamedirs\{i}\deep_scan`.
Os jogos são lançados com `eden -f <rom>` ou
`flatpak run dev.eden_emu.eden -f <rom>`. Nada é gravado no diretório do
emulador.

### UZDoom

Fonte local, opt-in, sem rede e sem segredos. O importador lista os jogos de
uma pasta de WADs e usa uma pasta de mods, ambas detectadas na configuração do
próprio UZDoom (`uzdoom.ini`) e sobrescritíveis pelo usuário nas Preferências
(chaves `uzdoom-location` e `uzdoom-mods-location` do GSettings). Enquanto a
chave `uzdoom` estiver desligada ou a pasta de WADs não estiver configurada
(nem detectada, nem removida), a localização é irresolvível e o importador
apenas pula a fonte, sem podar os jogos já importados.

A detecção é feita por `cartridges/importer/uzdoom_config.py`, que lê os
arquivos de configuração em ordem de prioridade
(`$XDG_CONFIG_HOME/uzdoom/uzdoom.ini`, `~/.config/uzdoom/uzdoom.ini`,
`~/.config/uzdoom.ini` e o do Flatpak
`~/.var/app/org.zdoom.UZDoom/config/uzdoom/uzdoom.ini`) e usa a seção
`[IWADSearch.Directories]` para os WADs e `[FileSearch.Directories]` para os
mods: o UZDoom não tem uma pasta de mods separada, um mod é um arquivo que o
motor encontra nas pastas que procura. As pastas que o próprio motor adiciona
(`/usr/share`, `/app/share` e equivalentes) são descartadas, porque não são
uma escolha do usuário. O arquivo nunca é escrito.

Como a resolução de uma localização grava o valor encontrado no GSettings, a
primeira resolução persiste a pasta detectada. O valor escolhido pelo usuário
sempre vence a detecção, e uma mudança no `uzdoom.ini` só volta a valer depois
que a chave do GSettings for limpa. A pasta de mods é opcional para a
importação: sem ela os jogos da pasta de WADs continuam sendo importados, e as
Preferências mostram o aviso da linha.

O conteúdo do UZDoom são arquivos WAD, differentiate pelo cabeçalho mágico de
4 bytes: `IWAD` é um jogo base (Doom, Doom II, …) e `PWAD` é um mod que
precisa de outro IWAD para rodar. Apenas os IWADs viram jogos; os PWADs são
ignorados em silêncio, sem virarem entradas na biblioteca. O nome e o id do
jogo vêm do nome do arquivo sem extensão, o que dá um id estável no formato
`uzdoom_<nome>`.

O executável é detectado uma única vez por instância da fonte, porque a
importação percorre muitos jogos: o binário nativo `uzdoom` tem prioridade,
o Flatpak `org.zdoom.UZDoom` é usado quando o binário não existe e a forma
nativa é mantida como melhor esforço quando nenhum dos dois é encontrado. A
detecção é local (sem rede e sem segredos) e o jogo é aberto com
`uzdoom -iwad <arquivo>`.

Cada jogo pode ter uma lista ordenada de mods, `uzdoom_mods`, persistida pelo
Jolven e aplicada no lançamento pela opção `-file`
(`cartridges/game_launch.py:append_uzdoom_mods`, que cita cada caminho e
preserva a ordem da lista). A lista é editada no diálogo
`cartridges/uzdoom_mods_dialog.py`: a pasta de mods e a pasta de WADs são
varridas em união (sem repetir o mesmo arquivo), a ordem dos mods é a ordem de
aplicação e os argumentos gerados entram depois do `-iwad`.

### Quiver

Fonte local, com enriquecimento opcional pela API pública do catálogo do
Quiver Launcher (`https://api.quiverlauncher.com/api/v1`): somente `GET`,
sem autenticação e sem credencial. O importador lê o `apps.json` do Quiver e
o `cartridges/utils/quiver_catalog.py` busca no catálogo a capa, a
descrição, a versão, a desenvolvedora e as tags de cada app. A consulta
acontece no worker do importador, nunca na thread GTK.

- Só há consulta quando a entrada tem identidade (`catalogEntryId`,
  `repository` ou `name`); uma entrada sem nenhum deles não gera requisição.
- A identidade é resolvida em ordem: `GET /apps/{catalogEntryId}`; se o
  catálogo não tem esse app, `GET /apps?search=…` com o repositório e, por
  fim, com o nome. Um candidato só é aceito quando casa exatamente com o
  repositório ou com o nome da entrada e é o único assim — nunca "o primeiro
  resultado". Sem casamento único, não há enriquecimento.
- Timeout de 10 s e teto de 2 MiB por resposta, lidos em stream pelo
  `get_capped` das outras integrações.
- Resposta JSON inválida, corpo grande demais ou erro de rede não são
  fatais: a cadeia é rede → cache velho → sem enriquecimento. O app entra
  na biblioteca do mesmo jeito, só sem os metadados do catálogo.
- Cache versionado em `<cache_dir>/jolven/quiver_catalog.json`, TTL de 24 h,
  no mesmo formato do `xcloud_catalog.py`.
- O base pode ser trocado pela variável `QUIVER_API`; quando o domínio
  próprio falha na conexão, o host da implantação
  (`famous-wildebeest-660.convex.site`) é tentado em seguida, como no
  upstream.
- Privacidade: a única coisa enviada é o termo de busca — o nome do app ou o
  repositório, que já estão no `apps.json` do próprio usuário. Nenhum dado do
  usuário, identificador de máquina ou credencial é transmitido, e a API é
  pública: não existe autenticação para guardar.

Os dados do catálogo são consumidos sob a licença MIT do Quiver Launcher, e
o conteúdo publicado nele é responsabilidade de quem o publica. A
`TRADEMARKS.md` do upstream permite dizer que o Jolven é compatível com o
Quiver Launcher; ela não permite usar "Quiver" no nome do Jolven nem
reaproveitar o logotipo ou os ícones do Quiver. Na marca do Jolven, o nome e
o logotipo do Quiver aparecem no máximo como o identificador da fonte e o
ícone que apontam para o launcher importado.

### Cemu

Importação de jogos do Cemu (Wii U) lendo o `settings.xml` local via
`cartridges/utils/cemu_config_reader.py` (stdlib puro, sem GTK) e
produzindo jogos pelo `CemuSource`. Candidatos de config: Flatpak
`~/.var/app/info.cemu.Cemu/config/Cemu`, `XDG_CONFIG_HOME/Cemu` e o
`host_config_dir`; a escolha fica em `cemu-location`. A fonte dos jogos é
o `<GameCache>` persistente do Cemu (cada `<Entry>` traz `title_id`,
`name`, `custom_name` e o path do RPX/arquivo de disco); o `<GamePaths>`
(a lista de varredura configurada no Cemu) não é necessária aqui.

- Só jogos base entram na biblioteca (`title_id` iniciado em `00050000`);
  DLC (`0005000c`), updates (`0005000e`) e títulos de sistema ficam de
  fora. O cache é persistente e pode ficar obsoleto: entradas cujo path
  não existe mais são ignoradas.
- O nome exibido prefere `custom_name`, depois `name`, depois o stem do
  arquivo; o ID estável é `cemu_<title_id>`.
- Lançamento: `Cemu -f -g <path>` nativo ou
  `flatpak run info.cemu.Cemu -f -g <path>` (flag `-f` de fullscreen).
- Sem rede, sem segredos e sem escrita: o `settings.xml` é apenas lido;
  falha de leitura/parse vira fonte vazia, nunca bloqueia a biblioteca.

### Sunshine

Exportação opcional de jogos para o Sunshine (`lizardbyte/sunshine`),
inspirada no LutrisToSunshine, por escrita direta no `apps.json`
(`~/.config/sunshine/apps.json`, com override em
`sunshine-apps-path`). O payload segue os mesmos campos
(`name`, `cmd`, `working-dir`, `image-path`, `auto-detach`,
`exit-timeout`…); o `cmd` reaproveita o executável do jogo com o prefixo
`env` de `run_executable.py` e a capa local quando existir.

- Opt-in duplo: ação “Add to Sunshine” no menu do jogo e toggle
  `sunshine-auto-sync` (desligado por padrão) via `SunshineManager`
  (pós-`FileManager`, sinal `save-ready`).
- Upsert atômico por nome exato, preservando entradas alheias e a chave
  `env`; JSON inválido nunca é sobrescrito.
- Xbox Cloud Gaming (`base_source == xcloud`), jogos removidos e jogos
  sem executável são sempre ignorados.
- Sem rede, sem auth e sem segredos: falha é não fatal (toast/log) e
  nunca impede o uso da biblioteca local.
- A página Sunshine nas Preferências (item Sunshine no menu do
  aplicativo) centraliza exportação e diagnóstico: além do grupo de
  exportação, há conexão com a Web UI local (`sunshine-host`,
  `sunshine-port`, `sunshine-username` em GSettings; a senha mora no
  Secret Service por `cartridges/utils/sunshine_credenciais.py`, nunca
  em GSettings e nunca em log), teste que exibe versão e
  quantidade de apps via `GET /api/apps` + `GET /api/config` com Basic
  auth e sem header `Origin` (isento de CSRF),   lista somente-leitura
  dos apps e abertura da Web UI. `POST /api/config`, PIN e clientes
  ficam para uma v2 (config exige GET→merge→POST completo + restart;
  índice de app é racy pois a lista reordena por nome).

### Sunshine v2 (config do host, apps, PIN, clientes)

A v2 completa a tela com escrita remota, sempre com Basic auth e
timeout. `cartridges/utils/sunshine_api.py` continua sem persistir nada:
as credenciais só passam por ele em memória, chegam do cofre pela tela e
nunca aparecem nos testes (sem rede):

- Host: leitura via `GET /api/config` preenche as linhas; Aplicar faz
  GET→merge→`POST /api/config` (o Sunshine substitui o arquivo inteiro)
  e oferece `POST /api/restart` em diálogo separado. Chaves curadas:
  `max_bitrate`, `minimum_fps_target`, `upnp`, `origin_web_ui_allowed`,
  `encoder`.
- Apps: excluir resolve o índice por nome na hora (`DELETE
  /api/apps/{index}`, com confirmação); exportar via API cria com
  `index:-1` e sobe a capa local em base64 (`POST /api/covers/upload`
  devolve `path`, usado como `image-path`).
- Pareamentos: `GET /api/pin` lista pendentes; aprovar pede o PIN do
  Moonlight em diálogo (`POST /api/pin` com `pairing_id`, `pin`,
  `name`); recusar usa `DELETE /api/pin`.
- Clientes: `GET /api/clients/list`, desemparelhar um (`POST
  /api/clients/unpair` com `uuid`) ou todos (com confirmação).

### Instalação do Sunshine pelo Jolven

O item Sunshine no menu do aplicativo funciona como porta de entrada:
se `sunshine` (nativo) ou o Flatpak `dev.lizardbyte.app.Sunshine`
existirem, abre a página de configurações; senão, um diálogo oferece
instalar via Flatpak user a partir do Flathub (sem sudo), com toast de
progresso e abertura da página ao concluir. O caminho padrão do
`apps.json` prefere o catálogo existente (nativo, depois Flatpak) e,
sem nenhum, segue o tipo de instalação detectado.
- A linha **Iniciar o Sunshine** (`is_running` via `pgrep -x` no
  nativo e `flatpak ps` no Flatpak) inicia o servidor destacado quando
  parado, avisa quando já roda e retesta a conexão em seguida.
- A linha **Iniciar o Sunshine automaticamente** habilita/desabilita o
  autostart da unidade de usuário do Sunshine (`systemctl --user
  enable/disable`, sem root e sem polkit) por
  `cartridges/utils/sunshine_servico.py`. O nome da unidade é detectado
  (AppId do LizardByte ou `sunshine.service`); o estado exibido vem do
  systemd, nunca do GSettings, e é lido fora da thread GTK com entrega
  por `entregar_na_tela`. Sem Sunshine instalado a linha fica insensível.
- Flatpak: o Jolven confinado não enxerga o `~/.config` do host; nesse
  caso aponte `sunshine-apps-path` para um caminho acessível.

## Integrações do sistema

### Autenticação para abrir as Preferências

`cartridges/platform/authentication.py` é o portão que roda antes de construir o
diálogo, fora da thread GTK, com a entrega por
`utils.na_tela.entregar_na_tela` (chamado em
`CartridgesApplication.on_preferences_action`):

- Linux: action polkit `io.github.zonaro.Jolven.preferences`
  (`data/io.github.zonaro.Jolven.Preferences.policy.in`), verificada com
  `pkcheck --action-id … --process <pid>,<início>,<uid>
  --allow-user-interaction`. `auth_admin_keep` guarda a autorização por cerca de
  5 minutos, então aberturas seguidas não repetem a senha. Não há helper rodando
  como root nem comando arbitrário. O início do processo vem do campo 22 de
  `/proc/<pid>/stat`.
- Windows: Windows Hello por `UserConsentVerifier`, no pacote opcional
  `winrt-Windows.Security.Credentials.UI`, importado de forma lazy.
- `DENIED` — recusa, diálogo dispensado ou tempo esgotado — bloqueia a abertura
  com toast. `UNAVAILABLE` abre assim mesmo e registra aviso: o fail-open cobre
  apenas plataformas sem polkit (Windows/sem policy instalada; uma instalação
  Windows pode não ter o pacote ou o Hello configurado). Em instalações normais
  no Linux o `install.sh` instala a policy com sudo junto do Jolven, então o
  portão atua; se a integração de sistema faltar, o recurso fica indisponível
  com aviso de reinstalar o Jolven.
- O helper privilegiado é resolvido pelo `exec.path` da policy instalada, nunca
  pelo prefixo do app.
- O portão é higiene contra alteração casual por quem já está na sessão, não
  fronteira de segurança: o mesmo usuário consegue contorná-lo, e o app não
  decide autorização de sistema a partir dele.

### GPU Screen Recorder

O overlay de jogo da Jolven Session pode abrir uma instalação local do GPU
Screen Recorder. A integração procura primeiro o desktop app oficial, o que
inclui o pacote Flatpak, e só então os executáveis nativos conhecidos. Ela não
configura gravação, não acessa arquivos de vídeo, não usa rede nem armazena
credenciais. Ausência ou falha do aplicativo externo deve produzir apenas um
aviso recuperável e nunca encerrar o jogo ou a sessão.

| Sistema | Uso | Restrição |
| --- | --- | --- |
| systemd-logind | suspender/desligar/reiniciar | via D-Bus e autorização normal |
| Secret Service | credenciais Tuya e senha da Web UI do Sunshine | nunca fallback para log, backup ou arquivo público |
| xdg-desktop-portal/libei | emulação autorizada de entrada | sem acesso bruto a dispositivos |
| PipeWire/WirePlumber | volume e sink da sessão | restaurar estado ao sair |
| `/sys/class/drm` | detecção de monitor/VRR | somente leitura |
| polkit | instalar/remover sessão e abrir as Preferências | operações fixas, sem comando arbitrário |
| Windows Hello | abrir as Preferências (Windows) | pacote opcional; sem ele, abre com aviso |
| Gamescope | compositor da Jolven Session | não aninhar em sessão dedicada |
| GameMode/MangoHud | wrappers por jogo | opcionais e composicionalmente testados |
