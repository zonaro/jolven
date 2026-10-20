blueprint_compiler = find_program('blueprint-compiler')
blueprints = []
foreach name : [
  'details-dialog',
  'fita-wizard',
  'game',
  'logo-picker',
  'preferences',
  'image-picker',
  'shortcuts-dialog',
  'wallpaper-picker',
  'window',
]
  blueprints += custom_target(
    name + '-blueprint',
    input: 'gtk/' + name + '.blp',
    output: name + '.ui',
    command: [blueprint_compiler, 'compile', '--output', '@OUTPUT@', '@INPUT@'],
  )
endforeach

# O arquivo .desktop e a integracao com o menu sao do Linux; no Windows a
# entrada do aplicativo e criada pelo instalador.
if host_machine.system() == 'linux'
  desktop_file = i18n.merge_file(
    input: configure_file(
      input: 'io.github.zonaro.Jolven.desktop.in',
      output: app_id + '.desktop.in',
      configuration: conf,
    ),
    output: app_id + '.desktop',
    type: 'desktop',
    po_dir: '../po',
    install: true,
    install_dir: join_paths(get_option('datadir'), 'applications'),
  )

  desktop_utils = find_program('desktop-file-validate', required: false)
  if desktop_utils.found()
    test('Validate desktop file', desktop_utils, args: [desktop_file])
  endif
endif

appstream_file = i18n.merge_file(
  input: configure_file(
    input: 'io.github.zonaro.Jolven.metainfo.xml.in',
    output: app_id + '.metainfo.xml.in',
    configuration: conf,
  ),
  output: app_id + '.metainfo.xml',
  po_dir: '../po',
  install: true,
  install_dir: join_paths(get_option('datadir'), 'metainfo'),
)

# ── Recursos de tema (paletas e previews) ────────────────────────────────
# As paletas entram no GResource e sao instaladas como dados. Os previews SVG
# sao produzidos pela lane de UI e podem ainda nao existir; a varredura abaixo
# tolera o diretorio ausente ou vazio sem quebrar o build.
theme_palette_slugs = [
  'adwaita',
  'adwaita-gray',
  'breeze',
  'canta',
  'catppuccin-frappe',
  'catppuccin-latte',
  'catppuccin-macchiato',
  'catppuccin-mocha',
  'dracula',
  'everforest',
  'gruvbox',
  'kate',
  'metro',
  'nord',
  'oled',
  'one-dark',
  'pop',
  'rose-pine',
  'tokyo-night',
  'tomorrow-night',
  'vapor',
  'vgui2',
  'yaru',
  'jolven',
]

theme_files_xml = ''
foreach slug : theme_palette_slugs
  _palette = 'themes/palettes/' + slug + '.css'
  theme_files_xml += '    <file alias="' + _palette + '">' + _palette + '</file>\n'
  install_data(
    _palette,
    install_dir: join_paths(pkgdatadir, 'themes', 'palettes'),
  )
endforeach

# Previews opcionais: so entram quando existem, para o diretorio vazio do
# inicio do desenvolvimento nao derrubar o gresource.
_fs = import('fs')
_previews_scan = run_command(
  py_installation.full_path(),
  '-c',
  'import glob, os, sys; base = sys.argv[1]; ' +
  'print("\\n".join(sorted(glob.glob(os.path.join(base, "themes/previews/*.svg")))))',
  meson.current_source_dir(),
  check: true,
)
theme_previews_xml = ''
foreach _abs : _previews_scan.stdout().strip().split('\n')
  if _abs != ''
    _preview = 'themes/previews/' + _fs.name(_abs)
    theme_previews_xml += '    <file alias="' + _preview + '">' + _preview + '</file>\n'
    install_data(
      _preview,
      install_dir: join_paths(pkgdatadir, 'themes', 'previews'),
    )
  endif
endforeach

# O vendor do Adwaita-for-Steam e lido em tempo de execucao por
# cartridges/integrations/steam_skin/vendor.py em <pkgdatadir>/vendor/adwaita-for-steam.
# Instalado como dados comuns (nao vai no GResource: precisa ser inspecionavel
# e atualizavel a mao, conforme UPSTREAM.md).
install_subdir(
  'vendor',
  install_dir: pkgdatadir,
  exclude_directories: ['__pycache__'],
)

# O `conf` global já foi consumido pelos configure_file acima; o gresource usa
# um objeto próprio com as mesmas chaves do template.
theme_conf = configuration_data()
theme_conf.set('APP_ID', app_id)
theme_conf.set('PREFIX', prefix)
theme_conf.set('theme_files', theme_files_xml)
theme_conf.set('theme_previews', theme_previews_xml)

gnome.compile_resources(
  'jolven',
  configure_file(
    input: 'jolven.gresource.xml.in',
    output: 'cartridges.gresource.xml',
    configuration: theme_conf,
  ),
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
  dependencies: [blueprints, appstream_file],
)

appstreamcli = find_program('appstreamcli', required: false)
if appstreamcli.found()
  test(
    'Validate appstream file',
    appstreamcli,
    args: ['validate', '--no-net', '--explain', appstream_file],
    workdir: meson.current_build_dir(),
  )
endif

schema_file = configure_file(
  input: 'io.github.zonaro.Jolven.gschema.xml.in',
  output: app_id + '.gschema.xml',
  configuration: conf,
)

install_data(
  schema_file,
  install_dir: join_paths(get_option('datadir'), 'glib-2.0/schemas'),
)

compile_schemas = find_program('glib-compile-schemas', required: false)
if compile_schemas.found()
  test(
    'Validate schema file',
    compile_schemas,
    args: ['--strict', '--dry-run', meson.current_build_dir()],
  )
endif

subdir('icons')

if host_machine.system() == 'linux'
  _polkit_install = get_option('prefix') in ['/usr', '/usr/local']
  _polkit_dir = join_paths(get_option('prefix'), 'share/polkit-1/actions')
  # O exec.path precisa apontar para onde o helper foi instalado nesta
  # compilacao (prefixo + libexecdir). Em build de usuario (~/.local) as
  # policies nao sao instaladas, mas o arquivo gerado mantem
  # system_libexecdir (/usr/libexec) porque e ele que o install.sh promove.
  _policy_execdir = get_option('system_libexecdir')
  if _polkit_install
    _policy_execdir = join_paths(get_option('prefix'), get_option('libexecdir'))
  endif
  _policy_conf = configuration_data()
  _policy_conf.set('system_libexecdir', _policy_execdir)
  configure_file(
    input: 'io.github.zonaro.Jolven.GameMode.policy.in',
    output: app_id + '.GameMode.policy',
    configuration: _policy_conf,
    install: _polkit_install,
    install_dir: _polkit_dir,
  )
  configure_file(
    input: 'io.github.zonaro.Jolven.XCloudDeps.policy.in',
    output: app_id + '.XCloudDeps.policy',
    configuration: _policy_conf,
    install: _polkit_install,
    install_dir: _polkit_dir,
  )
  configure_file(
    input: 'io.github.zonaro.Jolven.Preferences.policy.in',
    output: app_id + '.Preferences.policy',
    configuration: _policy_conf,
    install: _polkit_install,
    install_dir: _polkit_dir,
  )
endif
