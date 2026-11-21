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

La repo contiene `.mcp.json` con tre server: Playwriter, container-use e
DriveNow Vibetest. Dopo `setup`, un client che legge la configurazione MCP di
progetto può avviarli quando apre questa repo e accetta i server del progetto.
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
