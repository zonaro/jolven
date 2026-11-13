# Jolven Nearby — upload Android → Desktop (issue #146)

**Implementado como primeira integração com usuário explícito nas duas pontas**, ainda requer QA em aparelho real antes de ser considerado estável.

## Como usar

No PC, inicie a sessão receptora:

```bash
python -m cartridges.utils.nearby_receiver \
  --dest /home/usuario/Recebidos --bind 0.0.0.0
```

O receptor mostra URL local, token temporário e fingerprint SHA-256 de um certificado TLS efêmero. No Android, abra Jolven → **Ferramentas → Enviar arquivo ao PC**, informe URL/fingerprint/token, escolha o tipo do arquivo e selecione um arquivo de sua propriedade via Android SAF.

O Android copia temporariamente o arquivo selecionado para cache privado (limite inicial de **512 MiB**), computa hash SHA-256 e envia um manifesto do formato Nearby v1. O computador lista nome, tipo e tamanho e exige digitar **YES** antes de permitir o envio. Depois, o envio em streaming vai para staging no destino escolhido, é validado por checksum e só então movido por hard link atômico com `os.link` (não substitui arquivo já existente). Ao confirmar, o receptor se encerra, limpando certificados e arquivos temporários.

## Restrições de segurança

- A comunicação é HTTPS TLS 1.2+ com pinning do **certificado exato** antes de enviar token ou conteúdo. O cliente desabilita raízes CA por padrão e aceita somente o certificado cujo fingerprint foi fornecido explicitamente. Verifica novamente o certificado da resposta.
- Endereço de destino somente IP IPv4 privado/loopback, nunca hostname resolvido por terceiros nem `http://`.
- Token de 256 bits temporário, não persistido. Nenhum servidor abre no Android. O destinatário desktop só é executado sob comando explícito.
- O backend recusa caminhos traversal, extensão de nomes inválida, tipo desconhecido, hash divergente, alteração no tamanho, arquivos duplicados, e não sobrescreve saves/ROMs. O servidor não instala jogos/emuladores, não edita configurações de RetroArch.
- Falha de envio não remove o original. O arquivo temporário do Android é apagado após envio concluído ou descarte da página; não distribuir ROMs/BIOS não autorizados.

## Limitações / pendências

- Apenas **um arquivo por sessão enviada pelo Android**; a recepção PC→Android permite seleção múltipla.
- Sem descoberta automática/mDNS, QR, transferência em segundo plano, integração com a biblioteca pós-envio, retomada de upload, fila, diagnóstico de VPN/hotspot, UI desktop GTK para iniciar/acompanhar sessão, progresso por arquivo no receptor.
- `create_receiver` ainda precisa de revisão de ameaças em LAN real, testes com cliente malicioso e limites práticos em devices e versões diferentes de Android; CLI de recepção é **experimental**.
- A opção `--bind 0.0.0.0` expõe a porta temporária na rede local; só usar com firewall/rede confiável.
- Sem QA com arquivo grande e suspensão do Android. Não fechar #146 até testar Android↔Linux nos dois sentidos e verificar operações SAF/rollback reais.

Código: `cartridges/utils/nearby_receiver.py`, `android/jolven_flutter/lib/src/nearby_send_page.dart`, `NearbyStageBridge.kt`.
