#!/bin/bash
# ============================================================
# Arma Reforger Panel Installer
# https://github.com/aumik116/arma-reforger-panel-aumik-edition
# Original project by Mateusz Gołębiewski:
# https://github.com/mateuszgolebiewski-code/arma-reforger-panel
#
# Modes:
#   sudo bash install.sh              — install panel and prepare SteamCMD
#   sudo bash install.sh --panel-only — alias for panel installation
#   sudo bash install.sh --update     — update panel files only
# ============================================================

set -e

# Keep both fresh installs and updates on the same file-copy path.
PANEL_PY_FILES=(app.py storage_usage.py notifications.py workshop.py panel_features.py player_query.py runtime_ops.py network_status.py file_manager.py config_editor.py config_backups.py mod_metadata.py server_software.py persistence_saves.py armahq_compare.py mod_validation.py legacy_api.py server_registry.py instance_runtime.py server_provisioning.py instance_control.py update_recovery.py scheduler.py operator_tools.py)

copy_panel_files() {
    local destination="$1" file
    for file in "${PANEL_PY_FILES[@]}" index.html login.html setup.html servers.html; do
        if [[ ! -f "$SCRIPT_DIR/$file" ]]; then
            echo "ERROR: Required panel file $file is missing from the checkout." >&2
            return 1
        fi
    done
    if [[ ! -d "$SCRIPT_DIR/static" ]] || ! compgen -G "$SCRIPT_DIR/static/*" > /dev/null; then
        echo "ERROR: Panel static files are missing from the checkout." >&2
        return 1
    fi
    mkdir -p "$destination/static"
    for file in "${PANEL_PY_FILES[@]}" index.html login.html setup.html servers.html; do
        cp "$SCRIPT_DIR/$file" "$destination/"
    done
    cp "$SCRIPT_DIR/static/"* "$destination/static/"
}

# These helpers can be sourced by tests without running the installer.
run_steamcmd_logged() {
    local log_file="$1"
    shift
    local -a result
    # Give SteamCMD its own working directory and the target user's HOME.
    # Capture both statuses: tee must not hide a failed SteamCMD invocation.
    if sudo -H -u "$ARMA_USER" bash -c \
        'cd "$1" || exit 1; shift; exec ./steamcmd.sh "$@"' \
        _ "$STEAM_DIR" "$@" 2>&1 | tee "$log_file"; then
        result=("${PIPESTATUS[@]}")
    else
        result=("${PIPESTATUS[@]}")
    fi
    if (( result[1] != 0 )); then
        echo "ERROR: Could not save SteamCMD output to $log_file" >&2
        return 1
    fi
    return "${result[0]}"
}

prepare_steamcmd() {
    local attempts=3 attempt status log_file log_dir ready=0
    mkdir -p "$STEAM_DIR/install-logs" || return 1
    log_dir=$(mktemp -d "$STEAM_DIR/install-logs/run-XXXXXXXX") || return 1
    echo "SteamCMD diagnostics: $log_dir"

    # Let SteamCMD finish replacing/restarting itself before asking it to
    # install the game. A self-update can exit nonzero; retry in a new process.
    for ((attempt=1; attempt<=attempts; attempt++)); do
        echo "Preparing SteamCMD (attempt $attempt/$attempts)..."
        if run_steamcmd_logged "$log_dir/bootstrap-$attempt.log" +quit; then
            ready=1
            break
        else
            status=$?
            echo "SteamCMD bootstrap exited with status $status."
        fi
        if (( attempt < attempts )); then sleep 5; fi
    done
    if (( ! ready )); then
        echo "ERROR: SteamCMD could not finish starting after $attempts attempts." >&2
        echo "Logs: $log_dir" >&2
        return 1
    fi

    return 0
}

configure_server_control() {
    local panel_dir="$1" panel_user="$2" rule
    local config_root="${3:-/etc}"
    # Only these two exact operations are privileged, never arbitrary commands.
    [[ "$panel_user" =~ ^[a-zA-Z_][a-zA-Z0-9_-]*\$?$ ]] || return 1
    command -v visudo >/dev/null || { echo "ERROR: Install sudo first." >&2; return 1; }
    mkdir -p "${config_root}/sudoers.d" "${config_root}/systemd/system/arma-server.service.d" "${config_root}/systemd/system/arma-panel.service.d"
    rule=$(mktemp)
    printf '%s ALL=(root) NOPASSWD: /usr/bin/systemctl start arma-server.service, /usr/bin/systemctl stop arma-server.service\n' "$panel_user" > "$rule"
    visudo -cf "$rule" || { rm -f "$rule"; return 1; }
    install -o root -g root -m 0440 "$rule" "${config_root}/sudoers.d/arma-panel-control"
    rm -f "$rule"
    if [[ ! -f ${config_root}/systemd/system/arma-server.service ]]; then
        cat > "${config_root}/systemd/system/arma-server.service" <<EOF
[Unit]
Description=Arma Reforger Dedicated Server
After=network.target
[Service]
Type=simple
User=${panel_user}
Restart=on-failure
RestartSec=10
[Install]
WantedBy=multi-user.target
EOF
    fi
    cat > "${config_root}/systemd/system/arma-server.service.d/panel-control.conf" <<EOF
[Service]
User=${panel_user}
ExecStart=
ExecStart=/usr/bin/python3 "${panel_dir}/runtime_ops.py" "${panel_dir}/config.env"
TimeoutStopSec=120
EOF
    # Preserve a legacy panel-launched game during this and future panel updates.
    # New launches use arma-server.service and its normal control-group cleanup.
    cat > "${config_root}/systemd/system/arma-panel.service.d/legacy-game.conf" <<EOF
[Service]
KillMode=process
EOF
    systemctl daemon-reload
}

configure_instance_control() {
    local panel_dir="$1" panel_user="$2" config_root="${3:-/etc}" source_dir rule
    [[ "$panel_user" =~ ^[a-zA-Z_][a-zA-Z0-9_-]*\$?$ ]] || return 1
    [[ "$panel_dir" == /* && "$panel_dir" != *[\"\%\$\\]* && "$panel_dir" != *$'\n'* ]] || return 1
    source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    mkdir -p "$config_root/arma-panel" "$config_root/systemd/system" "$config_root/sudoers.d"
    install -o root -g root -m 0755 "$source_dir/instance_control.py" "$config_root/arma-panel/instance-control.py"
    rule=$(mktemp)
    printf '%s ALL=(root) NOPASSWD: /etc/arma-panel/instance-control.py\n' "$panel_user" > "$rule"
    visudo -cf "$rule" || { rm -f "$rule"; return 1; }
    install -o root -g root -m 0440 "$rule" "$config_root/sudoers.d/arma-panel-instances"
    rm -f "$rule"
    cat > "$config_root/systemd/system/arma-server@.service" <<EOF
[Unit]
Description=Arma Reforger instance %i
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=${panel_user}
ExecStart=/usr/bin/python3 "${panel_dir}/runtime_ops.py" "${panel_dir}/config.env" %i
Restart=on-failure
RestartSec=10
TimeoutStopSec=120
UMask=0077
[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
}

update_panel_with_recovery() (
    set -Ee
    local panel_dir="$1" panel_user="$2" snapshot
    snapshot=$(python3 "$SCRIPT_DIR/update_recovery.py" backup "$panel_dir" "$SCRIPT_DIR")
    echo "Recovery snapshot: $snapshot"
    rollback_update() {
        trap - ERR
        set +e
        echo "ERROR: Update failed. Restoring installed panel and service files." >&2
        if python3 "$SCRIPT_DIR/update_recovery.py" restore "$snapshot"; then
            systemctl daemon-reload
            systemctl restart arma-panel
            sleep 2
            if systemctl is-active --quiet arma-panel; then
                echo "Previous panel restored. Recovery snapshot: $snapshot" >&2
            else
                echo "ERROR: Files restored but panel is offline. Inspect journalctl -u arma-panel." >&2
            fi
        else
            echo "ERROR: Automatic restoration failed. Keep snapshot: $snapshot" >&2
        fi
        exit 1
    }
    trap rollback_update ERR
    copy_panel_files "$panel_dir"
    rm -f "$panel_dir/save_library.py" "$panel_dir/static/saves.js"
    local file
    for file in "${PANEL_PY_FILES[@]}" index.html login.html setup.html servers.html; do
        chown "$panel_user:$panel_user" "$panel_dir/$file"
    done
    chown "$panel_user:$panel_user" "$panel_dir/static" "$panel_dir/static/"*
    if ! grep -q "^PANEL_MODE=manager$" "$panel_dir/config.env"; then
        configure_server_control "$panel_dir" "$panel_user"
    fi
    configure_instance_control "$panel_dir" "$panel_user"
    systemctl restart arma-panel
    sleep 2
    systemctl is-active --quiet arma-panel
    trap - ERR
)

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then return 0; fi

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE=manager
case "${1:-}" in
    ""|--panel-only) ;;
    --update) MODE=update ;;
    *) echo "Usage: sudo bash install.sh [--update]" >&2; exit 1 ;;
esac
[[ "$EUID" == 0 ]] || { echo "Run with sudo bash install.sh" >&2; exit 1; }
[[ "$(uname -m)" == x86_64 ]] || { echo "Requires x86_64 Linux." >&2; exit 1; }
if [[ "$MODE" == "update" ]]; then
    echo -e "${YELLOW}Updating panel files...${NC}"
    EXISTING_USER=$(systemctl show arma-panel.service --property=User --value)
    PANEL_DIR_EXISTING=$(systemctl show arma-panel.service --property=WorkingDirectory --value)
    if [[ -z "$EXISTING_USER" || "$PANEL_DIR_EXISTING" != /* || ! -d "$PANEL_DIR_EXISTING" || ! -f "$PANEL_DIR_EXISTING/config.env" ]]; then
        echo "ERROR: Cannot locate installed panel service and config.env." >&2
        exit 1
    fi
    update_panel_with_recovery "$PANEL_DIR_EXISTING" "$EXISTING_USER"
    echo -e "${GREEN}✓ Panel updated and restarted.${NC}"
    echo ""
    exit 0
fi


echo "Install management panel. Create game servers in the browser after installation."
read -r -p "Service user [arma]: " ARMA_USER
ARMA_USER="${ARMA_USER:-arma}"
[[ "$ARMA_USER" =~ ^[a-z_][a-z0-9_-]*$ && "$ARMA_USER" != root ]] || { echo "Invalid service user." >&2; exit 1; }
ARMA_HOME=$(getent passwd "$ARMA_USER" | cut -d: -f6)
ARMA_HOME="${ARMA_HOME:-/home/$ARMA_USER}"
PANEL_DIR="$ARMA_HOME/panel"
STEAM_DIR="$ARMA_HOME/steamcmd"
if [[ -f "$PANEL_DIR/config.env" ]] || systemctl cat arma-panel.service >/dev/null 2>&1; then
    echo "An installation already exists. Use sudo bash install.sh --update." >&2
    exit 1
fi
[[ "$SCRIPT_DIR" != "$PANEL_DIR" ]] || { echo "Run from a separate checkout." >&2; exit 1; }
read -r -s -p "Panel admin password (10-72 bytes): " PANEL_PASSWORD
echo
[[ ${#PANEL_PASSWORD} -ge 10 ]] || { echo "Password too short." >&2; exit 1; }
read -r -p "Panel TCP port [8888]: " PANEL_PORT
PANEL_PORT="${PANEL_PORT:-8888}"
[[ "$PANEL_PORT" =~ ^[0-9]{4,5}$ ]] && ((10#$PANEL_PORT >= 1024 && 10#$PANEL_PORT <= 65535)) || { echo "Invalid panel port." >&2; exit 1; }
id "$ARMA_USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$ARMA_USER"
apt-get update -qq
apt-get install -y -qq python3 python3-flask python3-bcrypt curl ca-certificates tar sudo binutils lib32gcc-s1 lib32stdc++6
PANEL_PASSWORD_HASH=$(printf '%s' "$PANEL_PASSWORD" | python3 -c 'import bcrypt,sys; password=sys.stdin.buffer.read(); assert 10 <= len(password) <= 72, "Password must be 10-72 bytes"; print(bcrypt.hashpw(password,bcrypt.gensalt()).decode())')
unset PANEL_PASSWORD
mkdir -p "$STEAM_DIR"
if [[ ! -f "$STEAM_DIR/steamcmd.sh" ]]; then
    STEAM_ARCHIVE=$(mktemp "$STEAM_DIR/download-XXXXXXXX.tar.gz")
    curl -qfSL --retry 3 --connect-timeout 30 https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz -o "$STEAM_ARCHIVE"
    tar xzf "$STEAM_ARCHIVE" -C "$STEAM_DIR"
    rm -f -- "$STEAM_ARCHIVE"
fi
chown -R "$ARMA_USER:$ARMA_USER" "$STEAM_DIR"
prepare_steamcmd
copy_panel_files "$PANEL_DIR"
mkdir -p "$PANEL_DIR/instances"
chmod 700 "$PANEL_DIR/instances"
cat > "$PANEL_DIR/config.env" <<EOF
PANEL_PASSWORD_HASH=${PANEL_PASSWORD_HASH}
PANEL_PORT=${PANEL_PORT}
PANEL_MODE=manager
INSTANCE_ROOT=${PANEL_DIR}/instances
STEAMCMD_PATH=${STEAM_DIR}/steamcmd.sh
EOF
chmod 600 "$PANEL_DIR/config.env"
chown -R "$ARMA_USER:$ARMA_USER" "$PANEL_DIR"
cat > /etc/systemd/system/arma-panel.service <<EOF
[Unit]
Description=Arma Reforger Management Panel
After=network.target

[Service]
Type=simple
User=${ARMA_USER}
WorkingDirectory=${PANEL_DIR}
ExecStart=/usr/bin/python3 ${PANEL_DIR}/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
configure_instance_control "$PANEL_DIR" "$ARMA_USER"
systemctl daemon-reload
systemctl enable arma-panel
systemctl restart arma-panel
sleep 2
systemctl is-active --quiet arma-panel
PANEL_ADDRESS=$(hostname -I | awk '{print $1}')
echo "Panel installed: http://${PANEL_ADDRESS:-YOUR_VM_IP}:${PANEL_PORT}"
echo "Sign in as admin, then create your first server. It will start after installation."
echo "Manage firewall/router rules yourself for the panel TCP port and each server's game/query UDP ports."
echo "Updates: git pull && sudo bash install.sh --update"
