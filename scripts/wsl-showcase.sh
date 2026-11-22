#!/usr/bin/env bash
# Windows reviewer setup inside Ubuntu WSL2. Does not remove containers or PVCs.
set -Eeuo pipefail

say() { printf '\n== %s ==\n' "$*"; }
stop() { printf '\nSETUP NEEDED: %s\n' "$*" >&2; exit 1; }

SOURCE="${1:-}"
[ -n "$SOURCE" ] && [ -d "$SOURCE" ] || stop "Windows source directory not accessible from WSL"
[ -f "$SOURCE/scripts/showcase.sh" ] || stop "Windows checkout has no scripts/showcase.sh"

[ -r /etc/os-release ] || stop "Cannot identify Linux distribution"
# shellcheck disable=SC1091
. /etc/os-release
[ "${ID:-}" = "ubuntu" ] || stop "Install the Ubuntu WSL 2 distribution for the Windows demo"
case "$(uname -r)" in
    *WSL2*|*wsl2*) ;;
    *) stop "WSL 2 is required. In Windows PowerShell run: wsl --list --verbose" ;;
esac
[ "$(id -u)" != "0" ] || stop "Open Ubuntu and configure a normal non-root WSL user first"

export PATH="$HOME/.local/bin:$PATH"
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64) TARGET_ARCH=amd64 ;;
    aarch64) TARGET_ARCH=arm64 ;;
    *) stop "Unsupported WSL CPU architecture: $ARCH" ;;
esac

# Windows Docker Desktop, not a separate WSL Docker Engine.
command -v docker >/dev/null 2>&1 || stop "Open Docker Desktop > Settings > Resources > WSL Integration > enable Ubuntu > Apply & Restart"
if ! timeout 15 docker info >/dev/null 2>&1; then
    stop "Start Docker Desktop, enable its WSL 2 backend and Ubuntu integration, switch to Linux containers, then retry. Do not install another Docker Engine inside Ubuntu."
fi
if ! docker compose version >/dev/null 2>&1; then
    stop "Docker Desktop Compose v2 is unavailable inside Ubuntu. Enable WSL integration in Docker Desktop."
fi
say "Docker Desktop connected from Ubuntu"

# Install missing Ubuntu utilities only after explicit user approval.
missing_packages=()
command -v git >/dev/null 2>&1 || missing_packages+=(git)
command -v curl >/dev/null 2>&1 || missing_packages+=(curl)
command -v python3 >/dev/null 2>&1 || missing_packages+=(python3)
command -v pipx >/dev/null 2>&1 || missing_packages+=(pipx)
command -v sha256sum >/dev/null 2>&1 || missing_packages+=(coreutils)
command -v timeout >/dev/null 2>&1 || missing_packages+=(coreutils)
if ((${#missing_packages[@]} > 0)); then
    say "Ubuntu packages required: ${missing_packages[*]}"
    printf 'Install these missing packages with Ubuntu apt? [y/N] '
    read -r confirm
    case "$confirm" in
        y|Y|yes|YES)
            sudo apt-get update
            sudo apt-get install -y --no-install-recommends "${missing_packages[@]}"
            ;;
        *) stop "Required Ubuntu packages were not installed" ;;
    esac
fi
mkdir -p "$HOME/.local/bin"

# Python 3.14 is installed separately for the current Ubuntu user; system
# Python is never replaced. uv is installed as a user-scoped pipx tool.
if ! command -v python3.14 >/dev/null 2>&1; then
    say "Install user-scoped Python 3.14 (does not replace system Python)"
    if ! command -v uv >/dev/null 2>&1; then
        command -v pipx >/dev/null 2>&1 || stop "pipx missing: sudo apt-get install pipx"
        pipx install uv || stop "Could not install uv via pipx"
    fi
    uv python install 3.14 || stop "Could not download Python 3.14 with uv"
    hash -r
fi
python3.14 -c 'import sys; assert sys.version_info[:2] == (3, 14)' \
    || stop "Python 3.14 executable not found; add ~/.local/bin to PATH"
say "Python 3.14 ready"

# Never execute an unverified remote binary: kind release's GitHub asset
# digest is verified, kubectl matches its official sha256 file.
install_kind() {
    command -v kind >/dev/null 2>&1 && return 0
    say "Install verified kind v0.33.0 for Kubernetes GitOps"
    local filename checksum_line expected temp
    filename="kind-linux-$TARGET_ARCH"
    checksum_line="$(curl -fsSL --retry 2 --connect-timeout 10 --max-time 60 \
        "https://kind.sigs.k8s.io/dl/v0.33.0/${filename}.sha256sum")" \
        || stop "Could not retrieve official kind release checksum"
    expected="${checksum_line%%[[:space:]]*}"
    [[ "$expected" =~ ^[0-9a-f]{64}$ ]] \
        || stop "Invalid official kind SHA256 checksum"
    [[ "$checksum_line" == *"$filename"* ]] \
        || stop "Unexpected kind release asset name"
    temp="$(mktemp "$HOME/.local/bin/.kind-XXXXXX")"
    if ! curl -fsSL --retry 2 --connect-timeout 10 --max-time 180 \
        "https://kind.sigs.k8s.io/dl/v0.33.0/$filename" -o "$temp"; then
        rm -f -- "$temp"
        stop "Could not download kind"
    fi
    if ! printf '%s  %s\n' "$expected" "$temp" | sha256sum -c --status; then
        rm -f -- "$temp"
        stop "kind checksum mismatch"
    fi
    chmod 755 "$temp"
    mv -f -- "$temp" "$HOME/.local/bin/kind"
}

install_kubectl() {
    command -v kubectl >/dev/null 2>&1 && return 0
    say "Install verified kubectl"
    local version checksum downloaded temp
    version="$(curl -fsSL --connect-timeout 10 --max-time 30 https://dl.k8s.io/release/stable.txt)"
    [[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || stop "Invalid Kubernetes stable version metadata"
    checksum="$(curl -fsSL --connect-timeout 10 --max-time 30 "https://dl.k8s.io/release/$version/bin/linux/$TARGET_ARCH/kubectl.sha256")"
    [[ "$checksum" =~ ^[0-9a-f]{64}$ ]] || stop "Invalid kubectl SHA256 metadata"
    temp="$(mktemp "$HOME/.local/bin/.kubectl-XXXXXX")"
    if ! curl -fsSL --retry 2 --connect-timeout 10 --max-time 180 \
        "https://dl.k8s.io/release/$version/bin/linux/$TARGET_ARCH/kubectl" -o "$temp"; then
        rm -f -- "$temp"
        stop "Could not download kubectl"
    fi
    if ! printf '%s  %s\n' "$checksum" "$temp" | sha256sum -c --status; then
        rm -f -- "$temp"
        stop "kubectl checksum mismatch"
    fi
    chmod 755 "$temp"
    mv -f -- "$temp" "$HOME/.local/bin/kubectl"
}

install_kind || stop "kind setup failed. See https://kind.sigs.k8s.io/docs/user/quick-start/"
install_kubectl || stop "kubectl setup failed. See https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/"
command -v kind >/dev/null 2>&1 || stop "kind executable is not in PATH"
command -v kubectl >/dev/null 2>&1 || stop "kubectl executable is not in PATH"
say "Kubernetes tools ready"

# Store code in Linux filesystem for reliable Compose volumes and file modes.
# Source is the Windows checkout; no second GitHub login is required.
DEST="$HOME/.local/share/opsboard-windows/ci-cd-lab"
if [ ! -d "$DEST/.git" ]; then
    [ ! -e "$DEST" ] || stop "Target path exists but is not an OpsBoard Git checkout: $DEST"
    mkdir -p "$(dirname "$DEST")"
    if [ -d "$SOURCE/.git" ] || [ -f "$SOURCE/.git" ]; then
        say "Copy repository into the Ubuntu filesystem using a local Git clone"
        git clone --quiet --no-hardlinks -- "$SOURCE" "$DEST" \
            || stop "Could not clone Windows Git checkout into Ubuntu"
        git -C "$DEST" checkout -q main || stop "No main branch found in Windows clone"
    else
        say "Download the repository into Ubuntu (source was a ZIP, not a Git checkout)"
        git clone --quiet --depth 1 https://github.com/Mishkaaass/ci-cd-lab.git "$DEST" \
            || stop "Cannot clone repository. Use the Git checkout method or check access."
    fi
    git -C "$DEST" remote set-url origin https://github.com/Mishkaaass/ci-cd-lab.git
else
    [ -z "$(git -C "$DEST" status --porcelain)" ] \
        || stop "Ubuntu OpsBoard checkout has local changes; resolve them before updating: $DEST"
    if [ -d "$SOURCE/.git" ] || [ -f "$SOURCE/.git" ]; then
        say "Fast-forward Ubuntu checkout from the Windows Git source"
        git -C "$DEST" fetch --quiet --no-tags "$SOURCE" refs/heads/main \
            || stop "Unable to read main from Windows Git checkout"
    else
        say "Fast-forward Ubuntu checkout from GitHub"
        git -C "$DEST" fetch --quiet --no-tags origin refs/heads/main \
            || stop "Cannot fetch main from GitHub"
    fi
    [ "$(git -C "$DEST" branch --show-current)" = "main" ] \
        || stop "Ubuntu OpsBoard checkout is not on main"
    git -C "$DEST" merge --ff-only FETCH_HEAD \
        || stop "Ubuntu checkout diverged; no force reset or data deletion performed"
fi

[ -f "$DEST/scripts/showcase.sh" ] || stop "OpsBoard showcase.sh is missing from Ubuntu checkout"
say "Ready to launch"
printf 'Repository: %s\n' "$DEST"
printf 'Windows browser: http://127.0.0.1:18002/\n'
printf 'Private Viewer token path (inside Ubuntu): ~/.config/ci-cd-lab/unified-console/viewer.token\n'
printf 'Stop with Ctrl+C. Volumes and PVC are preserved.\n'
cd "$DEST"
exec bash scripts/showcase.sh
