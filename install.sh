#!/bin/bash
# ============================================================
# Arma Reforger Panel Installer
# https://github.com/aumik116/arma-reforger-panel-aumik-edition
# Original project by Mateusz Gołębiewski:
# https://github.com/mateuszgolebiewski-code/arma-reforger-panel
#
# Modes:
#   sudo bash install.sh              — full install (SteamCMD + server + panel)
#   sudo bash install.sh --panel-only — install panel only (server already exists)
#   sudo bash install.sh --update     — update panel files only
# ============================================================

set -e

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

download_arma_server() {
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

    for ((attempt=1; attempt<=attempts; attempt++)); do
        log_file="$log_dir/download-$attempt.log"
        echo "Installing Arma server (attempt $attempt/$attempts)..."
        status=0
        if run_steamcmd_logged "$log_file" \
            +@ShutdownOnFailedCommand 1 +@NoPromptForPassword 1 \
            +@sSteamCmdForcePlatformType linux \
            +force_install_dir "$SERVER_DIR" \
            +login anonymous +app_update "$ARMA_APP_ID" validate +quit; then
            status=0
        else
            status=$?
        fi
        # A zero exit or an old binary alone does not prove this download worked.
        if (( status == 0 )) \
            && grep -Eq "Success! App '$ARMA_APP_ID' (fully installed|already up to date)" "$log_file" \
            && ! grep -q 'ERROR!' "$log_file" \
            && [[ -s "$SERVER_DIR/$ARMA_BINARY" && -x "$SERVER_DIR/$ARMA_BINARY" ]]; then
            echo "Arma server download verified. Logs: $log_dir"
            return 0
        fi
        echo "Download not verified (SteamCMD exit status: $status)."
        if grep -qi 'Missing configuration' "$log_file"; then
            echo "Steam could not resolve the app configuration; retrying with a fresh SteamCMD process."
        fi
        if (( attempt < attempts )); then
            echo "Retrying in 10 seconds; downloaded files will be reused."
            sleep 10
        fi
    done
    echo "ERROR: Arma server installation failed after $attempts attempts." >&2
    echo "The installer has stopped before writing configuration or starting services." >&2
    echo "Keep the logs in $log_dir for diagnosis. Check Steam connectivity and available disk space." >&2
    return 1
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

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then return 0; fi

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

# ── Defaults ──────────────────────────────────────────────────────────────────
ARMA_USER="arma"
ARMA_HOME="/home/arma"
STEAM_DIR="/home/arma/steamcmd"
SERVER_DIR="/home/arma/server"
SERVER_CONFIG="/home/arma/server/config.json"
LOG_DIR="/home/arma/.config/ArmaReforger/logs"
PANEL_DIR="/home/arma/panel"
PANEL_PORT="8888"
ARMA_APP_ID="1874900"
ARMA_BINARY="ArmaReforgerServer"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MODE="full"
if [[ "$1" == "--panel-only" ]]; then MODE="panel"; fi
if [[ "$1" == "--update" ]];      then MODE="update"; fi

# ── Header ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${CYAN}Arma Reforger Panel${NC}"
echo "github.com/aumik116/arma-reforger-panel-aumik-edition"
echo "Based on the original panel by Mateusz Gołębiewski."
echo "Developed with AI assistance using OpenAI Codex."
echo ""

if [[ "$MODE" == "full" ]];   then echo -e "  Mode: ${GREEN}Full install${NC} (SteamCMD + Arma server + Panel)"; fi
if [[ "$MODE" == "panel" ]];  then echo -e "  Mode: ${YELLOW}Panel only${NC} (skip SteamCMD and server download)"; fi
if [[ "$MODE" == "update" ]]; then echo -e "  Mode: ${CYAN}Update${NC} (panel files only)"; fi
echo ""

# ── Root check ────────────────────────────────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}ERROR: Please run as root: sudo bash install.sh${NC}"
    exit 1
fi

# ── OS check ──────────────────────────────────────────────────────────────────
if ! grep -qi "ubuntu" /etc/os-release 2>/dev/null; then
    echo -e "${YELLOW}WARNING: This installer targets Ubuntu and requires Python 3.10+.${NC}"
    read -p "  Continue anyway? [y/N]: " CONTINUE
    [[ "$CONTINUE" =~ ^[Yy]$ ]] || exit 1
fi

# ── Disk space check ──────────────────────────────────────────────────────────
if [[ "$MODE" == "full" ]]; then
    FREE_GB=$(df / | awk 'NR==2 {printf "%d", $4/1024/1024}')
    if [ "$FREE_GB" -lt 20 ]; then
        echo -e "${RED}ERROR: Not enough disk space.${NC}"
        echo -e "  Available: ${FREE_GB} GB — Required: at least 20 GB"
        echo -e "  (Arma Reforger server is ~15 GB)"
        exit 1
    fi
    echo -e "  ${GREEN}✓${NC} Disk space: ${FREE_GB} GB available"
fi

# ── UPDATE mode ───────────────────────────────────────────────────────────────
if [[ "$MODE" == "update" ]]; then
    echo -e "${YELLOW}Updating panel files...${NC}"
    EXISTING_USER=$(systemctl show arma-panel.service --property=User --value)
    PANEL_DIR_EXISTING=$(systemctl show arma-panel.service --property=WorkingDirectory --value)
    if [[ -z "$EXISTING_USER" || "$PANEL_DIR_EXISTING" != /* || ! -d "$PANEL_DIR_EXISTING" || ! -f "$PANEL_DIR_EXISTING/config.env" ]]; then
        echo "ERROR: Cannot locate installed panel service and config.env." >&2
        exit 1
    fi
    cp "$SCRIPT_DIR/app.py"     "$PANEL_DIR_EXISTING/"
    cp "$SCRIPT_DIR/panel_features.py" "$PANEL_DIR_EXISTING/"
    cp "$SCRIPT_DIR/player_query.py" "$PANEL_DIR_EXISTING/"
    cp "$SCRIPT_DIR/runtime_ops.py" "$PANEL_DIR_EXISTING/"
    cp "$SCRIPT_DIR/config_editor.py" "$PANEL_DIR_EXISTING/"
    cp "$SCRIPT_DIR/mod_metadata.py" "$PANEL_DIR_EXISTING/"
    cp "$SCRIPT_DIR/server_software.py" "$PANEL_DIR_EXISTING/"
    rm -f "$PANEL_DIR_EXISTING/save_library.py" "$PANEL_DIR_EXISTING/static/saves.js"
    cp "$SCRIPT_DIR/index.html" "$PANEL_DIR_EXISTING/"
    cp "$SCRIPT_DIR/login.html" "$PANEL_DIR_EXISTING/"
    cp "$SCRIPT_DIR/static/"*   "$PANEL_DIR_EXISTING/static/"
    chown -R "$EXISTING_USER:$EXISTING_USER" "$PANEL_DIR_EXISTING"
    configure_server_control "$PANEL_DIR_EXISTING" "$EXISTING_USER"
    systemctl restart arma-panel
    echo -e "${GREEN}✓ Panel updated and restarted.${NC}"
    echo ""
    exit 0
fi

# ── Collect configuration ─────────────────────────────────────────────────────
echo -e "${BOLD}━━━ Configuration ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

if [[ "$MODE" == "full" ]]; then
    read -p "  System user for Arma [arma]: " INPUT_USER
    ARMA_USER="${INPUT_USER:-arma}"
    ARMA_HOME="/home/$ARMA_USER"
    STEAM_DIR="$ARMA_HOME/steamcmd"
    SERVER_DIR="$ARMA_HOME/server"
    SERVER_CONFIG="$SERVER_DIR/config.json"
    LOG_DIR="$ARMA_HOME/.config/ArmaReforger/logs"
    PANEL_DIR="$ARMA_HOME/panel"
    echo ""
    echo -e "  ${CYAN}Game server settings:${NC}"
    read -p "  Server name [My Arma Reforger Server]: " SERVER_NAME
    SERVER_NAME="${SERVER_NAME:-My Arma Reforger Server}"
    read -p "  Game password (leave empty for public): " GAME_PASSWORD
    read -p "  Admin password: " ADMIN_PASSWORD
    while [ -z "$ADMIN_PASSWORD" ]; do
        echo -e "  ${RED}Admin password cannot be empty.${NC}"
        read -p "  Admin password: " ADMIN_PASSWORD
    done
    read -p "  Max players [32]: " MAX_PLAYERS
    MAX_PLAYERS="${MAX_PLAYERS:-32}"
    read -p "  Game port [2001]: " GAME_PORT
    GAME_PORT="${GAME_PORT:-2001}"
    read -p "  Public IP (leave empty to auto-detect): " PUBLIC_IP
    if [ -z "$PUBLIC_IP" ]; then
        PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || curl -s api.ipify.org 2>/dev/null || echo "YOUR_SERVER_IP")
        echo -e "  ${DIM}Auto-detected: $PUBLIC_IP${NC}"
    fi
fi

echo ""
echo -e "  ${CYAN}Panel settings:${NC}"
read -p "  Panel web password: " PANEL_PASSWORD
while [ -z "$PANEL_PASSWORD" ]; do
    echo -e "  ${RED}Panel password cannot be empty.${NC}"
    read -p "  Panel web password: " PANEL_PASSWORD
done
read -p "  Panel port [8888]: " INPUT_PORT
PANEL_PORT="${INPUT_PORT:-8888}"
read -p "  Max FPS cap [60]: " MAX_FPS
MAX_FPS="${MAX_FPS:-60}"

if [[ "$MODE" == "panel" ]]; then
    echo ""
    read -p "  Arma server directory [$SERVER_DIR]: " INPUT_SERVER_DIR
    SERVER_DIR="${INPUT_SERVER_DIR:-$SERVER_DIR}"
    read -p "  config.json path [$SERVER_CONFIG]: " INPUT_CONFIG
    SERVER_CONFIG="${INPUT_CONFIG:-$SERVER_CONFIG}"
    read -p "  Log directory [$LOG_DIR]: " INPUT_LOG
    LOG_DIR="${INPUT_LOG:-$LOG_DIR}"
    read -p "  Arma system user [$ARMA_USER]: " INPUT_ARMA_USER
    ARMA_USER="${INPUT_ARMA_USER:-$ARMA_USER}"
    PANEL_DIR="/home/$ARMA_USER/panel"
fi

# ── Confirm ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}━━━ Summary ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
if [[ "$MODE" == "full" ]]; then
    echo -e "  System user   : ${CYAN}$ARMA_USER${NC}"
    echo -e "  Server dir    : ${CYAN}$SERVER_DIR${NC}"
    echo -e "  Server name   : ${CYAN}$SERVER_NAME${NC}"
    echo -e "  Public IP     : ${CYAN}$PUBLIC_IP:$GAME_PORT${NC}"
    echo -e "  Max players   : ${CYAN}$MAX_PLAYERS${NC}"
fi
echo -e "  Panel dir     : ${CYAN}$PANEL_DIR${NC}"
echo -e "  Panel port    : ${CYAN}$PANEL_PORT${NC}"
echo ""
read -p "  Proceed? [Y/n]: " CONFIRM
[[ "$CONFIRM" =~ ^[Nn]$ ]] && exit 0
echo ""

# ── FULL MODE: steps 1-5 ──────────────────────────────────────────────────────
if [[ "$MODE" == "full" ]]; then

    # Step 1: System user
    echo -e "${YELLOW}[1/6] Creating system user '${ARMA_USER}'...${NC}"
    if id "$ARMA_USER" &>/dev/null; then
        echo -e "      ${DIM}User already exists — skipping.${NC}"
    else
        useradd -m -s /bin/bash "$ARMA_USER"
        echo -e "      ${GREEN}✓ Done.${NC}"
    fi

    # Step 2: Dependencies
    echo -e "${YELLOW}[2/6] Installing system dependencies...${NC}"
    dpkg --add-architecture i386
    apt-get update -qq
    # Install Flask and bcrypt via apt rather than pip — avoids the "Cannot
    # uninstall blinker, RECORD file not found" error caused by pip trying
    # to replace apt-managed dependencies on Ubuntu 24.04.
    apt-get install -y -qq python3 curl lib32gcc-s1 binutils python3-flask python3-bcrypt
    echo -e "      ${GREEN}✓ Done.${NC}"

    # Step 3: SteamCMD
    echo -e "${YELLOW}[3/6] Installing SteamCMD...${NC}"
    mkdir -p "$STEAM_DIR"
    if [ ! -f "$STEAM_DIR/steamcmd.sh" ]; then
        # Fail on HTTP/download errors instead of piping an error page to tar.
        STEAM_ARCHIVE=$(mktemp "$STEAM_DIR/steamcmd-download-XXXXXXXX.tar.gz")
        if ! curl -qfSL --retry 3 --connect-timeout 30 \
            "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz" \
            -o "$STEAM_ARCHIVE"; then
            echo -e "${RED}ERROR: SteamCMD download failed. Archive: $STEAM_ARCHIVE${NC}"
            exit 1
        fi
        tar xzf "$STEAM_ARCHIVE" -C "$STEAM_DIR"
        rm -f -- "$STEAM_ARCHIVE"
    fi
    chown -R "$ARMA_USER:$ARMA_USER" "$STEAM_DIR"
    echo -e "      ${GREEN}✓ Done.${NC}"

    # Step 4: Download Arma server
    echo -e "${YELLOW}[4/6] Downloading Arma Reforger Dedicated Server (~15 GB)...${NC}"
    echo -e "      ${DIM}This may take 10–30 minutes depending on your connection.${NC}"
    mkdir -p "$SERVER_DIR"
    chown -R "$ARMA_USER:$ARMA_USER" "$SERVER_DIR"
    download_arma_server
    echo -e "      ${GREEN}✓ Arma Reforger Server downloaded.${NC}"

    # Step 5: config.json
    echo -e "${YELLOW}[5/6] Generating server config.json...${NC}"
    mkdir -p "$(dirname "$SERVER_CONFIG")"
    if [ -f "$SERVER_CONFIG" ]; then
        echo -e "      ${DIM}Keeping existing $SERVER_CONFIG.${NC}"
    else
    SERVER_NAME="$SERVER_NAME" GAME_PASSWORD="$GAME_PASSWORD" ADMIN_PASSWORD="$ADMIN_PASSWORD" \
    PUBLIC_IP="$PUBLIC_IP" GAME_PORT="$GAME_PORT" MAX_PLAYERS="$MAX_PLAYERS" \
    python3 - "$SERVER_CONFIG" <<'PYCONFIG'
import json, os, sys
cfg = {'bindAddress': '0.0.0.0', 'bindPort': 0, 'publicAddress': '', 'publicPort': 0, 'a2s': {'address': '', 'port': 17777}, 'game': {'name': '', 'password': '', 'passwordAdmin': '', 'scenarioId': '{ECC61978EDCC2B5A}Missions/23_Campaign.conf', 'maxPlayers': 0, 'visible': True, 'crossPlatform': True, 'supportedPlatforms': ['PLATFORM_PC', 'PLATFORM_XBL'], 'gameProperties': {'serverMaxViewDistance': 2500, 'serverMinGrassDistance': 50, 'networkViewDistance': 1000, 'disableThirdPerson': False, 'fastValidation': True, 'battlEye': True, 'persistence': {'autoSaveInterval': 10, 'saveRetention': 10, 'loadSessionSave': True, 'keepSessionSave': False, 'hiveId': 0}}, 'mods': []}}
e = os.environ
port, players = int(e['GAME_PORT']), int(e['MAX_PLAYERS'])
if not 1 <= port <= 65535 or players < 1:
    raise ValueError('Invalid game port or max players')
cfg.update(bindPort=port, publicPort=port, publicAddress=e['PUBLIC_IP'])
cfg['a2s']['address'] = e['PUBLIC_IP']
cfg['game'].update(name=e['SERVER_NAME'], password=e['GAME_PASSWORD'], passwordAdmin=e['ADMIN_PASSWORD'], maxPlayers=players)
with open(sys.argv[1], 'x', encoding='utf-8') as stream:
    json.dump(cfg, stream, indent=2)
PYCONFIG
    fi
    chown "$ARMA_USER:$ARMA_USER" "$SERVER_CONFIG"
    echo -e "      ${GREEN}✓ config.json ready.${NC}"

    # Firewall is intentionally NOT touched — see post-install summary.
    # The user is expected to manage their own firewall (UFW recommended).

    # Arma server systemd service
    cat > /etc/systemd/system/arma-server.service << EOF
[Unit]
Description=Arma Reforger Dedicated Server
After=network.target

[Service]
Type=simple
User=${ARMA_USER}
WorkingDirectory=${SERVER_DIR}
ExecStart=${SERVER_DIR}/${ARMA_BINARY} -config ${SERVER_CONFIG} -maxFPS=${MAX_FPS} -logStats 1000
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable arma-server
    echo -e "      ${GREEN}✓ Arma server service created.${NC}"

fi  # end full mode

# ── PANEL install (both full and panel-only modes) ────────────────────────────
PANEL_STEP=6
if [[ "$MODE" == "panel" ]]; then PANEL_STEP=1; fi
TOTAL_STEPS=6
if [[ "$MODE" == "panel" ]]; then TOTAL_STEPS=1; fi

echo -e "${YELLOW}[${PANEL_STEP}/${TOTAL_STEPS}] Installing management panel...${NC}"

# Dependencies (panel-only mode)
if [[ "$MODE" == "panel" ]]; then
    apt-get update -qq
    apt-get install -y -qq python3 binutils python3-flask python3-bcrypt
fi

mkdir -p "$PANEL_DIR/static"

# Copy files from script directory
for f in app.py panel_features.py player_query.py runtime_ops.py network_status.py file_manager.py config_editor.py mod_metadata.py server_software.py index.html login.html; do
    if [ -f "$SCRIPT_DIR/$f" ]; then
        cp "$SCRIPT_DIR/$f" "$PANEL_DIR/"
    else
        echo -e "      ${RED}WARNING: $f not found in script directory.${NC}"
    fi
done
for f in manifest.json service-worker.js features.js console.js workspace.css configuration.js configuration.css network.js network.css files.js files.css mods.js mods.css sharp.css software.js icon-192.png icon-512.png; do
    if [ -f "$SCRIPT_DIR/static/$f" ]; then
        cp "$SCRIPT_DIR/static/$f" "$PANEL_DIR/static/"
    fi
done

# Hash the panel password with bcrypt so it isn't stored in plaintext.
# Falls back to plaintext only if bcrypt isn't available (shouldn't happen).
PANEL_PASSWORD_HASH=$(python3 -c "
import bcrypt, sys
print(bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt()).decode())
" "$PANEL_PASSWORD" 2>/dev/null || true)

# Default workshop dir for the addons that the Reforger server downloads.
WORKSHOP_DIR="${ARMA_HOME}/.local/share/Arma Reforger/addons"
# Default profile dir: where Reforger writes session saves. Linux dedicated
# layout puts them under `{ARMA_HOME}/.config/ArmaReforger/profile/.save/`.
PROFILE_DIR="${ARMA_HOME}/.config/ArmaReforger/profile"

if [ -f "$PANEL_DIR/config.env" ]; then
    echo -e "      ${DIM}Keeping existing $PANEL_DIR/config.env (including its panel port and paths).${NC}"
else
cat > "$PANEL_DIR/config.env" << EOF
# bcrypt-hashed admin password. Generated at install time.
PANEL_PASSWORD_HASH=${PANEL_PASSWORD_HASH}
PANEL_PORT=${PANEL_PORT}
SERVER_DIR=${SERVER_DIR}
STEAMCMD_PATH=${STEAM_DIR}/steamcmd.sh
SERVER_CONFIG=${SERVER_CONFIG}
LOG_DIR=${LOG_DIR}
WORKSHOP_DIR=${WORKSHOP_DIR}
PROFILE_DIR=${PROFILE_DIR}
MAX_FPS=${MAX_FPS}
EOF
fi
chmod 600 "$PANEL_DIR/config.env"
chown -R "$ARMA_USER:$ARMA_USER" "$PANEL_DIR"

cat > /etc/systemd/system/arma-panel.service << EOF
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

configure_server_control "$PANEL_DIR" "$ARMA_USER"
systemctl enable arma-panel
systemctl restart arma-panel

# Firewall is intentionally NOT touched — see post-install summary.

echo -e "      ${GREEN}✓ Panel installed and started.${NC}"

# ── Final summary ─────────────────────────────────────────────────────────────
if [ -z "$PUBLIC_IP" ]; then
    PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "YOUR_SERVER_IP")
fi

echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║           Installation complete!                 ║${NC}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
if [[ "$MODE" == "full" ]]; then
echo -e "  ${BOLD}Arma Reforger Server:${NC}"
echo -e "    Address : ${CYAN}${PUBLIC_IP}:${GAME_PORT}${NC}"
echo -e "    Start   : ${YELLOW}sudo systemctl start arma-server${NC}"
echo -e "    Status  : ${YELLOW}sudo systemctl status arma-server${NC}"
echo ""
fi
echo -e "  ${BOLD}Management Panel:${NC}"
echo -e "    URL      : ${CYAN}http://${PUBLIC_IP}:${PANEL_PORT}${NC}"
echo -e "    Username : ${CYAN}admin${NC} (first install)"
echo -e "    Password : ${DIM}(the one entered on first install; existing accounts keep their passwords)${NC}"
echo -e "    Config   : ${DIM}$PANEL_DIR/config.env — saved settings take precedence when rerunning${NC}"
echo -e "    Restart  : ${YELLOW}sudo systemctl restart arma-panel${NC}"
echo -e "    Logs     : ${YELLOW}sudo journalctl -u arma-panel -f${NC}"
echo ""
echo -e "  ${BOLD}Update panel in the future:${NC}"
echo -e "    ${YELLOW}git pull && sudo bash install.sh --update${NC}"
echo ""
echo -e "${BOLD}${YELLOW}⚠  Firewall — action required${NC}"
echo -e "  This installer does ${BOLD}not${NC} touch your firewall. Open the following ports"
echo -e "  yourself so players (and you) can reach the server and panel:"
echo ""
if [[ "$MODE" == "full" ]]; then
echo -e "    ${CYAN}sudo ufw allow ${GAME_PORT}/udp${NC}      ${DIM}# Reforger game port${NC}"
echo -e "    ${CYAN}sudo ufw allow 17777/udp${NC}              ${DIM}# A2S server-browser query${NC}"
fi
echo -e "    ${CYAN}sudo ufw allow ${PANEL_PORT}/tcp${NC}        ${DIM}# Panel web UI${NC}"
echo -e "    ${CYAN}sudo ufw reload${NC}"
echo ""
echo -e "  ${DIM}Tip: bind the panel to 127.0.0.1 and SSH-tunnel instead of opening${NC}"
echo -e "  ${DIM}${PANEL_PORT}/tcp publicly — even with the hashed password, HTTP is sniffable.${NC}"
echo ""
if [[ "$MODE" == "full" ]]; then
echo -e "  ${DIM}Tip: Connect in-game via Multiplayer → Direct Connect → ${PUBLIC_IP}:${GAME_PORT}${NC}"
echo ""
fi
