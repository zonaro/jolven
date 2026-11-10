# Jolven Nearby — interface GTK no desktop (issue #146)

**UI inicial implementada** em `cartridges/utils/nearby_dialog.py`, acessível por `Integrações → Ferramentas → Jolven Nearby → Compartilhar / receber`.

- Selecionar **um arquivo pessoal** por `Gtk.FileDialog` e um tipo (ROM, save exportado, capa ou etiqueta) para PC→Android, ou uma **pasta destino** para Android→PC. O app não varre nem lê diretórios privados de emuladores.
- Uma sessão de até **5 minutos** é criada somente ao clicar em **Iniciar envio** ou **Aguardar recebimento**. Nenhuma porta aberta no startup do app.
- **Permitir conexões na LAN** é **desativado por padrão** (loopback `127.0.0.1`). Ao ativar, o servidor usa `0.0.0.0` temporariamente; usar apenas em rede confiável, com firewall habilitado.
- A janela mostra fingerprint SHA-256 e token temporário para copiar manualmente ao Android. Ambos são apagados da UI ao encerrar; a keystore TLS temporária é apagada pelo backend.
- No recebimento, uma oferta informa nome/tipo/tamanho de cada item e exige **Aceitar todos**. Falha/timeout/fechamento da janela = recusar. Não há sobrescrita silenciosa e os arquivos são verificados por checksum antes de serem publicados no destino.
- **Encerrar sessão** usa `threading.Event` para interromper o loop do servidor, liberando portas/arquivos temporários. Nenhum token fica em preferências ou logs.
- Inicialização/transferência/checagem executadas em workers; UI GTK só atualiza via GLib. Cancelamento de sessão não exige matar o processo Jolven.

## Limitações importantes

**Ainda experimental**: o receptor e emissor usam servidor HTTP/TLS Python simplificado e não foram validados por QA malicioso/LAN física. Sem descoberta mDNS, QR, progresso detalhado por byte, fila de arquivos, reenvio ou importação automática na biblioteca. A UI desktop depende de caminhos locais fornecidos pelo portal GTK; se o documento não tiver `get_path()`, deve indicar indisponibilidade sem ler fora do sandbox.

O app Android **não** embute emuladores e continua acessando apenas arquivos autorizados via SAF. O token e fingerprint são dados de pareamento: devem ser comparados no Android **antes** de receber/enviar conteúdo. Não considerar #146 concluído até testes com dispositivos Android, Linux Flatpak/nativo e adversários na rede.

Teste de backend: `python -m unittest tests.test_nearby_sender tests.test_nearby_receiver -v`.
