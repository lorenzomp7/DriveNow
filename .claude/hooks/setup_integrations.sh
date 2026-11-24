#!/usr/bin/env bash
# Prepara in background le repo integrate in third_party/ e i loro strumenti (avviato da
# session_start.sh tramite background()): sottomoduli, flameox, REA + Apktool, ambiente PPO.
# Scrive ready o failed in $STATUS_FILE.
set -u
cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" || exit 1
ok=1
git submodule update --init --depth 1 || ok=0
python3 tools/devtools.py setup flameox rea ppo || ok=0
if [ "$ok" = 1 ]; then echo ready > "$STATUS_FILE"; else echo failed > "$STATUS_FILE"; fi
