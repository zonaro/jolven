# Jolven Nearby — emissor HTTPS temporário no desktop (#146)

**Estado:** protótipo funcional do lado desktop, ainda **não é o fluxo completo Android ↔ PC**. Este comando fica desligado até o usuário executar explicitamente o envio, não é instalado como serviço nem abre porta na inicialização do Jolven.

## Exemplo de envio (somente arquivos próprios)

```bash
python -m cartridges.utils.nearby_sender --bind 0.0.0.0 \
  "rom:/home/usuario/ROMs/homebrew.gba" \
  "save:/home/usuario/Saves/homebrew.srm"
```

O terminal mostra uma **porta aleatória**, um certificado temporário identificado pelo SHA-256 e um token aleatório de sessão. O receptor deve validar o fingerprint **antes** de transmitir o token; conexão HTTPS que não exiba o fingerprint esperado não é confiável. A sessão expira em até cinco minutos e só publica os arquivos explicitamente selecionados.

## Segurança e limitações
- Chave RSA 3072 e certificado TLS autoassinado **efêmeros** gerados pelo OpenSSL em uma pasta temporária, apagados ao encerrar a sessão; chave com permissão 0600.
- Conexões recebem apenas HTTP GET de `/manifest` e `/file/N`; exigem Bearer token secreto (256 bits de entropia) e origem IPv4 privada. Rotas não recebem caminhos do cliente.
- O manifesto exige nome seguro, hash SHA-256, tipo e tamanho; antes de cada envio o servidor verifica se o arquivo original ainda confere com o manifesto. O receptor **também** precisa verificar o hash do conteúdo transferido.
- O servidor não tem endpoint de upload e não modifica os arquivos de origem. Sem nuvem, mDNS, leitura de saves privados de emuladores ou descoberta de ROMs arbitrárias.
- O endereço `0.0.0.0` expõe o **servidor somente durante a sessão**. O usuário deve manter firewall/rede privada. Nenhuma interface externa pública é aceita por padrão.
- **Não** estabelecer conexão com certificado não verificado e sem comparação do fingerprint. A verificação explícita não é opcional para um cliente de produção.

## Ainda pendente
- Cliente Flutter/Kotlin Android que insira IP, token e fingerprint, confirme a oferta e importe os arquivos via SAF com checksum.
- Direção Android → PC com consentimento explícito, escrita temporária e rollback; cancelamento, UI de progresso e testes de host malicioso.
- Pareamento via QR/mDNS opcional, UX persistida de dispositivos confiáveis, testes Android+Fedora/Gamescope.
- Integração visual no Jolven Desktop, confirmação de conflitos e confirmação de overwrite por tipo. Nenhum issue pode ser encerrado só com este protótipo.

Teste: `python -m unittest tests.test_nearby_sender -v`.
