# Adwaita-for-Steam — vendored subset

This directory is a **curated** copy of
[Adwaita-for-Steam](https://github.com/tkashkin/Adwaita-for-Steam) by
Anatoliy Kashkin (`tkashkin`), used by the Jolven Steam-skin integration.

## Snapshot

| Field | Value |
| --- | --- |
| Upstream repository | https://github.com/tkashkin/Adwaita-for-Steam |
| Version / tag | `4.4` |
| Commit (tag `4.4`) | `1e92107a51f6ed53c59c38646444c9eb3a52b030` |
| License (skin) | MIT (see `LICENSE`, Copyright (c) 2022 Anatoliy Kashkin) |
| License (fonts) | SIL OFL 1.1 — see `fonts/adwaita/*/LICENSE.md` and `fonts/cantarell/COPYING` |
| Snapshot taken | 2026-10-13 |
| Source archive | https://codeload.github.com/tkashkin/Adwaita-for-Steam/tar.gz/refs/tags/4.4 |
| Release page | https://github.com/tkashkin/Adwaita-for-Steam/releases/tag/4.4 |

## What is vendored

| Path | Upstream origin |
| --- | --- |
| `LICENSE` | `LICENSE` |
| `VERSION` | `adwaita/VERSION` |
| `palette.css` | `adwaita/css/_colors/palette.css` |
| `colorthemes/<slug>/<slug>.css` | `adwaita/colorthemes/<slug>/<slug>.css` (23 themes, `.css` only) |
| `extras/**/*.css` | `adwaita/extras/**/*.css` (all 8 extras + `README.md`) |
| `windowcontrols/*.css` | `adwaita/windowcontrols/*.css` (`adwaita`, `breeze`, `macos`, `windows`) |
| `fonts/**` | `adwaita/fonts/**` (`adwaita`, `cantarell`, `system` stylesheets, font binaries and their `LICENSE.md`/`COPYING`) |

The 23 colorthemes are pure `:root { --adw-*: … !important; }` blocks with no
Steam selectors, which is exactly what Jolven consumes. The `extras/`,
`windowcontrols/` and `fonts/` trees feed the advanced options on the
Appearance page (`installer.py` maps each option to its file; see
`OPCAO_EXTRA_MAP`, `_MAPA_TEMA_CONTROLES` and `_resolver_layout_controles`).

Total size is ~7.8 MB, almost entirely the optional font binaries
(`fonts/adwaita/**` ~7.3 MB, `fonts/cantarell/cantarell-vf.otf` ~0.2 MB).
Everything else stays under 120 KB.

## What is intentionally excluded (and why)

| Excluded | Reason |
| --- | --- |
| `adwaita/css/**` (structural CSS, ~608 KB) | Too large for the vendor budget. The structural rules are not needed to *define* the Adwaita variables; the installer composes the skin entry files from the vendored palette + colortheme. |
| `adwaita/colorthemes/**/preview.png` (~19 MB) | UI previews only; unused by Jolven. |
| `injectors/**` | Millennium / CSS-loader injectors for other skin managers; Jolven patches Steam's CSS directly. |
| `screenshots/**` | Documentation images only. |
| `scripts/**` | Upstream installer CLI; Jolven reimplements the needed mechanics in `cartridges/integrations/steam_skin/installer.py`. |
| `install.py`, `skin.json`, `theme.json` | Upstream launcher/manifests; not used. |

## Updating this vendor

When a newer upstream release is needed:

1. Pick the target tag (e.g. `4.5`) and resolve its commit SHA:
   `curl -sL https://api.github.com/repos/tkashkin/Adwaita-for-Steam/git/ref/tags/<tag>`.
2. Download the tag archive:
   `curl -sL https://codeload.github.com/tkashkin/Adwaita-for-Steam/tar.gz/refs/tags/<tag> -o afs.tar.gz`.
3. Copy the files listed under "What is vendored" above, preserving the
   layout (`LICENSE`, `VERSION`, `palette.css`, `colorthemes/<slug>/<slug>.css`,
   plus the `extras/`, `windowcontrols/` and `fonts/` trees with their license
   files). Never run remote code; only copy data files (CSS, TTF/OTF, docs).
4. Re-check the size: `du -sb .` (expect ~8 MB while fonts are vendored).
5. Update the table in this file (tag, commit SHA, snapshot date).
6. Bump `_ADW_VERSION_FALLBACK` in `cartridges/integrations/steam_skin/constants.py`
   only if `VERSION` must be known without reading the file.
7. Run the Steam-skin tests:
   `PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_steam_*.py'`.

No generated artifacts are committed; only the upstream sources listed here.
