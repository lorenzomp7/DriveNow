---
name: drivenow-integrazioni
description: Usa le repo integrate in third_party/ (PPO dei semafori, flameox, REA) per conto dell'utente - confronto PPO, riaddestramento, profilazione, schede delle app dall'APK. Da usare quando l'utente chiede di far girare, aggiornare o completare una di queste integrazioni.
---

# Repo integrate in DriveNow

L'utente vuole fare tutto da chat: esegui tu ogni comando, non dargli istruzioni da lanciare.
Gli unici gesti che restano a lui sono fisici o di consenso: collegare il telefono, caricare
un file in chat, approvare un download.

## Prima di tutto

Nelle sessioni cloud l'hook di avvio prepara sottomoduli e strumenti in background:

```bash
bash .claude/hooks/wait_setup.sh integrazioni
```

In locale, o se manca qualcosa: `git submodule update --init --depth 1` e
`python tools/devtools.py setup ppo flameox rea` (PyTorch pesa alcuni GB: dillo prima di
installarlo su una macchina dell'utente). `python tools/devtools.py status` dice cosa c'è.

## Compiti

| Richiesta | Comando | Dove va il risultato |
|---|---|---|
| Confronto PPO (semafori del PPO, finestre impegnate) | `python tools/devtools.py run ppo -- --seeds 1 2 3 --out docs/benchmarks/ppo-2x2` (circa 10 minuti) | `docs/benchmarks/ppo-2x2.*`, tabella in `docs/ppo-semafori.md` |
| Riaddestrare il PPO | `.tools/envs/ppo/bin/python tools/ppo_train.py --rollouts 200` (circa 20 minuti; poi rifai il confronto) | `data/ppo/ppo_2x2.pt` e `.json` |
| Profilare | `python tools/devtools.py run flameox -- --seconds 900`; tempi senza profiler con `python tools/sim_profile.py sim|sumo|server` | tabelle in `docs/operational.md` (data, macchina, impronta dei risultati) |
| Scheda di un'app | vedi sotto | `docs/app-analizzate/<app>.md` |

Per ogni confronto riporta seme, scenario, domanda, quota, durata, riscaldamento e viaggi
conclusi (AGENTS.md); dopo un'ottimizzazione l'impronta `results.sha256` deve restare uguale.

## Scheda di un'app dall'APK

1. Procurati l'APK in modo lecito, sempre fuori dalla repo (es. `/tmp/apks/`):
   - telefono collegato via USB a questa macchina, debug USB attivo (sessione locale):
     `.tools/rea/node_modules/.bin/rea list-adb-devices`, poi
     `rea resolve-adb-packages <serial> <nome>` e
     `rea pull-adb-package <serial> <pacchetto> --output-directory /tmp/apks/<app>`;
   - sessione cloud o senza telefono: chiedi all'utente di caricare in chat gli APK
     (base e split) e usa i file caricati;
   - app open source: la release ufficiale dell'editore, verificando il checksum pubblicato.
   Mai APK da siti mirror.
2. `python tools/app_scan.py /tmp/apks/<app>/base.apk [split...] --app "<Nome>"
   --evidence-dir /tmp/apks/evidence --source "<da dove>" --out /tmp/<app>-apk.md`
3. Nella scheda esistente sostituisci le righe «da verificare (APK)» con quanto trovato,
   citando l'elemento del manifest; aggiorna la tabella di `docs/app-analizzate/README.md`.
4. Mai copiare in DriveNow APK, codice decompilato o risorse dell'app.

Per leggere il codice (da dove arrivano i dati dei semafori, quando parla) REA vuole JADX e
il ponte `jadx-headless-mcp` (`REA_JADX_MCP_JAR`). L'utente ha chiesto REA utilizzabile dalla
chat in tutte le repo: `.claude/rea/installa.sh` scarica il JAR 0.7.1 con lo SHA-256 indicato da
REA (nel cloud all'avvio della sessione) e il server MCP `rea` di `.mcp.json` ha già gli
strumenti `inspect_android_class`, `inspect_android_method` e `trace_android_references`:
vedi la skill `rea`.

## Chiusura

`python -m pytest -q`, `git diff --check`, commit su `main_claude` e push. Nel file
«Piano di battaglia» aggiorna il foglio «Integrazioni GitHub» in una nuova revisione
numerata del file, senza sovrascrivere la precedente.
