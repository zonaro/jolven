# Compatibilidade e plataforma

## Escopo suportado

Jolven é um produto Linux. O aplicativo desktop se comporta em GNOME, KDE e
outros ambientes que ofereçam GTK/portais adequados. Integrações específicas do
desktop precisam detectar suporte e oferecer orientação manual quando
indisponíveis.

O Jolven **desktop é exclusivamente Linux**. O aplicativo Android é um
projeto separado, com seu próprio frontend e integração a emuladores externos.
A compatibilidade entre GNOME, KDE e outros ambientes Linux deve continuar
independente do desktop, do compositor e da distribuição. A remoção do código
de portabilidade desktop é acompanhada pelo épico #168.

## Stack mínima

O build de fonte declara aproximadamente:

- Python 3;
- Meson 0.59 ou posterior;
- GTK 4.15 ou posterior;
- libadwaita 1.8 ou posterior;
- Blueprint Compiler;
- PyGObject e bibliotecas Python instaladas pelo projeto.

O manifesto Flatpak usa a plataforma GNOME 49 e é a referência mais reprodutível
do ambiente de runtime. Se a versão do manifesto divergir da CI ou dos requisitos
Meson, trate como dívida a ser resolvida, não como três fontes independentes de
verdade.

## Wayland, X11 e Gamescope

Wayland é o caminho primário. O Flatpak ainda expõe sockets Wayland e X11 para
compatibilidade com desktops e launchers. Jolven Session é baseada em Gamescope e
portanto tem requisitos mais estritos que o aplicativo desktop.

Distribuições recomendadas: **Fedora Workstation, Nobara, CachyOS e Ubuntu**.
A recomendação é de produto, não um selo de QA. Verificar por versão se GTK 4.15+,
libadwaita 1.8+, Python/GI, Gamescope, portais, polkit e runtime da sessão estão
disponíveis. AppImage instala apenas o aplicativo desktop, não a integração de
sessão privilegiada. O helper dispõe de instalação de dependências via DNF para Fedora/Nobara e
APT para Ubuntu, ainda dependentes de smoke tests reais. Em CachyOS evita
atualização automática de todo o sistema via pacman: orienta instalar Gamescope
com CachyOS Hello antes de registrar a sessão. A sessão deve continuar falhando
com segurança sem Gamescope (ver #199).

| Família | Pacotes | Display manager a testar | Estado da sessão |
| --- | --- | --- | --- |
| Fedora Workstation | RPM / DNF | GDM | Referência atual; QA por release pendente |
| Nobara | RPM / DNF | GDM e SDDM, conforme edição | QA por edição pendente |
| CachyOS | pacman (AppImage desktop) | Plasma Login Manager, SDDM ou GDM | QA e backend de pacotes pendentes |
| Ubuntu | APT / DEB (somente ABI compatível) | GDM | QA e backend de pacotes pendentes |

Não assumir que ID_LIKE=arch implica suporte pronto: releases rolling, login
manager e dependências mudam. Em Ubuntu LTS antigo, validar versões das bibliotecas
antes de oferecer DEB. Preservar rollback, dados de usuário e greeter original.

Em sessão dedicada:

- não aninhe Gamescope ao lançar jogos;
- restaure áudio e estado alterado ao encerrar;
- preserve fallback de parâmetros de monitor/FPS;
- nunca execute a sessão como root;
- mantenha a instalação privilegiada pequena e auditável.

## Dependências opcionais

| Capacidade | Dependência | Comportamento sem ela |
| --- | --- | --- |
| xCloud (navegador externo) | navegador com modo quiosque | abre em janela nova sem tela cheia |
| gamepad | libmanette | teclado e mouse continuam funcionais |
| emulação de entrada | libei/snegg + portal | ação específica indisponível |
| Jolven Session | Gamescope | desktop funciona; sessão não instala/inicia |
| perfil de desempenho | GameMode | jogo inicia sem wrapper |
| overlay | MangoHud | jogo inicia sem overlay |
| controle de áudio | `wpctl`/WirePlumber | não ajustar automaticamente |
| luzes inteligentes | `tinytuya` e Secret Service | integração desabilitada |
| autenticação das Preferências | polkit (`pkcheck`) | sem política/agente, fallback de indisponibilidade explicitamente documentado; negação real não libera o diálogo |

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

