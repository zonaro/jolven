#!/usr/bin/env bash
# Instala o Jolven no usuario atual sem manter uma copia do repositorio.
#
# Modo padrao (binario): baixa o tarball da ultima GitHub Release e extrai
# em $PREFIX (sem compilar nada localmente).
#
#   curl -fsSL https://raw.githubusercontent.com/zonaro/jolven/main/install.sh | bash
#
# Modo source (compila localmente, como antes):
#
#   curl -fsSL .../install.sh | bash -s -- --source
#   CARTRIDGES_FROM_SOURCE=1 bash install.sh
set -Eeuo pipefail

readonly REPOSITORY_URL="${CARTRIDGES_REPOSITORY_URL:-https://github.com/zonaro/jolven.git}"
readonly REPOSITORY_REF="${CARTRIDGES_REF:-main}"
readonly GITHUB_REPOSITORY="${CARTRIDGES_GITHUB_REPOSITORY:-zonaro/jolven}"
readonly INSTALL_PREFIX="${PREFIX:-$HOME/.local}"

MODE="binary"
if [[ ${CARTRIDGES_FROM_SOURCE:-0} == 1 ]]; then
    MODE="source"
fi

usage() {
    printf 'Uso: %s [--binary|--source] [--help]\n' "$(basename -- "$0")"
    printf '\n'
    printf '  --binary   baixa o tarball da ultima release (padrao)\n'
    printf '  --source   clona o repositorio e compila localmente\n'
}

while (($#)); do
    case "$1" in
        --binary) MODE="binary" ;;
        --source) MODE="source" ;;
        -h | --help)
            usage
            exit 0
            ;;
        *)
            printf 'Opcao desconhecida: %s\n' "$1" >&2
            usage >&2
            exit 64
            ;;
    esac
    shift
done

print_path_hint() {
    if [[ ":$PATH:" != *":$INSTALL_PREFIX/bin:"* ]]; then
        printf 'Se necessario, adicione %s/bin ao PATH para usar o comando jolven.\n' \
            "$INSTALL_PREFIX"
    fi
}

install_runtime_packages() {
    local -a packages=("$@")
    local missing=()
    local package
    for package in "${packages[@]}"; do
        rpm -q "$package" >/dev/null 2>&1 || missing+=("$package")
    done
    if ((${#missing[@]})); then
        printf 'Instalando dependencias necessarias...\n'
        sudo dnf install --refresh --assumeyes "${missing[@]}"
    else
        printf 'Todas as dependencias ja estao instaladas.\n'
    fi
}

promote_system_integration() {
    local src_prefix="${1:-$INSTALL_PREFIX}"
    local policy_src_dir="${2:-$src_prefix/share/polkit-1/actions}"
    local dest_libexec="${CARTRIDGES_SYSTEM_LIBEXECDIR:-/usr/libexec}"
    local dest_polkit="${CARTRIDGES_POLKIT_DIR:-/usr/share/polkit-1/actions}"

    if [[ $src_prefix == /usr || $src_prefix == /usr/local ]]; then
        printf 'Prefixo do sistema (%s): helpers e policies ja instalados pelo meson; promocao dispensada.\n' "$src_prefix"
        return 0
    fi

    local sudo_cmd=""
    if [[ ${EUID:-$(id -u)} -ne 0 ]] && [[ $dest_libexec == /usr/* || $dest_polkit == /usr/* ]] && command -v sudo >/dev/null 2>&1; then
        sudo_cmd="sudo"
    fi

    local helper src dest backup
    for helper in jolven-game-mode-setup; do
        src="$src_prefix/libexec/$helper"
        dest="$dest_libexec/$helper"
        if [[ ! -f $src ]]; then
            printf 'Helper nao encontrado em %s; promocao abortada.\n' "$src" >&2
            return 1
        fi
        if [[ -e $dest ]] && ! grep -q 'X-Jolven-Managed=true' "$dest" 2>/dev/null; then
            backup="$dest.bak-$(date +%Y%m%d%H%M%S)"
            printf 'Arquivo alheio em %s; preservado como %s.\n' "$dest" "$backup"
            $sudo_cmd mv -- "$dest" "$backup"
        fi
        $sudo_cmd install -D -m 0755 -- "$src" "$dest"
        printf 'Helper promovido: %s\n' "$dest"
    done

    local spec policy action psrc pdest pbackup
    for spec in \
        "io.github.zonaro.Jolven.GameMode.policy:io.github.zonaro.Jolven.configure-game-mode" \
        "io.github.zonaro.Jolven.Preferences.policy:io.github.zonaro.Jolven.preferences"; do
        policy="${spec%%:*}"
        action="${spec##*:}"
        psrc="$policy_src_dir/$policy"
        pdest="$dest_polkit/$policy"
        if [[ ! -f $psrc ]]; then
            printf 'Policy nao encontrada em %s; promocao abortada.\n' "$psrc" >&2
            return 1
        fi
        if [[ -e $pdest ]] && ! grep -Fq "$action" "$pdest" 2>/dev/null; then
            pbackup="$pdest.bak-$(date +%Y%m%d%H%M%S)"
            printf 'Arquivo alheio em %s; preservado como %s.\n' "$pdest" "$pbackup"
            $sudo_cmd mv -- "$pdest" "$pbackup"
        fi
        $sudo_cmd install -D -m 0644 -- "$psrc" "$pdest"
        printf 'Policy instalada: %s\n' "$pdest"
    done

    # Remove as copias inertes do prefixo do usuario. O search-provider e o
    # jolven-session ficam onde estao, por design (D-Bus e sessao de usuario).
    rm -f -- "$src_prefix/libexec/jolven-game-mode-setup"
    rm -rf -- "$src_prefix/share/polkit-1"

    local failures=0
    local installed exec_path
    for installed in "$dest_polkit"/io.github.zonaro.Jolven.GameMode.policy \
        "$dest_polkit"/io.github.zonaro.Jolven.Preferences.policy; do
        if [[ ! -f $installed ]]; then
            printf 'Verificacao falhou: policy ausente: %s\n' "$installed" >&2
            failures=1
            continue
        fi
        while IFS= read -r exec_path; do
            [[ -n $exec_path ]] || continue
            if [[ ! -x $exec_path ]]; then
                printf 'Verificacao falhou: %s (de %s) nao existe ou nao e executavel.\n' "$exec_path" "$installed" >&2
                failures=1
            elif [[ ${EUID:-$(id -u)} -eq 0 && $(stat -c '%u' -- "$exec_path" 2>/dev/null) != 0 ]]; then
                printf 'Verificacao falhou: %s (de %s) nao pertence a root.\n' "$exec_path" "$installed" >&2
                failures=1
            elif [[ -n "$(find "$exec_path" -perm /022 2>/dev/null)" ]]; then
                printf 'Verificacao falhou: %s (de %s) e gravavel por grupo ou outros.\n' "$exec_path" "$installed" >&2
                failures=1
            elif [[ ${EUID:-$(id -u)} -ne 0 && -w $exec_path ]]; then
                printf 'Verificacao falhou: %s (de %s) e gravavel pelo usuario corrente.\n' "$exec_path" "$installed" >&2
                failures=1
            fi
        done < <(sed -n 's/.*org.freedesktop.policykit.exec.path">\([^<]*\)<.*/\1/p' "$installed")
    done
    if ((failures)); then
        printf 'Integracao de sistema inconsistente; verifique os caminhos acima.\n' >&2
        return 1
    fi
    printf 'Integracao de sistema verificada.\n'
}

install_binary() {
    for command in sudo dnf curl tar sha256sum python3; do
        if ! command -v "$command" >/dev/null 2>&1; then
            printf 'Comando necessario nao encontrado: %s\n' "$command" >&2
            exit 69
        fi
    done

    install_runtime_packages \
        adwaita-icon-theme \
        desktop-file-utils \
        libnice-gstreamer1 \
        gstreamer1-plugins-bad-free \
        gstreamer1-plugins-bad-freeworld \
        gstreamer1-plugins-bad-free-extras \
        gstreamer1-plugin-openh264 \
        gtk4 \
        libadwaita \
        python3-gobject \
        python3-pillow \
        python3-pyyaml \
        python3-requests

    local arch
    arch="$(uname -m)"
    local base_url="https://github.com/$GITHUB_REPOSITORY/releases/latest/download"
    local tarball="jolven-linux-$arch.tar.gz"

    local work_dir
    work_dir="$(mktemp -d -t jolven-install.XXXXXX)"
    # shellcheck disable=SC2064
    trap "rm -rf -- '$work_dir'" EXIT

    printf 'Baixando o Jolven (binario)...\n'
    curl -fsSL -o "$work_dir/$tarball" "$base_url/$tarball"
    curl -fsSL -o "$work_dir/$tarball.sha256" "$base_url/$tarball.sha256"
    curl -fsSL -o "$work_dir/VERSION" "$base_url/VERSION"
    (
        cd -- "$work_dir"
        sha256sum -c -- "$tarball.sha256"
    )
    printf 'Versao: %s\n' "$(cat -- "$work_dir/VERSION")"

    printf 'Instalando em %s...\n' "$INSTALL_PREFIX"
    mkdir -p -- "$INSTALL_PREFIX"
    # O tarball contem a arvore usr/ do build (--prefix=/usr); o launcher e
    # os helpers deduzem o prefix real a partir do proprio caminho.
    tar -xzf "$work_dir/$tarball" -C "$INSTALL_PREFIX" --strip-components=1 usr

    # O servico D-Bus precisa do Exec absoluto com o site-packages relocado.
    local site_dir=""
    local candidate
    for candidate in "$INSTALL_PREFIX"/lib/python3*/site-packages \
        "$INSTALL_PREFIX"/lib64/python3*/site-packages; do
        if [[ -f "$candidate/cartridges/shared.py" ]]; then
            site_dir="$candidate"
            break
        fi
    done
    local service_file="$INSTALL_PREFIX/share/dbus-1/services/io.github.zonaro.Jolven.SearchProvider.service"
    if [[ -n $site_dir && -f $service_file ]]; then
        printf 'Exec=env PYTHONPATH=%s %s/libexec/jolven-search-provider\n' \
            "$site_dir" "$INSTALL_PREFIX" >"$service_file"
    fi

    if command -v glib-compile-schemas >/dev/null 2>&1; then
        glib-compile-schemas "$INSTALL_PREFIX/share/glib-2.0/schemas"
    fi
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$INSTALL_PREFIX/share/applications" || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -f -t "$INSTALL_PREFIX/share/icons/hicolor" 2>/dev/null || true
    fi

    printf '\nJolven instalado com sucesso. Abra-o pelo menu de aplicativos.\n'
    print_path_hint

    promote_system_integration "$INSTALL_PREFIX" "$INSTALL_PREFIX/share/polkit-1/actions"
}

install_source() {
    for command in sudo dnf; do
        if ! command -v "$command" >/dev/null 2>&1; then
            printf 'Comando necessario nao encontrado: %s\n' "$command" >&2
            exit 69
        fi
    done

    readonly -a REQUIRED_PACKAGES=(
        desktop-file-utils
        gcc
        gettext
        git
        gtk4-devel
        libadwaita-devel
        meson
        ninja-build
        python3-gobject
        python3-pillow
        python3-pyyaml
        python3-requests
    )

    install_runtime_packages "${REQUIRED_PACKAGES[@]}"

    local work_dir
    work_dir="$(mktemp -d -t jolven-install.XXXXXX)"
    # shellcheck disable=SC2064
    trap "rm -rf -- '$work_dir'" EXIT

    printf 'Baixando o Jolven...\n'
    git clone --depth 1 --branch "$REPOSITORY_REF" --single-branch \
        "$REPOSITORY_URL" "$work_dir/jolven"

    printf 'Compilando...\n'
    meson setup "$work_dir/jolven/build" "$work_dir/jolven" \
        --prefix="$INSTALL_PREFIX" \
        --buildtype=release \
        -Dprofile=release
    meson compile -C "$work_dir/jolven/build"

    printf 'Instalando em %s...\n' "$INSTALL_PREFIX"
    meson install -C "$work_dir/jolven/build"

    promote_system_integration "$INSTALL_PREFIX" "$work_dir/jolven/build/data"

    printf '\nJolven instalado com sucesso. Abra-o pelo menu de aplicativos.\n'
    print_path_hint
}

# Ensaio da promocao sem tocar no sistema (validacao do issue #42):
# CARTRIDGES_PROMOTE_ONLY=<prefixo> CARTRIDGES_SYSTEM_LIBEXECDIR=<dir> \
#   CARTRIDGES_POLKIT_DIR=<dir> bash install.sh
if [[ -n "${CARTRIDGES_PROMOTE_ONLY:-}" ]]; then
    promote_system_integration "${CARTRIDGES_PROMOTE_ONLY}"
    exit $?
fi

if [[ ${EUID:-$(id -u)} -eq 0 ]]; then
    printf 'Nao execute este instalador como root ou com sudo.\n' >&2
    exit 1
fi

if [[ ! -r /etc/os-release ]]; then
    printf 'Nao foi possivel identificar a distribuicao Linux.\n' >&2
    exit 1
fi

# shellcheck disable=SC1091
. /etc/os-release
if [[ ${ID:-} != fedora ]]; then
    printf 'Este instalador atualmente oferece suporte ao Fedora.\n' >&2
    exit 1
fi

if [[ $MODE == source ]]; then
    install_source
else
    install_binary
fi
