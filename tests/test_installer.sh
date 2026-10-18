#!/bin/bash
# Run with bash tests/test_installer.sh. No root, network or Steam download needed.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source "$ROOT/install.sh"
# The bundled Windows Git shell omits tee/chmod. Linux runs use the real tools;
# these test-only shims allow the same simulated cases to run on that shell.
case "$(uname -s)" in
    MINGW*|MSYS*)
        if ! command -v tee >/dev/null; then
            tee() {
                local line
                : > "$1" || return 1
                while IFS= read -r line || [[ -n "$line" ]]; do
                    printf '%s\n' "$line"
                    printf '%s\n' "$line" >> "$1" || return 1
                done
            }
        fi
        if ! command -v chmod >/dev/null; then chmod() { :; }; fi
        ;;
esac
TEST_DIR=$(mktemp -d)
trap 'rm -rf -- "$TEST_DIR"' EXIT
ARMA_USER=arma
ARMA_APP_ID=1874900
ARMA_BINARY=ArmaReforgerServer

# Test the real pipeline/status handling with a simulated sudo + SteamCMD.
# In particular, tee returns zero even when this command returns nonzero.
sudo() {
    [[ "$1" == -H && "$2" == -u && "$3" == arma && "$4" == bash && "$5" == -c ]] || return 90
    [[ "$6" == 'cd "$1" || exit 1; shift; exec ./steamcmd.sh "$@"' ]] || return 91
    [[ "$7" == _ && "$8" == "$STEAM_DIR" ]] || return 92
    shift 8
    printf '%s\n' "$*" >> "$STEAM_DIR/calls"
    if [[ "$*" == '+quit' ]]; then
        local boot_count=0
        [[ ! -f "$STEAM_DIR/boot-count" ]] || read -r boot_count < "$STEAM_DIR/boot-count"
        boot_count=$((boot_count + 1))
        printf '%s\n' "$boot_count" > "$STEAM_DIR/boot-count"
        if [[ "$CASE" == bootstrap_fail || ( "$CASE" == self_update && "$boot_count" == 1 ) ]]; then
            echo 'Restarting SteamCMD after self-update'
            return 7
        fi
        echo 'SteamCMD ready'
        return 0
    fi
    return 93
}
sleep() { :; }
for CASE in success self_update bootstrap_fail; do
    STEAM_DIR="$TEST_DIR/$CASE"
    mkdir -p "$STEAM_DIR"
    if prepare_steamcmd; then
        [[ "$CASE" != bootstrap_fail ]] || exit 1
    else
        [[ "$CASE" == bootstrap_fail ]] || exit 1
    fi
    count=$(wc -l < "$STEAM_DIR/calls")
    case "$CASE" in
        success) [[ "$count" == 1 ]] ;;
        self_update) [[ "$count" == 2 ]] ;;
        bootstrap_fail) [[ "$count" == 3 ]] ;;
    esac
    ! grep -q app_update "$STEAM_DIR/calls"
    compgen -G "$STEAM_DIR/install-logs/*/bootstrap-1.log" >/dev/null
done
echo "Panel-only SteamCMD preparation tests passed."
