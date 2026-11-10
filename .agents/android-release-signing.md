# Assinatura Android manual — issue #88

Existe um workflow de release **manual** em `.github/workflows/jolven-android-release.yml`. Ele não dispara com push, não publica automaticamente na Play Store e não cria releases públicas.

## Secrets necessários no repositório GitHub

Configure os valores em `Settings → Secrets and variables → Actions`:

- `JOLVEN_ANDROID_KEYSTORE_BASE64` — arquivo keystore gerado pelo responsável codificado em Base64.
- `JOLVEN_ANDROID_STORE_PASSWORD` — senha do keystore.
- `JOLVEN_ANDROID_KEY_ALIAS` — alias da chave de assinatura.
- `JOLVEN_ANDROID_KEY_PASSWORD` — senha da chave.

Guarde o **arquivo original e as senhas fora do repositório** com backup seguro. Perder a chave pode impedir atualização de apps distribuídos com essa assinatura.

Ao executar manualmente **Jolven Android signed release (manual)**, o job verifica a presença dos secrets, gera as pastas Android com Flutter, roda `analyze/test`, substitui a assinatura debug por uma assinatura release proveniente do usuário e gera APK + AAB. A keystore permanece no diretório temporário do runner, nunca é adicionada ao Git ou impressa no log. O workflow recusa execução se a estrutura de assinatura do template Gradle mudar.

O artefato assinado fica disponível no próprio run por 7 dias. **Não há garantia de estabilidade para distribuição pública até concluir testes físicos, revisão de permissões e versionamento.** Ainda não foram configurados secrets nem criada uma chave nesta implementação.
