#!/bin/bash
# ============================================================
# Arma Reforger — All-in-One Installer v4.0
# https://github.com/mateuszgolebiewski-code/arma-reforger-panel
#
# Modes:
#   sudo bash install.sh              — full install (SteamCMD + server + panel)
#   sudo bash install.sh --panel-only — install panel only (server already exists)
#   sudo bash install.sh --update     — update panel files only
# ============================================================

set -e

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
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${CYAN}║   Arma Reforger — All-in-One Installer v4.0     ║${NC}"
echo -e "${BOLD}${CYAN}║   github.com/mateuszgolebiewski-code             ║${NC}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════╝${NC}"
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
    echo -e "${YELLOW}WARNING: This installer is tested on Ubuntu 20.04/22.04/24.04.${NC}"
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
    if [ ! -d "$PANEL_DIR" ]; then
        echo -e "${RED}ERROR: Panel not found at ${PANEL_DIR}${NC}"
        echo -e "  Run the full installer first: sudo bash install.sh"
        exit 1
    fi
    # Read existing user from panel service
    EXISTING_USER=$(grep "^User=" /etc/systemd/system/arma-panel.service 2>/dev/null | cut -d= -f2 || echo "arma")
    PANEL_DIR_EXISTING=$(grep "^WorkingDirectory=" /etc/systemd/system/arma-panel.service 2>/dev/null | cut -d= -f2 || echo "$PANEL_DIR")
    cp "$SCRIPT_DIR/app.py"     "$PANEL_DIR_EXISTING/"
    cp "$SCRIPT_DIR/panel_features.py" "$PANEL_DIR_EXISTING/"
    cp "$SCRIPT_DIR/player_query.py" "$PANEL_DIR_EXISTING/"
    cp "$SCRIPT_DIR/index.html" "$PANEL_DIR_EXISTING/"
    cp "$SCRIPT_DIR/login.html" "$PANEL_DIR_EXISTING/"
    cp "$SCRIPT_DIR/static/"*   "$PANEL_DIR_EXISTING/static/"
    chown -R "$EXISTING_USER:$EXISTING_USER" "$PANEL_DIR_EXISTING"
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
        curl -sqL "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz" \
            | tar xz -C "$STEAM_DIR"
    fi
    chown -R "$ARMA_USER:$ARMA_USER" "$STEAM_DIR"
    echo -e "      ${GREEN}✓ Done.${NC}"

    # Step 4: Download Arma server
    echo -e "${YELLOW}[4/6] Downloading Arma Reforger Dedicated Server (~15 GB)...${NC}"
    echo -e "      ${DIM}This may take 10–30 minutes depending on your connection.${NC}"
    mkdir -p "$SERVER_DIR"
    chown -R "$ARMA_USER:$ARMA_USER" "$SERVER_DIR"
    # NOTE: +force_install_dir MUST come before +login, otherwise SteamCMD
    # fails with "Please use force_install_dir before logon!"
    sudo -u "$ARMA_USER" "$STEAM_DIR/steamcmd.sh" \
        +force_install_dir "$SERVER_DIR" \
        +login anonymous \
        +app_update "$ARMA_APP_ID" validate \
        +quit
    echo -e "      ${GREEN}✓ Arma Reforger Server downloaded.${NC}"

    # Step 5: config.json
    echo -e "${YELLOW}[5/6] Generating server config.json...${NC}"
    mkdir -p "$(dirname "$SERVER_CONFIG")"
    cat > "$SERVER_CONFIG" << EOF
{
	"bindAddress": "0.0.0.0",
	"bindPort": ${GAME_PORT},
	"publicAddress": "${PUBLIC_IP}",
	"publicPort": ${GAME_PORT},
	"a2s": {
		"address": "${PUBLIC_IP}",
		"port": 17777
	},
	"game": {
		"name": "${SERVER_NAME}",
		"password": "${GAME_PASSWORD}",
		"passwordAdmin": "${ADMIN_PASSWORD}",
		"scenarioId": "{ECC61978EDCC2B5A}Missions/23_Campaign.conf",
		"maxPlayers": ${MAX_PLAYERS},
		"visible": true,
		"crossPlatform": true,
		"supportedPlatforms": ["PLATFORM_PC", "PLATFORM_XBL"],
		"gameProperties": {
			"serverMaxViewDistance": 2500,
			"serverMinGrassDistance": 50,
			"networkViewDistance": 1000,
			"disableThirdPerson": false,
			"fastValidation": true,
			"battlEye": true
		},
		"mods": []
	}
}
EOF
    chown "$ARMA_USER:$ARMA_USER" "$SERVER_CONFIG"
    echo -e "      ${GREEN}✓ config.json generated.${NC}"

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
ExecStart=${SERVER_DIR}/${ARMA_BINARY} -config ${SERVER_CONFIG} -loadSessionSave -maxFPS=${MAX_FPS}
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
for f in app.py panel_features.py player_query.py index.html login.html; do
    if [ -f "$SCRIPT_DIR/$f" ]; then
        cp "$SCRIPT_DIR/$f" "$PANEL_DIR/"
    else
        echo -e "      ${RED}WARNING: $f not found in script directory.${NC}"
    fi
done
for f in manifest.json service-worker.js features.js icon-192.png icon-512.png; do
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

cat > "$PANEL_DIR/config.env" << EOF
# bcrypt-hashed admin password. Generated at install time.
PANEL_PASSWORD_HASH=${PANEL_PASSWORD_HASH}
PANEL_PORT=${PANEL_PORT}
SERVER_DIR=${SERVER_DIR}
SERVER_CONFIG=${SERVER_CONFIG}
LOG_DIR=${LOG_DIR}
WORKSHOP_DIR=${WORKSHOP_DIR}
PROFILE_DIR=${PROFILE_DIR}
MAX_FPS=${MAX_FPS}
EOF
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

systemctl daemon-reload
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
echo -e "    Password : ${DIM}(the one you entered — it has been bcrypt-hashed in config.env)${NC}"
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
