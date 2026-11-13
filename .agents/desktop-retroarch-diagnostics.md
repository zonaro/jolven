# RetroArch desktop — diagnóstico opcional (issue #152)

O Jolven mantém o RetroArch **externo**. No desktop, a página **Integrações → RetroArch → Diagnosticar** deixa o usuário selecionar explicitamente seu `retroarch.cfg`. Sem escolha, nenhum arquivo de configuração do usuário é lido.

`cartridges/utils/retroarch_diagnostics.py` usa apenas Python stdlib e não altera `retroarch.cfg`. O parser aceita `libretro_directory`, `system_directory`, `video_shader_dir` com a sintaxe de diretórios relativos a `:` do RetroArch e ignora entradas não reconhecidas. Exibe o número de bibliotecas libretro encontradas e a quantidade de avisos; o caminho escolhido é processado em worker, fora da thread GTK.

**Segurança e limitações**: arquivos de configuração acima de 1 MiB são rejeitados; somente diretórios dentro da home ou da pasta de configuração escolhida são examinados por padrão (opt-in explícito necessário para outros diretórios); lista de cores limitada a 512 arquivos, sem executar ou carregar código de core; não faz download de firmware/shader nem escreve no sandbox do emulador. O relatório é apenas uma verificação de presença de arquivos, **não** de funcionalidade do core ou validade de BIOS.

**Ainda pendente**: perfis de shader/controle por console e jogo, overrides temporários sem mutação de configurações globais, diagnóstico detalhado de BIOS pessoais, compatibilidade RetroArch Flatpak/Steam/nativo em sistemas reais e testes de navegação pela Jolven Session. Não fechar #152 até esses critérios.

## Testes
`python -m unittest tests.test_retroarch_diagnostics -v`
