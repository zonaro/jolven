# Linux release packaging

This directory replaces the former Fedora-only `install.sh` and manual
tarball publishing script. **The desktop application targets Linux only.**
The Android application has its own CI/release workflow.

## Version contract

The release workflow creates one version as it starts, in UTC:
`YY.DDD.HHmm` (e.g. `26.317.0132`). DDD is the ordinal day, **001–366**
(zero-padded); HHmm is **0000–2359**. `build-aux/versioning.py` validates the
date, including leap years. The workflow sets `JOLVEN_VERSION` in every
package job. Meson project metadata and installed `cartridges/version.py`
must agree, and the Git tag is `vYY.DDD.HHmm`.

If two builds start in the same UTC minute, they would have the same version.
The release workflow **rejects** an existing tag rather than overwriting it
or silently mixing artifacts.

## Build targets

| Artifact | CI base | How it is built |
| --- | --- | --- |
| AppImage x86_64 | Debian 13 (trixie) | Meson staging + appimage-builder, bundling Python, GTK4, libadwaita, PyGObject, introspection typelibs and schemas |
| .deb amd64 | Debian 13 (trixie) | Meson staging + fpm + post-install schema/cache hooks |
| .rpm x86_64 | Fedora 43 | Meson staging + fpm + post-install schema/cache hooks |

Commands (inside the matching disposable Linux build container):

```sh
export JOLVEN_VERSION="$(python3 build-aux/get-version.py)"
bash packaging/build-release.sh deb        # or rpm, or appimage
```

The build runs Meson compilation/tests before packaging; packages contain
`/usr/bin/jolven`, Python files, application data, GSettings schema,
icons and system helpers. Package-manager hooks rebuild system schemas and
desktop/icon caches without deleting user configuration. Do not install
system packages and AppImages into the same test environment when measuring
relocatability.

The AppImage is intended for **desktop** usage. Its embedded helper/polkit
files are not system-trusted just because the file was launched, so installing
a Jolven Session through the AppImage must not be advertised as functional.
Use a native RPM/DEB installation to enable the system integration where
the display manager and dependencies support it.

## Publishing

Run `Actions → Release Desktop → Run workflow` on `main`. The workflow:

1. freezes a unique UTC version before compiling anything;
2. builds the three assets in parallel;
3. runs build and artifact checks, including AppImage extraction/smoke;
4. downloads all assets and validates the native package versions;
5. creates a `SHA256SUMS` file, refusing missing/duplicate files;
6. creates the `vVERSION` GitHub Release **only after all steps succeed**.

GitHub Release descriptions are always generated in **English** by
`packaging/release-notes.py` using an English-only template; git commit
messages are linked in a comparison instead of being embedded verbatim
(they may be in Portuguese). Pushes that change packaging perform build
checks but **do not publish**. GitHub Release creation requires the
workflow's scoped `contents: write` permission.

## Validation still required on real desktops

Automated checks cannot prove that GTK/GI, GPU drivers, gamepad, desktop
portals and Gamescope work in every environment. Test Fedora GNOME/Wayland,
CachyOS/Arch (AppImage), KDE Plasma, Debian 13 and package removal/upgrades.
An AppImage built on Debian 13 may not run on older glibc hosts; do not claim
universal compatibility without testing. AppImage packaging uses the upstream
[appimage-builder](https://appimage-builder.readthedocs.io/), not
linuxdeploy-plugin-gtk (which only supports GTK2/3).

No CI job automatically installs/removes Jolven Session on a live host.
