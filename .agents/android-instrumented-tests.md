# Testes Android instrumentados (issue #88)

O workflow `.github/workflows/jolven-android.yml` mantém o build de debug existente e adiciona um job separado `android-smoke` em **emulador Android API 35**. Este job executa `integration_test/native_bridge_test.dart` com o Flutter + Kotlin reais, sem mocks de MethodChannel.

Cobertura inicial:
- Chamadas de consulta nativas para emuladores instalados, ROMs, Remote Play, coleções e gamepads.
- Inicialização da interface Jolven **sem RetroArch instalado**.
- Abertura da tela Nearby sem iniciar qualquer conexão de rede na ausência de entrada/ação explícita.

O teste não inclui emuladores de terceiros, ROMs comerciais ou dados de contas pessoais. Não usa permissões `QUERY_ALL_PACKAGES` nem `MANAGE_EXTERNAL_STORAGE`.

**Limitações:** emulador não substitui QA físico com gamepads USB/Bluetooth, diferentes provedores SAF, Android 11/13/15, aparelhos de baixo custo, MediaProjection, rotação/foldables, hosts Sunshine/RetroArch/PPSSPP e fluxo Nearby em LAN real. Uma build no CI não prova que todos os adaptadores externos funcionarão em hardware. O job é apenas o primeiro degrau de QA instrumentado, não release assinada.
