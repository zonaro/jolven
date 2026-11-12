# Auditoria de independência do GNOME — Jolven (#167)

> **Estado:** diagnóstico de arquitetura e plano de implementação; nenhuma migração de código está incluída neste documento.  
> **Base inspecionada:** branch main em 12/11/2026 (repositório zonaro/jolven).  
> **Issue principal:** https://github.com/zonaro/jolven/issues/167  
> **Meta:** execução no desktop GNOME, KDE Plasma e outros desktops/WM compatíveis, além da Jolven Session dedicada, sem **exigir GNOME Shell, GNOME Settings Daemon ou GDM**. Preservar dados e UX atuais.

## 1. Decisão arquitetural

**Manter Python + GTK4 + libadwaita + GLib/GIO + Blueprint + GSettings.** Essas tecnologias podem ser usadas em desktops não GNOME. Migrar todo o frontend para Qt/Flutter **não é pré-requisito** para independência do GNOME: implicaria reescrever as telas Blueprint, foco via GTK, bindings, acessibilidade, recursos, temas e testes, com regressões graves e custo muito maior que isolar as integrações do sistema.

**Isolar ou remover acessos diretos às configurações e APIs próprias do GNOME**. Preferir freedesktop.org/XDG/portais quando implementarem a capacidade necessária; usar adaptadores específicos por ambiente somente como fallback e com detecção real de capacidade, não por presença de schema ou pacote. Não substituir uma biblioteca madura por código caseiro sem economia de complexidade ou teste de paridade.

**Jolven Session permanece baseada em Gamescope**, independente de GNOME Shell e KDE Plasma. Não implementar compositor/display manager próprio. Portabilidade da sessão depende de integração correta com login, bus de usuário, compositor, drivers, áudio e empacotamento.

**Prioridade recomendada:** P0 instalação/identificação do ambiente e isolamento de GNOME; P1 atalhos, wallpaper e portais; P2 testes de sessão nas distros/display managers; P3 otimizações de dependências e empacotamento.

## 2. Inventário — dependência real versus origem do projeto

| Componente | Implementação existente | Relação com GNOME | Decisão |
|---|---|---|---|
| Interface | cartridges/main.py, window.py, preferences.py, data/gtk/*.blp, meson.build | GTK4/libadwaita vêm do ecossistema GNOME, mas **não requerem GNOME Shell** | **Manter**; avaliar frontend alternativo só em épico separado |
| GLib/GIO, D-Bus e GSettings | cartridges/shared.py.in, schemas, main.py | APIs gerais, schema do **Jolven** é próprio | **Manter**; não migrar configurações para JSON indiscriminadamente |
| Meson gnome module / Blueprint | meson.build, data/meson.build, subprojects | Namespace de ferramentas de build, não dependência de sessão | **Manter** |
| Tema Adwaita / GNOME icons | cartridges/themes/, data/themes/, assets | Preferência estética ou recursos de UI; não exige GNOME desktop | **Manter** e oferecer temas atuais; pacote de ícones conforme distribuição |
| Wallpaper ao jogar | cartridges/utils/session_wallpaper.py | **Dependência real** de org.gnome.desktop.background | **Refatorar**; separar composição de imagens do backend que aplica/restaura |
| Atalho global Super+G | cartridges/utils/global_shortcut.py | **Dependência opcional** de org.gnome.settings-daemon.plugins.media-keys; já possui backend KDE | **Portal GlobalShortcuts primeiro**, backends GNOME/KDE como fallback |
| Pesquisa no overview | search-provider/* e search-provider/meson.build | **Específico do GNOME Shell SearchProvider2** | **Manter opcional**; não exigir/ativar fora do GNOME |
| Gamepad | import protegido de Manette em cartridges/main.py; controller.py e gamepad_visual.py | libmanette é desenvolvida no GNOME, mas é biblioteca GObject de gamepad **sem precisar do shell** | **Manter** como backend padrão; eventual SDL3 apenas com benchmark/paridade |
| Entrada emulada | cartridges/keyboard_emulator.py, snegg/libei, xdg-desktop-portal | **Freedesktop**, não GNOME; depende do compositor/portal | **Manter opcional**, com fallback não intrusivo |
| Teclado na tela | cartridges/onscreen_keyboard.py | **Já é implementação interna**, baseada em Gtk.Editable | **Manter**; não exigir teclado virtual do GNOME |
| Sessão dedicada | session/jolven-session.in, session/jolven-game-mode-setup.in, cartridges/game_session.py | Gamescope é independente; documentação/helpers assumem **GDM/Fedora** | **Generalizar** instalação e validar DMs; não trocar Gamescope |
| Instalador | install.sh; helper de sessão | **Bloqueio real por distro**, não pelo GNOME: ID=fedora, dnf, rpm | **Criar backend por gerenciador**, começando Arch/CachyOS e Fedora |
| Flatpak | build-aux/flatpak/io.github.zonaro.Jolven.Devel.json | org.gnome.Platform 49 é **runtime**, não requisito de sessão GNOME | **Manter por ora**; mudança para freedesktop exige bundle e teste de custo |
| Energia | cartridges/power.py | org.freedesktop.login1/systemd-logind, não GNOME | **Manter**; capability-check, compatível com implementações login1; nunca sudo direto |
| Áudio | cartridges/hardware.py, session/jolven-session.in | PipeWire + WirePlumber/wpctl, não GNOME | **Manter**, wpctl opcional, não abortar GUI por ausência |
| Autenticação / ações root | cartridges/platform/authentication.py, system_integration.py, *.policy.in | polkit, independente de GNOME; diálogo depende de agente ativo | **Manter** fail-closed; nunca helper root em home gravável |
| Credenciais | cartridges/utils/sunshine_credenciais.py, tuya_conta.py | libsecret / freedesktop Secret Service; **não é GNOME Keyring obrigatório** | **Manter** sem fallback plaintext; tratar ausência da biblioteca/serviço |
| Abertura de links/arquivos | cartridges/utils/open_uri.py, importadores | Gtk.UriLauncher/GIO/XDG | **Manter** |
| Notificações | cartridges/main.py / Gio.Notification | GApplication/GIO e integração do sistema | **Manter**; validar no desktop e na sessão independente |
| Gravação | cartridges/recorder/*, GPU Screen Recorder | Serviço externo opcional, portais/gráficos | **Manter opcional**; não desenvolver encoder próprio |
| Desempenho | GameMode, MangoHud, Gamescope, game_launch.py | Não GNOME | **Manter opcional** e nunca instalar só para iniciar a biblioteca |
| Sunshine/OpenRGB/Tuya | cartridges/integrations/, iluminacao/, utils/sunshine* | Integrações independentes do desktop | **Manter opcionais**; capacidades detectadas por serviço/binário |
| Android | android/jolven_flutter | Não depende de GNOME | **Fora do escopo**; manter contratos de biblioteca independentes |
| Windows | cartridges/platform/*, .agents/compatibility.md | Port standalone em andamento, sem sessão dedicada | **Não regredir**; mudanças devem preservar guardas de plataforma |

### Observações que merecem correção

1. **Wallpaper GNOME não é per-monitor na implementação atual.** Em session_wallpaper.py, o argumento monitor é ignorado por _Fundo.papel() e _Fundo.vestir(); todas as telas compartilham picture-uri. Com múltiplos alvos, a última escrita prevalece. A documentação atual sugere quadros individualizados, mas o backend não os aplica individualmente.
2. **Wallpaper claro/escuro pode ser perdido ao restaurar.** _Fundo.vestir() escreve picture-uri e picture-uri-dark, mas _Fundo.papel() salva apenas picture-uri, e restaurar() devolve esse único valor para os dois. Corrigir sem descartar o estado antigo persistido; testar dark/light, crash e rollback.
3. **Falta de monitor secundário muda a preferência do usuário.** comecar() faz set_boolean("session-wallpaper", False) em vez de apenas não executar temporariamente. Preservar preferência desativando a capacidade, não a escolha.
4. **Atalho detecta a presença, não necessariamente a sessão correta.** global_shortcut.py usa o schema GNOME ou os utilitários KDE como fallback mesmo se a sessão não for do respectivo DE. A associação de LXQt a KDE e Budgie/Cinnamon/Pantheon a GNOME não garante compatibilidade real com o backend selecionado.
5. **O provedor SearchProvider2 é inequivocamente GNOME.** Os arquivos search-provider/* e o caminho gnome-shell/search-providers não devem se tornar requisito do desktop genérico. Manter a funcionalidade específica apenas quando o GNOME oferece o consumidor.
6. **O instalador é mais restrito que o aplicativo.** install.sh aborta quando ID não é fedora; session/jolven-game-mode-setup.in só instala dependências automaticamente no Fedora. Portanto a principal barreira a CachyOS/Arch é empacotamento/instalação, não necessariamente a UI.
7. **GNOME Platform do Flatpak não implica GNOME instalado no host.** Não contabilizar esse runtime como dependência do GNOME Shell. Preferir menor custo real de manutenção a uma alteração cosmética do nome do runtime.
8. **Secret Service é protocolo; provedor é variável.** Testar em GNOME Keyring, provedores KDE compatíveis e sem cofre; tuya_conta.py tem import de Secret não suficientemente protegido e merece import opcional/lazy.
9. **Mensagens, documentos e categorias tratam GNOME como padrão.** README recomenda Fedora/GNOME; docs/game-mode-architecture.md chama a entrada de GDM; data/io.github.zonaro.Jolven.desktop.in inclui Categories=GNOME;GTK;Game. Atualizar o marketing/diagnóstico quando suporte multiplataforma for validado, não prometer antes.
10. **Um ambiente XDG_CURRENT_DESKTOP=Jolven não garante portals funcionais.** A sessão dedicada precisa descobrir/selecionar backends adequados e propagar WAYLAND_DISPLAY, XDG_CURRENT_DESKTOP e demais variáveis para ativação D-Bus quando aplicável.

## 3. Design de integração proposto (mínimo, sem overengineering)

Criar uma fronteira pequena e testável em cartridges/platform/, mantendo RuntimeContext como fonte da verdade para modo de execução:

- **capabilities.py**: um snapshot de capacidades disponível para UI/diagnóstico, com desktop detectado, tipo de sessão, D-Bus session/system, portal GlobalShortcuts, portal Wallpaper, Secret Service, login1, gamescope, wpctl, pkexec, agente polkit e gamepad. Uma capacidade pode ser available, unavailable, unsupported ou needs-permission. Não assumir suporte porque um pacote existe.
- **shortcuts.py**: registrar/remover/listar usando backend portal, GNOME, KDE ou manual; manter IDs semânticos estáveis e cleanup somente de atalhos gerenciados pelo Jolven.
- **wallpaper.py**: interface para capture_original(), apply(), restore(); implementação GNOME como fallback, backend portal quando aplicável, backend de desktop adicional apenas se testado; composição e cache continuam no atual session_wallpaper.py ou módulo utilitário extraído.
- **session.py** ou extensão segura de game_session.py: estado de instalação, DM/paths, preflight de portal/DBus/áudio/Gamescope. O helper privilegiado continua pequeno e com operações fixas.
- **packages.py** ou um pequeno helper Shell no install.sh: resolução de distro/família para nomes de pacotes e instalação com confirmação, sem comandos arbitrários montados por entrada externa.
- **secrets.py**, se necessário: encapsular libsecret preservando atributos/compatibilidade e diferenciando ausência do cofre, cofre bloqueado e segredo inexistente.

Preferir protocolos simples (tipagem/Protocol ou classes pequenas) e composição, **não um framework de plugins genérico**. Backend selection deve depender de capacidade medida, consentimento e ambiente ativo; cache com invalidação em mudança de sessão/serviço; erro não fatal para recursos opcionais. GNOME/KDE devem existir como adaptadores isolados, não condicionais dispersos por telas.

### Precedência sugerida por capacidade

**Atalhos globais:** xdg-desktop-portal GlobalShortcuts suportado e autorizado → integração GNOME se sessão GNOME verdadeira → KDE KGlobalAccel se sessão KDE verdadeira → instruções manuais. O portal trata ativação da ação durante a vida da sessão; garantir relançamento/autostart conforme necessário. Não simular atalho global por hooks de X11 em Wayland ou por /dev/input.

**Wallpaper:** preferência por renderização interna no Jolven quando a finalidade for **fundo da UI** (zero alteração no desktop). Para alterar o wallpaper real do usuário, utilizar Portal Wallpaper somente onde houver suporte/consentimento e onde for possível cumprir a garantia de restauração; ele **não expõe leitura de wallpaper atual nem seleção por monitor**. Implementar fallback GNOME preservando estado e, se houver justificativa, adaptador KDE específico. Se o objetivo exigir wallpaper por monitor, nenhum portal padrão resolve sozinho: definir decisão explícita sobre escopo, com opt-in e testes por compositor. Na Jolven Session, não assumir presença de GNOME Settings Daemon.

**Credenciais:** Secret Service com backend disponível → indisponível e pedir novamente; **nunca** texto claro, dconf, log ou token em argumento de CLI.

**Energia:** login1 e autorização padrão → desabilitar ação com explicação. Não criar mecanismo próprio privilegiado para suspender/reiniciar.

**Gamepad:** libmanette enquanto entregar hotplug, mapeamento e baixo custo; avaliação opcional de SDL3 em P3. Não usar leitura própria de /dev/input como solução fácil.

## 4. Recomendações por dependência: remover, manter ou internalizar

| Funcionalidade | Implementar nós mesmos? | Julgamento e risco |
|---|---|---|
| Fundo visual **da interface Jolven** | **Sim, já é parcialmente interno** | GTK/CSS/imagens; evita tocar no wallpaper externo |
| Converter/cortar/armazenar arte por jogo | **Sim, já existe** | Reaproveitar Pillow, cache e sidecars; desacoplar apenas aplicação externa |
| Trocar wallpaper do desktop | **Não como daemon proprietário genérico** | Portal/DE controlam wallpaper; restauração, monitores e permissão são difíceis |
| Teclado na tela | **Sim, já existe** | Manter o componente do Jolven, não exigir OSK do desktop |
| Atalho global Wayland | **Não interceptar diretamente** | Somente compositor/portal pode fazê-lo com segurança |
| Controles/gamepad | **Não reescrever driver/input stack** | libmanette é pequena e madura; avaliar SDL3 só por benefício medido |
| Jogador/streaming de vídeo | **Não** | GSR, Sunshine e codecs externos têm manutenção pesada; conservar opcionais |
| Ações de energia | **Não** | login1/polkit são a fronteira correta de privilégios |
| Cofre de senhas | **Não** | Crypto caseira aumenta risco; continuar Secret Service |
| Gamescope/compositor | **Não** | É precisamente a infraestrutura agnóstica de que a Jolven Session precisa |
| Detecção de distro / catálogo de pacotes / preflight | **Sim** | Pequeno e testável; valor alto em CachyOS/Arch |
| Diagnóstico de portais e sugestões de correção | **Sim** | UI própria pode orientar instalação sem mexer automaticamente no host |
| Busca de jogos do Jolven | **Já existe** | GNOME Shell SearchProvider2 é só um adaptador opcional; pesquisa interna continua |

## 5. Roadmap executável para agentes

### Fase P0 — Inventário, detecção e ausência de GNOME
- [ ] Cobrir por teste a identificação de GNOME, KDE, LXQt, Cinnamon, XFCE, compositores independentes, sessão Jolven e variável vazia/ambígua; não declarar suporte por pacote instalado.
- [ ] Criar módulo mínimo de capabilities com injeção de sondas nos testes; consultar o modo apenas de RuntimeContext.
- [ ] Substituir verificações de GNOME em recursos compartilhados por capacidade e fallback, preservando comportamento GNOME atual.
- [ ] Corrigir documentação que confunde GTK/libadwaita/Meson gnome module/Flatpak runtime com dependência de GNOME Shell.
- [ ] Registrar diagnóstico de ambiente e dependências **sem segredos**, ex.: frontend, sessão, compositor, versões, portals, serviços e motivos de indisponibilidade.
- [ ] Garantir inicialização desktop com GNOME Shell/Settings Daemon e seus schemas não instalados.

**Aceite:** Jolven abre e importa biblioteca em uma instalação não GNOME com GTK4/libadwaita; nenhum recurso opcional impede a janela; nenhuma escrita em schema GNOME fora de backend GNOME ativo.

### Fase P0 — Instalação cross-distro (Arch/CachyOS primeiro)
- [ ] Refatorar install.sh: detecção via ID/ID_LIKE de os-release + gerenciador disponível; catálogos por distro para pacotes obrigatórios, build e opcionais. Manter modo --binary/--source e checksum.
- [ ] Adicionar backend pacman para Arch/CachyOS, preservando DNF em Fedora; evitar pacman -Sy isolado e qualquer instalação silenciosa de AUR. Dar instruções na distro não suportada, sem instalar sistema parcialmente.
- [ ] Separar dependências **requeridas para abrir UI** de dependências **requeridas pela Jolven Session** e das opcionais (GameMode, MangoHud, wpctl, recorder, integrações).
- [ ] Adaptar caminhos polkit/helper/relay conforme distro e layout de libexec, sem relaxar a verificação de dono, permissões e exec path autorizado.
- [ ] Atualizar testes de instalador (mocks para pacman/dnf, falha, checksum, reversão, idempotência); criar smoke tests em Arch/CachyOS e Fedora.
- [ ] Depois avaliar Debian/Ubuntu (apt) e openSUSE (zypper); sistemas imutáveis precisam caminho separado/não suportado com instrução segura.

**Aceite:** instalação desktop, atualização e remoção dos arquivos gerenciados funcionam em CachyOS/Arch e Fedora sem instalar GNOME Shell, GDM ou KDE; rollback não remove dados, pacotes compartilhados ou arquivos de outro app.

### Fase P1 — Atalho global universal
- [ ] Implementar backend xdg-desktop-portal GlobalShortcuts por D-Bus: descoberta de interface/versão, CreateSession, BindShortcuts, ListShortcuts, sinais Activated/Deactivated, encerramento/reconexão e permissão negada.
- [ ] Isolar backends já existentes para GNOME media-keys e KDE KGlobalAccel, com detecção por desktop ativo + serviço real.
- [ ] Corrigir classificação indevida de LXQt e derivados: não presumir que usam mesmo schema/compositor.
- [ ] Preservar conflito de tecla e desinstalação de somente registro gerenciado; não sobrescrever atalhos existentes nem reiniciar KWin.
- [ ] UI de Preferências mostra backend selecionado, estado (ativo, pendente de consentimento, não suportado) e alternativa manual.
- [ ] Testes com portais ausentes/negados, GNOME, KDE, sessão Wayland e X11, Flatpak e nativo.

**Aceite:** Super+G funciona no GNOME e KDE compatíveis, sem depender de schema GNOME na sessão KDE, e tem fallback seguro para desktops sem suporte.

### Fase P1 — Wallpaper seguro e cross-DE
- [ ] Extrair interface de aplicação/restauração sem reescrever geração de arte.
- [ ] Corrigir o backup separado picture-uri / picture-uri-dark no GNOME; fornecer migração para session-wallpaper-saved legado, sem perder valor existente ou sobrescrever após falha.
- [ ] Corrigir a falsa aplicação per-monitor (ou documentar de forma honesta que o backend GNOME altera apenas o papel de parede global). Testar alvos simultâneos.
- [ ] Não desligar preferência persistente na ausência de monitor secundário/backend; apenas informar incapacidade temporária.
- [ ] Avaliar Portal Wallpaper: SetWallpaperFile para imagens locais; perguntar consentimento e **não habilitar automaticamente** se não for possível ler/restaurar o estado original. Portal não fornece getter/per-monitor.
- [ ] Decidir produto: (A) apenas fundo interno padrão, (B) troca desktop apenas nos backends com restore comprovado, (C) suporte per-monitor com implementação explícita por ambiente. Recomendação: A como padrão, B opcional; C só se houver uso real.
- [ ] Testar crash/kill/restart, desconexão de monitor, nome de arquivo Unicode, dark mode, cache e recovery.

**Aceite:** a arte da interface funciona sem GNOME; wallpaper externo nunca fica alterado permanentemente por erro do Jolven; sem perdas de configuração do usuário.

### Fase P1 — Busca, segredos e portais
- [ ] Deixar SearchProvider2 como integração GNOME opt-in/instalação condicional; build e execução não dependem do serviço GNOME. Testar que pesquisa interna permanece.
- [ ] Tornar libsecret/Secret imports robustamente opcionais e lazy onde pertinente (especialmente tuya_conta.py); diferenciar backend ausente, segredo inexistente e cofre trancado.
- [ ] Implementar diagnóstico de portal na Jolven Session (Dbus activation env, WAYLAND_DISPLAY, XDG_CURRENT_DESKTOP=Jolven, backend configuration) sem forçar backend GNOME.
- [ ] Garantir que keyboard_emulator libei/snegg se desabilita com mensagem quando portal EIS/RemoteDesktop não existe; proibir fallback automático para uinput root.
- [ ] Validar abertura de URI, file chooser, notificações e gravador em GNOME/KDE/standalone; priorizar GIO/portais em vez de executar utilitário específico do DE.

**Aceite:** funcionalidades indisponíveis não derrubam a biblioteca; segredos nunca são salvos em claro; portais pedem consentimento conforme o sistema.

### Fase P2 — Jolven Session agnóstica
- [ ] Testar entrada em /usr/share/wayland-sessions com GDM e SDDM; documentar separadamente outros display managers apenas após validação. Não supor usuário do greeter chamado gdm.
- [ ] Testar relay do helper privilegiado quando a home está com modo 0700; garantir tryexec/permissions e que instalação/reversão não toca entradas não gerenciadas.
- [ ] Verificar que sessão Gamescope tem D-Bus session/user, XDG_RUNTIME_DIR, Wayland, polkit agent quando necessário, portais apropriados e áudio; não iniciar serviços via root arbitrariamente.
- [ ] Garantir saída limpa para tela de login, fallback de flags Gamescope, recuperação de áudio, desligamento e foco após jogos, sem GNOME Shell rodando.
- [ ] Testar GPU Intel/AMD/NVIDIA onde viável e mensagens de incompatibilidade; não presumir suporte VRR/HDR.
- [ ] Atualizar README/docs com suporte **testado** e instruções específicas; Fedora/GNOME permanece baseline até matriz validada.

**Aceite:** Jolven Session inicia, joga, encerra e volta ao greeter em pelo menos Fedora/GDM e CachyOS/SDDM com as dependências necessárias; sem iniciar GNOME Shell/KWin (exceto seus próprios DM auxiliares).

### Fase P3 — Racionalização de dependências
- [ ] Auditar imports Python/meson/Flatpak/instalador com script ou teste que classifica required/optional/host-only/Flatpak-only/build-only/DE-only.
- [ ] Verificar necessidade de manter libmanette frente SDL3 **apenas** se redução real de deps ou melhor suporte a controles: exigências hotplug, SDL mappings, dead zones, Guide, chords, haptics e disponibilidade em PyGObject.
- [ ] Avaliar Flatpak com org.freedesktop.Platform apenas por tamanho/reprodutibilidade/maintenance e presença de GTK4, libadwaita, PyGObject; não trocar runtime somente para apagar o nome GNOME.
- [ ] Reduzir permissões Flatpak quando compatível com importadores/execução de jogos; não quebrar leitura de bibliotecas externas.
- [ ] Documentar dependências opcionais via detecção e botão de instalação seguro (sem root amplo/AUR por padrão).

**Aceite:** dependências declaradas coerentes com capacidades reais, comportamento equivalente e redução **medida**, não nominal, de acoplamentos.

## 6. Matriz de validação

| Ambiente | App desktop | Atalho | Wallpaper | Sessão dedicada | Segredos/portal |
|---|---|---|---|---|---|
| Fedora + GNOME Wayland + GDM | obrigatório | GNOME/portal | legado corrigido + interno | baseline | obrigatório |
| CachyOS/Arch + GNOME Wayland + GDM | obrigatório | GNOME/portal | interno + opt-in | obrigatório | obrigatório |
| CachyOS/Arch + KDE Plasma Wayland + SDDM | obrigatório | KDE/portal | interno; externo só com restore | obrigatório | obrigatório |
| KDE Plasma X11 (quando existente) | smoke | backend disponível | interno | n/a | smoke |
| XFCE/Cinnamon/LXQt/X11 | smoke | manual quando não suportado | interno | não prometer sem teste | smoke |
| compositor Wayland independente + portal incompleto | smoke | fallback explícito | interno | smoke | ausência segura |
| Jolven Session Gamescope (sem GNOME/KDE shell) | obrigatório | sem hotkey do desktop, gamepad/OSK sim | interno | obrigatório | diagnóstico |
| Flatpak GNOME/KDE | obrigatório | portal e fallback compatível | somente sem violar sandbox | instalação de sessão via host, não no sandbox | obrigatório |
| ausência de libmanette/libsecret/wpctl/portal/Gamescope | desktop degrada | fallback | interno | modo sessão indisponível | UI preservada |

**Testes unitários (mocks):** seleção de backend; ausência de schemas GNOME; portal não implementado ou permissão negada; estados do Secret Service; GSettings antigo; ordenação de monitores; restauração clara/escura; distro ID/ID_LIKE; pacman/dnf; polkit path root-owned; sessão relay; stderr/timeout; reentrada no mesmo processo.

**Testes de integração:** Meson compile/test; validação Blueprint, GResource, schema, desktop file e AppStream; smoke X11/Wayland; hotplug de controle; Super+G; lançamento Steam/Flatpak e retorno de foco; instalação/removal do .desktop de sessão; reinício após crash; idioma pt-BR/en/es; plataforma Windows não regressa.

**Checklist de segurança:**
- nunca executar Jolven/Gamescope/jogo como root;
- nunca usar pkexec em binário gravável pelo usuário;
- nunca editar atalho/sessão/wallpaper alheio sem identificação e backup;
- nunca contornar autorização de portals/polkit;
- nunca usar backup plaintext de segredos;
- nunca remover pacotes da distro no uninstall do Jolven;
- tratar ações e capacidades indisponíveis com fallback sem bloquear GUI;
- preservar dados Cartridges legados, configs, game IDs, save vault e todos os IDs de schema.

## 7. Artefatos/documentos a atualizar ao implementar

- .agents/architecture.md: fronteira de plataforma/capabilities.
- .agents/compatibility.md: suporte Linux real e matriz com evidências.
- .agents/integrations.md: portais, wallpaper, atalho, credenciais e operações do sistema.
- docs/game-mode-architecture.md e docs/game-mode-plan-audit.md: GDM → display manager suportado; resultados por distro.
- README.md / CONTRIBUTING.md / install.sh: instruções Arch/CachyOS e requisitos por modo sem promessa não validada.
- AGENTS.md: regras para código novo usar capacidades/adaptadores; não introduzir dependência de GNOME Shell.
- tests/: cenários específicos por backend e casos negativos.
- data/io.github.zonaro.Jolven.desktop.in: revisar categoria específica GNOME apenas como metadado, sem mudar categorias válidas indiscriminadamente.

## 8. Fontes técnicas externas verificadas

- XDG Portal GlobalShortcuts: https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.GlobalShortcuts.html
- XDG Portal Wallpaper (SetWallpaperFile não equivale a get/set per-monitor): https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Wallpaper.html
- XDG Portal backend selection: https://flatpak.github.io/xdg-desktop-portal/docs/configuration-file.html
- XDG Portal sessão/ativação D-Bus: https://flatpak.github.io/xdg-desktop-portal/docs/system-integration.html
- libmanette API e dependências: https://gnome.pages.gitlab.gnome.org/libmanette/
- Flatpak runtimes (GNOME sobre freedesktop, independente do DE do host): https://docs.flathub.org/docs/for-app-authors/runtimes
- Flatpak não é acoplado ao GNOME: https://flatpak.org/faq

## 9. Fora do escopo deste issue

- Migrar toda a UI para Flutter/Qt ou substituir libadwaita.
- Escrever compositor, servidor de áudio, driver de controle ou cofre próprio.
- Trocar a distribuição base do host ou substituir o display manager do usuário.
- Integrar launcher/loja/Android ou reestruturar Store/importadores sem relação com a dependência de desktop.
- Declarar compatibilidade oficialmente validada sem testes nos dispositivos/sessões correspondentes.

### Definição de pronto global

1. Desktop abre/importa/lança jogos sem GNOME Shell/daemon/GDM instalado.
2. GNOME e KDE mantêm paridade onde houver suporte, e ambientes sem backend recebem instruções claras.
3. Arch/CachyOS e Fedora possuem instalador e configuração de sessão testados, incluindo polkit/root/relay e retorno ao greeter.
4. Wallpaper não destrói preferências claro/escuro e restaura após falhas; qualquer limite per-monitor fica explícito.
5. Nenhuma dependência opcional causa crash na abertura da janela; nenhum segredo/execução privilegiada perde segurança.
6. Documentação, matriz real e testes automatizados atualizados, com regressão zero na biblioteca e nos modos desktop/sessão.
