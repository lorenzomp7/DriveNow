# Verificare l’interfaccia di DriveNow

## Test automatici senza chiavi AI

```bash
python -m pip install -r requirements-ui.txt
python -m playwright install chromium
python tests/browser/check_ui.py
```

Il controllo avvia e arresta un server demo su una porta libera, apre Chromium
in formato desktop e telefono e verifica connessione live, avanzamento del tempo,
consiglio al veicolo, cambio veicolo, inseguimento, zoom e invio/applicazione dei
parametri della simulazione. Non richiede SUMO. Il workflow `Browser checks`
esegue anche i test Python su push a `main` e `main_chatgpt` e sulle pull request.
Queste verifiche non certificano la correttezza fisica del modello né la resa
visiva di ogni elemento del canvas; i test Python coprono il motore separatamente.

## Integrazione vibetest-use

Il comando `python tools/vibetest_drive.py` usa davvero il motore `run_pool`
di [vibetest-use](https://github.com/browser-use/vibetest-use), fissato al
commit `fe0b90ac9d6a129ce06f5b53074241a9f205015b`. Non serve un client MCP:
l'adattatore avvia una singola esplorazione headless della demo DriveNow e
salva il risultato JSON per la revisione. Nessuna chiamata AI parte dal server
DriveNow o dai normali test automatici.

### Installazione separata (Python 3.12)

```bash
python -m venv .venv-vibetest
.venv-vibetest/bin/python -m pip install -r requirements-vibetest.txt
.venv-vibetest/bin/python -m playwright install chromium
.venv-vibetest/bin/python tools/vibetest_drive.py --check
```

Su Windows usare `.venv-vibetest\Scripts\python.exe` al posto di
`.venv-vibetest/bin/python`. Su Linux possono servire le dipendenze di sistema:
`python -m playwright install --with-deps chromium` nell'ambiente dedicato.

`--check` verifica import, costruttori compatibili e presenza del browser:
non apre il browser e non chiama Google. Il workflow `Vibetest integration`
esegue questo controllo senza chiavi. La verifica non equivale a un test AI.

### Esecuzione

Avviare la demo in un terminale:

```bash
python -m drivenow.server --seed 1 --speed 5 --penetration 1 --demand 600
```

Nel terminale con l'ambiente dedicato, fornire `GOOGLE_API_KEY` nell'ambiente
locale e scegliere con `--model` un modello Gemini disponibile per la chiave:

```bash
.venv-vibetest/bin/python tools/vibetest_drive.py --model NOME_MODELLO_DISPONIBILE
```

La chiave non va salvata nei file del progetto. Non esiste un modello predefinito:
i modelli hardcoded upstream sono superati. Si può anche impostare
`VIBETEST_MODEL`. La disponibilità effettiva va verificata con il proprio account.
L'esplorazione invia contenuti della demo al modello e può consumare credito API.

Opzioni: `--url http://127.0.0.1:8000`, `--timeout 600` (secondi),
`--output test-results/vibetest.json`. Il server deve essere raggiungibile
dallo stesso ambiente del runner. SUMO/Amburgo richiedono i propri dati e dipendenze.

Il runner controlla mappa, selezione veicolo, inseguimento, zoom, spostamento e
parametri della simulazione. Il rapporto contiene i risultati grezzi degli
agenti e richiede sempre revisione umana. Exit code 0 significa che
l'esplorazione ha restituito un rapporto, **non** che l'interfaccia sia priva di
bug. Errori o risposte vuote producono exit code 1; configurazione, timeout o
errori di avvio producono 2. Non sostituisce Playwright, non garantisce una
copertura mobile e non verifica la correttezza matematica di GLOSA.

### Compatibilità e manutenzione

`requirements-vibetest.txt` blocca le dipendenze risolte su Python 3.12;
`requirements-vibetest.in` conserva i vincoli diretti. `browser-use==0.7.9`
preserva `BrowserSession`, rimosso nella versione 1.0. Aggiornare deliberatamente
con `uv pip compile requirements-vibetest.in -o requirements-vibetest.txt`,
poi ripetere installazione pulita, `--check` e test del runner.

L'adattatore sostituisce temporaneamente il selettore del modello e lo scout
upstream con un compito specifico DriveNow, poi ripristina entrambi. Legge lo
stato `_test_results` del commit fissato, evitando il riepilogo upstream che usa
un altro modello obsoleto e può mascherare agenti falliti. Non modifica il
pacchetto installato. Un aggiornamento upstream richiede di verificare anche
questi punti di integrazione. L'ambiente, i rapporti e le chiavi restano esclusi
dal versionamento; nessuna dipendenza AI entra nel runtime del server.
