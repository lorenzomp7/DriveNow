# Playwriter per verificare DriveNow

DriveNow integra **Playwriter 0.12.0**, con dipendenze e impronte npm fissate in
`tools/playwriter/package-lock.json`. Sono inclusi il collegamento MCP reale,
un controllo dell'interfaccia desktop/mobile e il comando per generare la
configurazione del proprio client. Il server DriveNow resta Python senza
nuove dipendenze di runtime.

Sorgente: [remorses/playwriter](https://github.com/remorses/playwriter), versione
npm verificata confrontando il sorgente upstream al commit
`53939bcdd9a6a9fd489454cadba41dfd0dbd5b4f`. Il pacchetto installato arriva da npm,
non da una compilazione locale di quel commit.

## Installazione e prova automatica

Serve Python 3.12, Node.js 22+ e Chrome/Chromium installato:

```bash
npm ci --prefix tools/playwriter
python tools/playwriter_check.py
```

Se il browser non è nel PATH, impostare `DRIVENOW_CHROMIUM` con il percorso
completo del suo eseguibile. In PowerShell si può usare
`$env:DRIVENOW_CHROMIUM = 'C:\Program Files\Google\Chrome\Application\chrome.exe'`.
Il percorso Windows non è stato verificato in questa sessione.

Il comando avvia una demo temporanea su una porta libera, un nuovo profilo
Chrome headless e un relay Playwriter su una porta locale dedicata. Usa i tool
MCP **session_new, execute e session_delete** del pacchetto ufficiale, collegandosi
via CDP al browser appena creato: non si limita a importare una libreria o a
lanciare il test Playwright già presente.

Controlla a 1440×900 e 390×844:

- Connessione live e avanzamento del tempo.
- Mappa visibile e consiglio al veicolo.
- Cambio veicolo, inseguimento e inquadratura.
- Richiesta e applicazione visibile della velocità di simulazione.
- Invio della quota DriveNow tramite la tastiera sullo slider.
- Zoom e assenza di errori JavaScript osservati.

I rapporti e gli screenshot vengono scritti in `test-results/playwriter/`.
Qualsiasi errore MCP, browser o asserzione produce un exit code diverso da zero.
Sessione, schede, browser temporaneo e relay vengono chiusi alla fine.
Non vengono avviati agenti AI, richiesti modelli o usate chiavi API.
La prova usa un browser dedicato: **non verifica l'estensione nel tuo profilo
personale** e non apre le tue schede esistenti.

Il workflow `Playwriter integration` esegue la stessa prova su Ubuntu usando
Chrome già installato nel runner, e pubblica rapporto/screenshot come artefatti.
Non scarica Chromium attraverso la versione Python di Playwright. Qui il lancio
di Chrome è bloccato dai permessi dell'ambiente locale; la verifica completa
viene quindi effettuata su GitHub Actions. I test esistenti in
`tests/browser/check_ui.py` rimangono una verifica separata.

## Utilizzarlo con il proprio Chrome

```bash
python tools/playwriter_check.py --mcp-config
```

Il comando stampa una configurazione `mcpServers` con percorsi assoluti al Node
locale e al pacchetto installato. Inserirla nel client che supporta MCP. Per
Claude Code è possibile registrare lo stesso eseguibile con
`claude mcp add playwriter -- node /percorso/DriveNow/tools/playwriter/node_modules/playwriter/bin.js`.
Usare il percorso effettivo del proprio checkout. La configurazione non viene
applicata automaticamente al client né alla sessione ChatGPT aperta.

Per usare Chrome già aperto, installare l'[estensione ufficiale](https://chromewebstore.google.com/detail/playwriter/jfeammnjpkecdekppnclgkkffahnhfhe)
e abilitarla sulla scheda da controllare. Avviare DriveNow con
`python -m drivenow.server`, poi chiedere al client collegato:

> Con Playwriter verifica la scheda DriveNow su http://localhost:8000.
> Controlla mappa, cambio veicolo, inseguimento, zoom e parametri. Riporta
> soltanto problemi osservati e come riprodurli. Usa soltanto la scheda
> DriveNow e chiudi esclusivamente le schede che hai creato tu.

Playwriter supporta anche CDP diretto senza estensione, come nella CI; la porta
di debugging va attivata nel browser che si intende controllare. Il collegamento
al proprio profilo richiede la configurazione locale e, se Chrome la mostra,
la sua conferma di accesso. Non viene attivato dal semplice push della repo.

L'ambiente di test disabilita la telemetria tramite `PLAYWRITER_TELEMETRY=0`
e `DO_NOT_TRACK=1`; la configurazione generata conserva queste impostazioni.
Non installiamo skill personali o comandi globali, non abilitiamo servizi cloud
Playwriter e non modifichiamo il browser personale durante il test.
