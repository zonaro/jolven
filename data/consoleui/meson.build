# data/consoleui/meson.build
#
# Instala a SPA estática do Jolven Console (frontend WebKitGTK) como dados
# comuns, para que cartridges/console_shell.py a carregue no WebView.
#
# Nenhuma dependência de Node/Vue em tempo de execucao: a SPA e um conjunto de
# arquivos HTML/CSS/JS puros, escritos a mao a partir da referencia visual do
# Aurora Launcher (GPL-3.0, autoria codebyallan) e adaptados com a
# identidade Jolven. A ligacao WebKit <-> Python e tratada em
# cartridges/console_shell.py.

install_subdir(
  'spa',
  install_dir: join_paths(pkgdatadir, 'consoleui'),
)
