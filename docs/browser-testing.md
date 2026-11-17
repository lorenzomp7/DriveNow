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

## Esplorazione con vibetest-use (facoltativa)

Repository: https://github.com/browser-use/vibetest-use

Vibetest è uno strumento esterno di sviluppo: non è una dipendenza del server
DriveNow. Richiede Python 3.11+, un client MCP e una chiave Google API.
Il README upstream indica Gemini 2.0 Flash: prima di usarlo verificare che il
modello configurato sia ancora disponibile per la propria chiave. Nessuna
esecuzione AI viene effettuata dal workflow automatico.

Installazione in una cartella separata, secondo le istruzioni upstream:

```bash
git clone https://github.com/browser-use/vibetest-use.git
cd vibetest-use
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m playwright install chromium --with-deps --no-shell
```

Configurare il client MCP con il percorso assoluto dell’eseguibile
`.venv/bin/vibetest-mcp`, fornendo `GOOGLE_API_KEY` tramite la configurazione
locale del client. Non salvare la chiave nella repo. Il servizio del modello
può avere costi e riceve i contenuti osservati dagli agenti.

Avviare DriveNow nello stesso ambiente raggiungibile dal browser degli agenti:

```bash
python -m drivenow.server --seed 1 --speed 5 --penetration 1 --demand 600
```

Prompt pronto da dare al client collegato a Vibetest:

> Verifica http://127.0.0.1:8000 con 1 agente in modalità headless.
> Controlla desktop 1440×900 e mobile 390×844. Aspetta che compaiano le auto.
> Verifica mappa e contatore live, selezione di un’auto sulla mappa,
> “Altro veicolo”, “Segui veicolo”, “Inquadra”, zoom e trascinamento.
> Prova 1×, 2×, 5× e 10×, quota DriveNow 0%, 50%, 100% e traffico minimo/massimo.
> Cerca sovrapposizioni, controlli non raggiungibili, errori JavaScript e
> incoerenze tra consiglio e veicolo selezionato. Non interpretare l’assenza
> iniziale di viaggi completati come errore. Riporta solo problemi osservati,
> con passi per riprodurli, formato schermo e screenshot quando disponibili.
> Non modificare codice e non valutare la sicurezza stradale del modello.

Per SUMO e Amburgo ripetere l’esplorazione con il relativo comando del README,
con dipendenze e dati installati. Il test automatico copre soltanto la demo.
