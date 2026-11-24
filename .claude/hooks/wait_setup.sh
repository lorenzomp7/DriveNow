#!/usr/bin/env bash
# wait_setup.sh NOME: aspetta la fine di un'installazione avviata in background da
# session_start.sh e ne stampa l'esito (log in .claude/hooks/.state/NOME.log).
name=${1:?uso: wait_setup.sh NOME}
state="${CLAUDE_PROJECT_DIR:-$(pwd)}/.claude/hooks/.state"
for _ in $(seq 1 900); do
  status=$(cat "$state/$name.status" 2>/dev/null || echo missing)
  case "$status" in
    ready) echo "$name: pronto"; exit 0 ;;
    failed) echo "$name: FALLITO, vedi $state/$name.log"; exit 1 ;;
    missing) echo "$name: non avviato (CLAUDE_SETUP_FORCE=1 bash .claude/hooks/session_start.sh)"; exit 1 ;;
  esac
  sleep 2
done
echo "$name: ancora in corso dopo 30 minuti, vedi $state/$name.log"; exit 1
