# ROM Patcher — Kwiq Gaming → Jolven Android

The optional native Android ROM patcher is adapted from code in the user's legacy `zonaro/Kwiq`: `rompatcher/RomPatchEngine.kt`. No emulation code is embedded.

- Recognized formats include IPS/EBP, UPS and BPS. Only these three decoders are enabled; other detected formats remain unsupported and result in an explicit error. IPS and EBP share the existing IPS magic/decoder.
- Input ROM is an already-imported SAF document. Patch is selected separately through ACTION_OPEN_DOCUMENT. The output is chosen through ACTION_CREATE_DOCUMENT, with a new file name. The original ROM and patch are never modified.
- Processing runs on the Kotlin worker. It stages limited copies in the app cache and emits the result through the destination provider. Files are deleted in finally. On error, it attempts to remove the just-created output document; the original remains intact.
- Limits: ROM input up to 64 MiB, patch up to 8 MiB and output up to 96 MiB, record allocations limited to 8 MiB. No arbitrary archive extraction or downloaded ROMs.
- UPS/BPS verify source and result checksums when supported by the Kwiq engine. IPS has no built-in checksum; the exported result includes computed SHA-1 for optional verification.
- UI is a separate Flutter page, strings in pt-BR, en and es. Choose an imported ROM, pick patch, export copy. User may import result into Jolven's ROM library separately.

## Tests and release gates

Kotlin JUnit tests for fixture IPS patch and invalid format are at `android/app/src/test/kotlin/.../RomPatchEngineTest.kt` and run in GitHub Actions after scaffold generation. Additional **UPS/BPS fixtures, malformed inputs, hardware SAF provider tests, cancellation and performance benchmarks** are required before marking #86 fully completed. Native paths, SAF permissions and policy should be tested on real devices.

Do not use on copyrighted games without the user's rights to modify them.
