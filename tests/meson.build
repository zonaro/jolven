test(
  'Python unit tests',
  py_installation,
  args: ['-m', 'unittest', 'discover', '-s', meson.current_source_dir(), '-v'],
  env: ['PYTHONPATH=' + meson.project_source_root()],
  # A suite inteira leva dezenas de segundos em runners compartilhados; o
  # padrao de 30s do meson produz TIMEOUT intermitente.
  timeout: 600,
)
