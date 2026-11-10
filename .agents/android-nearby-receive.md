# Jolven Nearby — receptor Android inicial (#146)

**Primeiro caminho real: PC → Android**, sem incluir emuladores no APK.

No PC, execute manualmente:

```bash
python -m cartridges.utils.nearby_sender --bind 0.0.0.0 "rom:/caminho/da/rom/homebrew.gba"
```

No Android, em **Jolven → Receber do PC**, informe:
- Endereço `https://IP-PRIVADO:PORTA` exibido pelo remetente (por exemplo 192.168.1.20);
- fingerprint SHA-256 TLS **completo**, comparado fora do canal de rede;
- token secreto da sessão.

O aplicativo valida endereço IPv4 privado, certificado apresentado **em cada resposta TLS**, token e esquema HTTPS; desativa redirects/compactação. O manifesto remoto exige versão 1, campos estritos, nomes sem traversal, até 128 arquivos, limite de 8 GiB por arquivo / 16 GiB no lote e SHA-256 esperado.

O usuário escolhe quais arquivos receber; cada um é transferido em fluxo para staging privado do app e validado por SHA-256 e tamanho antes de mostrar o picker `ACTION_CREATE_DOCUMENT`. Não grava diretamente em pastas de terceiros, não exige `MANAGE_EXTERNAL_STORAGE`, não sobrescreve jogos/saves sem consentimento Android. Se o certificado, hash ou conexão falhar, o download é descartado. Depois de salvo, o arquivo pode ser importado na biblioteca por SAF.

O receptor Android só envia solicitações **depois de ação explícita na UI**; sem descoberta de máquinas, servidor de rede local ou serviço permanente no APK. O token não é persistido em preferências; apenas fica nos controllers da página até ela ser descartada.

## Limitações explícitas
- **Não** implementa Android → PC, nem escolha de pasta de destino em lote ou reimportação automática na biblioteca.
- Sem teste de hardware Android/Wi-Fi local. CI Flutter testa validação de envelope e compila o APK, mas não verifica conectividade ou SAF real.
- Aparelhos com policy que bloqueie cleartext não afetam HTTPS; captive portal/proxy não é suportado, endereço DNS público não é permitido.
- Emuladores permanecem externos: saves/states só podem ser copiados quando o usuário exportou os arquivos.
- O código não autentica o cliente no servidor além do token TLS-pinned; não reutiliza token/certificado após a sessão.
- Para cancelar uma sessão, feche a tela ou toque Cancelar; em caso de queda, staging temporário é excluído.

## Pendente
Paired devices UX por QR/mDNS seguro, direção Android→PC, progresso agregado, testes de atacante/DoS, integração desktop gráfica, tratamento de perda da Activity e retorno de erro dos provedores SAF, testes de 2 GB+, escolha de conflito, QA Android+Fedora e documentação de rede real. Não fechar #146 ainda.
