# Adwaita-for-Steam — vendored subset

This directory is a **deliberately reduced** copy of
[Adwaita-for-Steam](https://github.com/tkashkin/Adwaita-for-Steam) by
Anatoliy Kashkin (`tkashkin`), used by the Jolven Steam-skin integration.

## Snapshot

| Field | Value |
| --- | --- |
| Upstream repository | https://github.com/tkashkin/Adwaita-for-Steam |
| Version / tag | `4.4` |
| Commit (tag `4.4`) | `1e92107a51f6ed53c59c38646444c9eb3a52b030` |
| License | MIT (see `LICENSE`, Copyright (c) 2022 Anatoliy Kashkin) |
| Snapshot taken | 2026-10-13 |
| Source archive | https://codeload.github.com/tkashkin/Adwaita-for-Steam/tar.gz/refs/tags/4.4 |
| Release page | https://github.com/tkashkin/Adwaita-for-Steam/releases/tag/4.4 |

## What is vendored

Only the colour data needed to build the skin `config.css` and the palette
variables, keeping the whole vendor tree well under 120 KB:

| Path | Upstream origin |
| --- | --- |
| `LICENSE` | `LICENSE` |
| `VERSION` | `adwaita/VERSION` |
| `palette.css` | `adwaita/css/_colors/palette.css` |
| `colorthemes/<slug>/<slug>.css` | `adwaita/colorthemes/<slug>/<slug>.css` (23 themes, `.css` only) |

The 23 colorthemes are pure `:root { --adw-*: … !important; }` blocks with no
Steam selectors, which is exactly what Jolven consumes.

## What is intentionally excluded (and why)

| Excluded | Reason |
| --- | --- |
| `adwaita/css/**` (structural CSS, ~608 KB) | Too large for the vendor budget. The structural rules are not needed to *define* the Adwaita variables; the installer composes the skin entry files from the vendored palette + colortheme. |
| `adwaita/colorthemes/**/preview.png` (~19 MB) | UI previews only; unused by Jolven. |
| `adwaita/fonts/**` (~7.5 MB) | Optional font bundles; Jolven does not ship them. |
| `adwaita/extras/**`, `adwaita/windowcontrols/**` | Optional extras; not part of Jolven's baseline skin. |
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
3. Copy only the files listed under "What is vendored" above, preserving the
   flat layout (`LICENSE`, `VERSION`, `palette.css`, `colorthemes/<slug>/<slug>.css`).
4. Re-check that the total stays under 120 KB: `du -sb .`.
5. Update the table in this file (tag, commit SHA, snapshot date).
6. Bump `_ADW_VERSION_FALLBACK` in `cartridges/integrations/steam_skin/constants.py`
   only if `VERSION` must be known without reading the file.

No generated artifacts are committed; only the upstream sources listed here.
