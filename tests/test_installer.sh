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
    [[ "$*" == *'+force_install_dir '*'+login anonymous +app_update 1874900 validate +quit' ]] || return 93
    local count=0
    [[ ! -f "$STEAM_DIR/download-count" ]] || read -r count < "$STEAM_DIR/download-count"
    count=$((count + 1))
    printf '%s\n' "$count" > "$STEAM_DIR/download-count"
    case "$CASE" in
        missing_then_success)
            if ((count == 1)); then
                echo "ERROR! Failed to install app '1874900' (Missing configuration)"
                return 8
            fi ;;
        permanent_failure|stale_binary)
            echo "ERROR! Failed to install app '1874900' (Missing configuration)"
            return 8 ;;
        zero_exit_failure)
            echo "ERROR! Failed to install app '1874900' (Missing configuration)"
            return 0 ;;
        missing_marker)
            echo 'SteamCMD exited without installing anything'
            return 0 ;;
    esac
    if [[ "$CASE" != missing_binary && "$CASE" != empty_binary ]]; then
        printf '#!/bin/sh\nexit 0\n' > "$SERVER_DIR/$ARMA_BINARY"
        chmod +x "$SERVER_DIR/$ARMA_BINARY"
    fi
    if [[ "$CASE" == up_to_date ]]; then
        echo "Success! App '1874900' already up to date."
    elif [[ "$CASE" == wrong_app ]]; then
        echo "Success! App '1007' fully installed."
    else
        echo "Success! App '1874900' fully installed."
    fi
    [[ "$CASE" != nonzero_success ]] || return 7
}
sleep() { :; }

check() (
    CASE="$1"
    local expected="$2" expected_boots="$3" expected_downloads="$4"
    STEAM_DIR="$TEST_DIR/$CASE/steam cmd"
    SERVER_DIR="$TEST_DIR/$CASE/game server"
    mkdir -p "$STEAM_DIR" "$SERVER_DIR"
    if [[ "$CASE" == stale_binary || "$CASE" == missing_marker ]]; then
        printf '#!/bin/sh\nexit 0\n' > "$SERVER_DIR/$ARMA_BINARY"
        chmod +x "$SERVER_DIR/$ARMA_BINARY"
    elif [[ "$CASE" == empty_binary ]]; then
        touch "$SERVER_DIR/$ARMA_BINARY"
        chmod +x "$SERVER_DIR/$ARMA_BINARY"
    fi
    local result=0
    # A plain call in a child with errexit verifies installer continuation.
    (set -e; download_arma_server; touch "$STEAM_DIR/continued") > "$STEAM_DIR/output" 2>&1 &
    local child=$!
    wait "$child" || result=$?
    if [[ "$result" != "$expected" ]]; then
        cat "$STEAM_DIR/output"
        echo "FAIL $CASE: expected $expected, got $result" >&2
        exit 1
    fi
    [[ "$(cat "$STEAM_DIR/boot-count")" == "$expected_boots" ]]
    local downloads=0
    [[ ! -f "$STEAM_DIR/download-count" ]] || read -r downloads < "$STEAM_DIR/download-count"
    [[ "$downloads" == "$expected_downloads" ]]
    if (( expected != 0 )); then
        [[ ! -f "$STEAM_DIR/continued" ]]
        ! grep -q 'download verified' "$STEAM_DIR/output"
    else
        [[ -f "$STEAM_DIR/continued" ]]
        grep -q 'download verified' "$STEAM_DIR/output"
    fi
    local logs
    logs=$(find "$STEAM_DIR/install-logs" -name '*.log' | wc -l)
    [[ "$logs" -eq $((expected_boots + expected_downloads)) ]]
    echo "PASS $CASE"
)

check first_success 0 1 1
check self_update 0 2 1
check missing_then_success 0 1 2
check up_to_date 0 1 1
check bootstrap_fail 1 3 0
check permanent_failure 1 1 3
check zero_exit_failure 1 1 3
check stale_binary 1 1 3
check missing_marker 1 1 3
check missing_binary 1 1 3
check empty_binary 1 1 3
check wrong_app 1 1 3
check nonzero_success 1 1 3
echo 'All installer retry and verification tests passed.'
