#!/bin/bash
# Verify generated files without modifying host services or sudo permissions.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source "$ROOT/install.sh"
TEST_DIR=$(mktemp -d)
trap 'rm -rf -- "$TEST_DIR"' EXIT
visudo() { [[ "$1" == -cf ]] && grep -q 'NOPASSWD: /etc/arma-panel/instance-control.py$' "$2"; }
install() { [[ "$1 $2 $3 $4 $5" == '-o root -g root -m' ]] && cp "$7" "$8"; }
systemctl() { printf '%s\n' "$*" >> "$TEST_DIR/calls"; }
configure_instance_control '/home/arma/panel' arma "$TEST_DIR/etc"
grep -q '^User=arma$' "$TEST_DIR/etc/systemd/system/arma-server@.service"
grep -q '^ExecStart=/usr/bin/python3 "/home/arma/panel/runtime_ops.py" "/home/arma/panel/config.env" %i$' "$TEST_DIR/etc/systemd/system/arma-server@.service"
grep -q '^Restart=on-failure$' "$TEST_DIR/etc/systemd/system/arma-server@.service"
[[ -s "$TEST_DIR/etc/arma-panel/instance-control.py" ]]
[[ "$(head -n 1 "$TEST_DIR/etc/arma-panel/instance-control.py")" == '#!/usr/bin/python3' ]]
[[ "$(cat "$TEST_DIR/calls")" == daemon-reload ]]
if configure_instance_control '/home/arma/panel' 'invalid ALL=' "$TEST_DIR/etc"; then exit 1; fi
if configure_instance_control '/home/arma/%bad' arma "$TEST_DIR/etc"; then exit 1; fi
echo 'PASS instance template and restricted helper generated without starting services'
