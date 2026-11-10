# Jolven Nearby v1 — segurança primeiro (issue #146)

Esta entrega implementa apenas **a camada de manifesto de arquivos** em `cartridges/utils/nearby_manifest.py`, testável sem rede nem interface gráfica. **Não há servidor TCP/TLS, pareamento, descoberta de hosts ou recepção Android nesta etapa.** Isso evita anunciar transferência LAN antes de implementar o modelo de ameaça completo.

## Envelope em JSON UTF-8

```json
{"version":1,"files":[{"name":"homebrew.gba","size":1234,"sha256":"<64 hexadecimal characters>","kind":"rom"}]}
```

- Metadados obrigatórios estritos, rejeição de campos extras, versão não suportada e nomes que possam escapar da pasta destino.
- Tipos permitidos: `rom`, `save`, `cover`, `label`; saves externos só os escolhidos/exportados pelo usuário.
- Máximo de 128 entradas, 8 GiB por entrada, 16 GiB por lote e 256 KiB por manifesto.
- SHA-256 calculado por stream local, rejeição de symlinks, comparação de tamanho + hash do staging antes de qualquer importação. Nenhuma sobrescrita de ROM/save por nome igual.
- O manifesto **não fornece autorização**, criptografia, autenticação de emissor ou integridade do canal. Nunca aceitar tráfego de rede com este parser isolado.

## Próxima implementação antes de expor a UI de rede
1. Transmissão sob TLS autenticado com pinning ou PAKE e confirmação visual do fingerprint/código em **ambas** as pontas.
2. Receptor não escuta por padrão; ativo apenas durante sessão consentida, com timeout, quotas, limites de taxa, cancelamento e contadores.
3. Oferta de arquivos → aceite seletivo por item/tamanho/tipo → streaming para arquivos temporários não executáveis → checksum → confirmação de conflito e importação atômica.
4. Descoberta mDNS opcional e endereço manual, rejeitando interfaces fora da LAN quando possível; testes de peer malicioso/DoS e queda de conexão.
5. Cliente Android SAF e servidor desktop, sem copiar dados do sandbox de emuladores de terceiros.

**Não fechar #146** até teste Android↔Linux nos dois sentidos com rede real e confirmação humana de pareamento.
