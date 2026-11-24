# Avviare gli strumenti di DriveNow

Da un checkout del branch `main_claude`, con Python 3.12, Git, Node 22+ e Chrome:

```bash
python tools/devtools.py setup
python tools/devtools.py status
```

`setup` installa realmente ogni ambiente nella cartella ignorata `.tools/`,
scarica il sorgente LibSignal alla versione fissata e installa Playwriter con
`npm ci`. Non richiede di attivare manualmente i virtualenv. Si può limitare
l'installazione: `python tools/devtools.py setup browser playwriter`.
Se un prerequisito manca, termina con un errore esplicito senza dichiarare
completata l'installazione. `status` mostra installazione e prerequisiti mancanti:
**non è un'esecuzione dei test**.

| Comando | Cosa esegue realmente |
|---|---|
| `python tools/devtools.py run skills` | Controlla integrità delle sette procedure installate |
| `python tools/devtools.py run browser` | Test Playwright della demo desktop/mobile |
| `python tools/devtools.py run playwriter` | Test desktop/mobile con il server MCP Playwriter reale |
| `python tools/devtools.py run container` | Test Python e demo dentro un ambiente container-use reale |
| `python tools/devtools.py run libsignal` | 900 passi del mondo SUMO reale LibSignal con previsione dai segnali osservati |
| `python tools/devtools.py run darts` | Confronto offline Darts/DriveNow sui dati reali di Amburgo |
| `python tools/devtools.py run vibetest -- --model NOME_MODELLO` | Esplorazione AI di una demo avviata automaticamente, con Google API |

Gli argomenti dopo `--` sono inoltrati allo strumento. Per esempio:
`python tools/devtools.py run darts -- --scenario gaertnerstrasse`.
I rapporti sono salvati in `test-results/`. Nessuno strumento cambia il modello
della demo ordinaria o esegue il merge dei risultati automaticamente.

## Claude Code e altri client MCP

La repo contiene `.mcp.optional.json` con Playwriter (richiede il tuo Chrome con
l'estensione), container-use (richiede Docker) e DriveNow Vibetest (richiede la
chiave Google). Non c'è un `.mcp.json`: le sessioni Claude Code nel cloud non
avviano server che lì non possono funzionare. In un client locale caricali con
`claude --mcp-config .mcp.optional.json`, dopo `setup`. I controlli nel browser
girano comunque in GitHub Actions.
Non vengono modificati la configurazione globale del client o i suoi permessi.

Per i client che richiedono percorsi assoluti:

```bash
python tools/devtools.py mcp-config
```

Questa configurazione è generata per il computer in cui esegui il comando.
Un agente che dispone di un terminale nel checkout può anche eseguire i comandi
`run` direttamente. Aggiungere un file MCP alla repo non registra strumenti
nuovi nella sessione ChatGPT già aperta: l'host deve supportare e collegare quel
server, oppure eseguire i comandi nel proprio ambiente di lavoro.

## Parti che richiedono il tuo ambiente

- **Vibetest AI:** esportare `GOOGLE_API_KEY` e scegliere un modello Gemini
  disponibile nel proprio account, passando `--model` o impostando
  `VIBETEST_MODEL`. Le chiavi non vengono scritte né committate. Un test AI può
  consumare credito Google e invia al modello il contenuto della demo.
- **container-use locale:** Docker deve essere installato e avviato. Il tool
  non installa o avvia automaticamente Docker sul tuo computer. Su Windows,
  usare WSL2 con Docker integrato e gli strumenti nello stesso ambiente.
- **Playwriter sul tuo Chrome personale:** installare e abilitare l'estensione
  sulla scheda DriveNow oppure scegliere un collegamento CDP autorizzato. I test
  automatici usano un profilo temporaneo; non abilitano le tue schede personali.

Vibetest ora espone i tool MCP `installation_status` e `test_drivenow`: il secondo
avvia la demo, esegue l'esplorazione e chiude il server. Senza chiave restituisce
un errore prima di avviare l'AI. La CI verifica davvero il collegamento MCP e
questo blocco, **senza chiamate al modello**; non è una prova di QA AI riuscita.

## LibSignal e Darts

LibSignal può usare `LibSignalAdvisor(world, learn_signals=True)`: il nuovo
previsore campiona gli stati SUMO dopo ogni passo, apprende dai cicli passati e
restituisce finestre probabilistiche solo dopo un riscaldamento sufficiente.
Non legge il futuro dell'XML, non cambia le luci e non tratta il giallo o un
verde permissivo come verde protetto. Senza dati sufficienti si astiene.
Ricreare il ponte dopo `world.reset()`; non saltare passi di osservazione.

La prova a 900 passi richiede che siano prodotte anche finestre verdi non vuote,
oltre ai consigli e all'integrità delle luci. È una previsione **sperimentale**,
non una garanzia sui controllori adattivi: se una politica cambia ciclo, può
sbagliare. Per usare impegni certi resta disponibile il callback `windows_fn`,
mutuamente esclusivo con `learn_signals`. Non viene aggiunto un addestramento RL
né viene dichiarata una riduzione delle fermate senza un benchmark apposito.

Darts è operativo nel confronto offline. Il modello provato non viene promosso
al motore online perché produce più falsi verdi nel campione misurato. Una
libreria installata non implica un miglioramento matematico dimostrato.

## Prestazioni della simulazione (flameox)

Quanti casi e semi si possono confrontare (Piano, punti 9, 24 e 25) dipende dal tempo di
calcolo per secondo simulato. `tools/sim_profile.py` ha tre carichi fissi; ognuno stampa una
riga JSON con tempo reale, tempo simulato e un'impronta dei risultati (`results.sha256`:
viaggi, fermate, energia nei freni e tempo dei due gruppi), da confrontare prima e dopo
un'ottimizzazione con lo stesso seme.

[flameox](https://github.com/morluto/flameox) (MIT, 0.2.9) coordina i profiler e restituisce
le funzioni più costose con la loro copertura. È integrato come sottomodulo git
`third_party/flameox` (commit `c7ea167`) e si installa da lì in un ambiente suo; non è una
dipendenza del server.

```bash
python tools/devtools.py setup flameox   # flameox[cpu] dal sottomodulo + py-spy (Python 3.12+)
python tools/devtools.py run flameox -- --seconds 900   # simulatore interno, come sotto
flameox capture --provider py-spy --operation rank_cpu_hotspots --cwd "$PWD" \
    -- python tools/sim_profile.py sim --seconds 900
flameox capture --provider py-spy --operation rank_cpu_hotspots --cwd "$PWD" \
    -- python tools/sim_profile.py server --speed 10 --wall 30
flameox capture --provider py-spy --operation rank_cpu_hotspots --cwd "$PWD" \
    -- python tools/sim_profile.py sumo --seconds 900
```

Gli stessi strumenti sono raggiungibili da un client MCP con `npx flameox@latest setup`
(`capture_and_rank_cpu_hotspots`, `inspect_cpu_callers`).

Misura del 2026-11-24, sessione cloud a 2 CPU x86_64, Python 3.13, SUMO dal pacchetto
`eclipse-sumo`, seme 1, domanda 240 veicoli/h per ingresso, quota DriveNow 50 %, passo 0,2 s.
Tempi senza profiler, tre ripetizioni:

| Carico | Secondi simulati | Tempo reale | Per secondo simulato | Impronta |
|---|---|---|---|---|
| Simulatore interno, città demo | 900 | 6,1-6,5 s | 6,8-7,2 ms | `462d1f821b7936e0` (uguale nelle tre) |
| SUMO, griglia 2×2 (parte Python + SUMO) | 900 | 14,3-15,3 s | 15,9-16,9 ms | `d26faae8c81526a3` (uguale nelle tre) |
| Server a velocità 10, senza HTTP | 299,8 in 30 s | – | tiene 9,98× | – |

Il server tiene anche la velocità massima che accetta (20×: 19,94× misurata). Le corse di
`tools/ppo_bench.py` (1250 s simulati in SUMO) durano 10-12 s con il ciclo fisso senza
consiglio, 22-25 s con il consiglio e 28-38 s con i semafori del PPO e il consiglio, quindi
3 semi × 8 casi stanno in circa 10 minuti.

Funzioni con più tempo proprio (campioni py-spy a 100 Hz; flameox restituisce le 100 righe
più costose, che coprono il 71 % dei campioni nel simulatore interno e l'81 % in SUMO):

| Simulatore interno | % | SUMO | % |
|---|---|---|---|
| `glosa.arrival_time` | 11,7 | TraCI `_recvExact` (attesa risposte) | 26,2 |
| `SignalPlan.green_windows` | 9,9 | TraCI `_sendExact` | 8,5 |
| `Advisor.controls_ahead` | 9,6 | TraCI `Storage.read` | 7,5 |
| `Simulation._acceleration` | 4,4 | `glosa.arrival_time` | 7,3 |
| `Simulation.step` | 4,0 | `Advisor.controls_ahead` | 2,6 |
| `SignalPlan._locate` + `cycle` | 4,9 | `SignalPlan.green_windows` | 2,5 |

Nel server a velocità 10 metà dei campioni sono attese (`time.sleep` nel ciclo del Runner e
nel carico); il resto è la stessa catena del simulatore interno.

Cosa dice: nel simulatore interno quasi un terzo del tempo è il calcolo del consiglio
(`arrival_time`, finestre di verde, controlli lungo il percorso), che si ripete ogni 0,6 s per
ogni auto; finestre di verde e cicli si potrebbero tenere in cache per semaforo e istante. In
SUMO quasi metà del tempo è nella comunicazione TraCI (un comando per auto e passo):
`libsumo` al posto di TraCI, o meno chiamate per passo, è la prima cosa da provare. Dopo
un'ottimizzazione: stessi comandi, stessa impronta (risultati uguali), tempo nuovo in questa
tabella.

## Verifiche automatiche

Il workflow **Operational toolchain** installa ed esegue ogni profilo con gli
stessi comandi sopra. La prova Vibetest controlla installazione, MCP e richiesta
delle credenziali, senza usare una chiave. Le altre prove eseguono realmente
browser, container, modello Darts e mondo LibSignal. I risultati correnti vanno
letti su GitHub Actions; soltanto una verifica completata con successo è una
prova passata.

È disponibile anche `python tools/devtools.py run vibetest -- --check-browser`:
apre e chiude una vera sessione BrowserUse senza chiamare il modello. Il flusso
corregge anche il vecchio richiamo upstream ad `aclose()` usando il metodo
`kill()` della versione fissata, ripristinando il contratto alla fine della
singola esecuzione. La CI verifica l'avvio del browser oltre al protocollo MCP.
La fixture LibSignal estesa usa una copia temporanea della rete con fasi finite,
per consentire a LibSignal di scoprire entrambe le fasi; la rete della repo
rimane invariata. L'esecuzione locale a 900 passi ha prodotto 29.689 campioni
veicolo e 680 previsioni con finestre verdi: è una prova funzionale, non una
misura di beneficio sul traffico.
