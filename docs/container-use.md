# Ambienti di sviluppo isolati con container-use

DriveNow configura [dagger/container-use](https://github.com/dagger/container-use)
alla release **v0.4.2**, commit `89ebe7765ec067a07c51de104822056eb217c1b9`.
La configurazione `.container-use/environment.json` viene letta dal tool reale:
Python 3.12.12 su Debian Bookworm, Git e pytest, nella cartella `/workdir`.

L'ambiente base è per motore e demo HTTP. SUMO, browser e modelli Darts restano
installazioni opzionali per i lavori che ne hanno bisogno; non vengono
scaricati in ogni nuovo ambiente. L'immagine ha un tag di versione esplicito,
ma non è fissata a un digest immutabile.

## Installazione locale

Serve Git con cronologia completa (checkout non shallow) e un **motore Docker avviato**. Su Windows la strada consigliata è
WSL2 con l'integrazione Docker Desktop abilitata; tenere repo, Python e client
MCP nello stesso ambiente WSL. Su Linux/macOS usare il Docker locale.
Il codice dell'installer gestisce anche i pacchetti Windows nativi, ma questo
percorso non è stato verificato qui.

```bash
python tools/container_use.py install
python tools/container_use.py doctor
```

L'installer scarica l'archivio ufficiale della versione fissata e verifica
SHA-256 prima di estrarre il solo binario e la licenza. Li conserva in `.tools/`,
esclusa da Git; non installa globalmente e non esegue script remoti.
`doctor` mostra la versione e verifica `docker info`: exit code 2 significa
prerequisiti mancanti. Non avvia Docker e non dichiara eseguito alcun container.

## Collegamento MCP

```bash
python tools/container_use.py mcp-config
```

Il comando produce una configurazione `mcpServers` con percorsi assoluti,
riutilizzabile nel proprio client MCP. Per Codex CLI si può registrare il server
con `codex mcp add container-use -- python /percorso/assoluto/DriveNow/tools/container_use.py stdio`,
sostituendo il percorso e usando il Python dello stesso ambiente di Docker.
Il wrapper avvia `.tools/container-use stdio` nella cartella del progetto.
Non modifica le impostazioni globali del client e non abilita nuovi strumenti
nella sessione ChatGPT già aperta.

Prompt d'esempio per un client collegato:

> Crea un ambiente container-use da `main_chatgpt` della repo DriveNow per
> questa singola modifica. Usa la configurazione del progetto, implementa il
> cambiamento e lancia `python -m pytest -q`. Condividi ID, log e diff
> dell'ambiente. Per avviare la demo usa `python -m drivenow.server --port 8000`
> in background esponendo la porta 8000. Non unire automaticamente le modifiche.

Ogni ambiente ha il proprio ref `container-use/<id>`. I cambiamenti non sono
in `main_chatgpt` finché non vengono esaminati e applicati. Per esaminare un
ambiente usare il binario in `.tools/` con `list`, `log <id>` e `diff <id>`.
`merge <id>` e `apply <id>` modificano il branch corrente: usarli nell'ambito
del lavoro richiesto e dopo aver controllato il diff. Nessun lavoro parallelo
né agente aggiuntivo viene avviato da questa integrazione.

## Prova automatica del collegamento reale

```bash
python -m venv .venv-container-use
.venv-container-use/bin/python -m pip install -r requirements-container-use.txt
.venv-container-use/bin/python tools/container_use_smoke.py
```

Su Windows adattare il percorso a `Scripts/python.exe`, oppure usare WSL2.
La prova usa il client MCP Python per:

1. Clonare lo stato **committato** della repo in una cartella temporanea.
2. Avviare il server MCP ufficiale, controllare i tool e creare un ambiente.
3. Lanciare pytest e verificare pagina demo e `/api/network` nel container.
4. Controllare gli errori MCP e il marcatore `DRIVENOW_CONTAINER_DEMO_OK`.
5. Eliminare soltanto l'ambiente temporaneo appena creato.

Il processo restituisce un errore se manca Docker o se un controllo fallisce.
Non unisce branch, non pubblica modifiche e non avvia modelli AI. La creazione
richiede rete per immagine e pacchetti; Dagger può inoltre scaricare il proprio
motore nel Docker host. La prima esecuzione può richiedere diversi minuti.

Il workflow `Container-use integration` esegue la stessa prova su Ubuntu con
Docker. L'ambiente locale di questa sessione ha consentito di verificare il
binario v0.4.2 e il controllo HTTP, ma **non dispone di Docker**: il risultato
della prova completa va letto nell'esecuzione GitHub Actions, separatamente
dai controlli locali. La configurazione MCP richiede comunque un client connesso
sul computer in cui si vuole utilizzare il tool.

Per aggiornare la versione ricontrollare protocollo, schema della configurazione
e checksum degli archivi ufficiali; poi ripetere la verifica con Docker.

Su runner Linux che usano soltanto nftables, Dagger 0.18 può riavviarsi perché
le tabelle NAT legacy non sono caricate. La CI carica `ip_tables` e
`iptable_nat` sul proprio host temporaneo e verifica `iptables-legacy -t nat -S`
prima dell'avvio. Il tool non applica questa modifica al computer dell'utente.
