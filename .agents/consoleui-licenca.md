# Licença, proveniência e avisos de terceiros — ConsoleUI (issue #178)

Documenta a origem do frontend do Console e os limites do que pode ser
reaproveitado do [Aurora Launcher]
(https://github.com/codebyallan/aurora-launcher, commit
`bf0a6b845638bd044f9f5c067f53e549929e0932`). Etapa **F0** do épico #176.

## Licença do Aurora

O frontend do Aurora (Vue 3, Nuxt, Tailwind, estilos, transições, UX) está sob
**GPL-3.0**. O Jolven também é GPL-3.0-or-later, o que é compatível, mas a
cópia/adaptação de código do Aurora deve:

1. Conservar os avisos de copyright e a notificação de licença nos arquivos
   reaproveitados (`.vue`, estilos, transições e UX).
2. Manter a autoria original atribuída ao Aurora (codebyallan).
3. Declarar, em cada arquivo adaptado, que é uma obra derivada do Aurora sob
   GPL-3.0.

## O que NÃO é copiado (regra não negociável do épico #176)

- Diretório `electron/`, preload, IPC e bibliotecas `umu`/SGDB do Aurora.
- Persistência `library.json` e o motor de execução do Aurora.
- Node em runtime (pode existir apenas no build da SPA).
- Qualquer código que dê ao WebView acesso ao FS, shell, segredos ou comandos
  arbitrários.

## O que é reaproveitado (apenas camada frontend)

- `.vue`, estilos (Tailwind/CSS), transições e UX do Aurora, adaptados com
  branding/texto do Jolven e i18n pt-BR/en/es.
- Composição visual: fundo full-bleed, carrossel, hero, header, contexto menu,
  modais, loading overlay.

## Ponte WebKit ↔ Python

Uma ponte mínima e tipada é criada pelo Jolven (não vem do Aurora). Ela expõe
apenas comandos autorizados, eventos e serialização, com tratamento assíncrono.
O renderer não acessa filesystem nem shell.

## Empacotamento

- A SPA estática é gerada no build (Vue + Vite, sem Electron) e embarcada como
  recurso do Jolven.
- A distribuição (AppImage/RPM/DEB) inclui o WebKitGTK 6 como dependência de
  runtime; sem ele, cai de volta ao Jolven Flat.

## Avisos a incluir nos pacotes

- Jolven é GPL-3.0-or-later.
- O frontend do Console incorpora obra derivada do Aurora Launcher, GPL-3.0,
  autoria codebyallan — disponível no código-fonte do Jolven.

Refs #176
Refs #178
