#!/bin/bash
# Exercise actual unit/rule generation in a temporary directory, without root.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source "$ROOT/install.sh"
TEST_DIR=$(mktemp -d)
trap 'rm -rf -- "$TEST_DIR"' EXIT
visudo() { [[ "$1" == -cf ]] && grep -q 'NOPASSWD: /usr/bin/systemctl start arma-server.service, /usr/bin/systemctl stop arma-server.service$' "$2"; }
install() { [[ "$1 $2 $3 $4 $5 $6" == '-o root -g root -m 0440' ]] && cp "$7" "$8"; }
systemctl() { printf '%s\n' "$*" >> "$TEST_DIR/calls"; }
configure_server_control '/home/arma/panel' arma "$TEST_DIR/etc"
grep -q '^User=arma$' "$TEST_DIR/etc/systemd/system/arma-server.service"
grep -q '^KillMode=process$' "$TEST_DIR/etc/systemd/system/arma-panel.service.d/legacy-game.conf"
grep -q '^ExecStart=/usr/bin/python3 "/home/arma/panel/runtime_ops.py" "/home/arma/panel/config.env"$' "$TEST_DIR/etc/systemd/system/arma-server.service.d/panel-control.conf"
[[ "$(cat "$TEST_DIR/calls")" == daemon-reload ]]
echo 'PASS separate service and legacy-game migration generated without restarting game'
printf '# existing custom service\n' > "$TEST_DIR/etc/systemd/system/arma-server.service"
configure_server_control '/custom/panel' arma "$TEST_DIR/etc"
grep -q '^# existing custom service$' "$TEST_DIR/etc/systemd/system/arma-server.service"
grep -q '"/custom/panel/runtime_ops.py"' "$TEST_DIR/etc/systemd/system/arma-server.service.d/panel-control.conf"
echo 'PASS existing service preserved and launcher updated'
if configure_server_control '/home/arma/panel' 'invalid ALL=' "$TEST_DIR/etc"; then exit 1; fi
echo 'PASS invalid sudoers username rejected'
