#!/usr/bin/env bash
# Hook SessionStart: prepara l'ambiente a ogni avvio di una sessione Claude Code cloud.
# Fuori dal cloud non fa nulla (vedi in_cloud in session_lib.sh).
source "${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/session_lib.sh"
in_cloud || exit 0
cd "$ROOT" || exit 0

# I test usano solo la libreria standard e pytest (già presente nell'ambiente cloud).
if python3 -c 'import pytest' 2>/dev/null; then note "pytest: già pronto"
else install_once pytest "pytest.ini" python3 -m pip install -q pytest; fi
# Repo integrate (third_party/: PPO, flameox, REA) e i loro strumenti, senza bloccare l'avvio.
background integrazioni "$ROOT/.claude/hooks/setup_integrations.sh"
note "Verifica standard: python -m pytest -q (circa 40 s). Le skill sono in .claude/skills/ (drivenow-integrazioni per PPO, flameox, REA)."
finish
