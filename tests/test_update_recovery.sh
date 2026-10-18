#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")/.."
source ./install.sh
SCRIPT_DIR="$PWD"
# Exercise the real update orchestration with isolated command doubles.
for failure in none copy configure restart health backup; do
    output=$(mktemp)
    set +e
    (
        python3() {
            if [[ "$2" == backup ]]; then
                [[ "$failure" != backup ]] || return 1
                echo /snapshot
            else
                echo RESTORED
            fi
        }
        copy_panel_files() { echo COPIED; [[ "$failure" != copy ]]; }
        configure_server_control() { [[ "$failure" != configure ]]; }
        configure_instance_control() { :; }
        chown() { :; }
        rm() { :; }
        sleep() { :; }
        systemctl() {
            [[ "$1" != restart || "$failure" != restart ]] || return 1
            [[ "$1" != is-active || "$failure" != health ]]
        }
        update_panel_with_recovery /panel arma
    ) > "$output" 2>&1
    result=$?
    set -e
    if [[ "$failure" == none ]]; then
        [[ "$result" == 0 ]]
        ! grep -q RESTORED "$output"
    else
        [[ "$result" != 0 ]]
        if [[ "$failure" == backup ]]; then
            ! grep -q COPIED "$output"
        else
            grep -q RESTORED "$output"
        fi
    fi
    rm "$output"
done
echo 'Update recovery failure-injection tests passed'
