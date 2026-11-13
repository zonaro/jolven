# Contributing

## Code

Be sure to follow the [code style](#code-style) of the project.

### Adding a feature
[Create an issue](https://github.com/zonaro/jolven/issues/new) or join the [Discord](https://discord.gg/yrJfddyt56) to discuss it with the maintainers. We will provide additional guidance.

### Fixing a bug
Fork the repository, make your changes, then create a pull request. Be sure to mention the issue you're fixing if one was already open.

## Translations
### Weblate
The project can be translated on [Weblate](https://hosted.weblate.org/engage/cartridges/).

### Manually
1. Clone the repository.
2. If it isn't already there, add your language to `/po/LINGUAS`.
3. Create a new translation from the `/po/cartridges.pot` file with a translation editor such as [Poedit](https://poedit.net/).
4. Save the file as `[YOUR LANGUAGE CODE].po` to `/po/`.
5. Create a pull request with your translations.

# Building

Jolven desktop supports Linux only. GitHub Releases distribute AppImage, RPM and DEB packages; these are not generated with an install.sh script.

## GNOME Builder
1. Install [GNOME Builder](https://flathub.org/apps/org.gnome.Builder).
2. Click "Clone Repository" with `https://github.com/zonaro/jolven.git` as the URL.
3. Click on the build button (hammer) at the top.

## Meson
```bash
git clone https://github.com/zonaro/jolven.git
cd jolven
meson setup build --prefix="$HOME/.local" -Dprofile=release
meson compile -C build
meson test -C build --print-errorlogs
meson install -C build
```

# Code style

All code is auto-formatted with [Black](https://github.com/psf/black) and linted with [Pylint](https://github.com/pylint-dev/pylint). Imports are sorted by [isort](https://github.com/pycqa/isort).

VSCode extensions are available for all of these and you can set them up with the following `settings.json` configuration:

```json
"python.formatting.provider": "none",
"[python]": {
    "editor.defaultFormatter": "ms-python.black-formatter",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
        "source.organizeImports": true
    },
},
"isort.args":["--profile", "black"],
```

For other code editors, you can install them via `pip` and invoke them from the command line.

## Desktop releases

Run [Release Desktop](https://github.com/zonaro/jolven/actions/workflows/release-desktop.yml)
manually from the `main` branch. The workflow creates one UTC version
(`YY.DDD.HHmm`) for the entire build, assembles AppImage/RPM/DEB packages,
verifies all assets and checksums, then publishes a GitHub Release with
**English-language notes only**. A failed package build never publishes a
partial release.

Implementation and package dependencies: [packaging/README.md](packaging/README.md).
