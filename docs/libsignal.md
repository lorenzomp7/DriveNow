# Collegamento sperimentale a LibSignal

`drivenow.libsignal.LibSignalAdvisor` collega DriveNow al mondo **SUMO** di
[DaRL-LibSignal/LibSignal](https://github.com/DaRL-LibSignal/LibSignal),
verificato al commit `127af9f93902778e556de2eedb2b606c4c9447e6`.

LibSignal decide i semafori e avanza la simulazione; DriveNow legge da
`world.eng` (TraCI o interfaccia equivalente libsumo) posizioni, percorsi e
velocità, costruisce le code e calcola i consigli. Non sostituisce il programma
semaforico e non avvia un secondo SUMO. L'applicazione delle velocità è opzionale.
Il modulo non importa LibSignal né librerie AI: il server demo rimane indipendente.

## Uso nel ciclo di LibSignal

Rendere importabile la cartella DriveNow nell'ambiente in cui si esegue
LibSignal (per esempio aggiungendola a `PYTHONPATH`). Dopo la creazione del
proprio `world` SUMO e dei propri agenti:

```python
from drivenow.libsignal import LibSignalAdvisor

world.reset()
bridge = LibSignalAdvisor(world, penetration=0.5, seed=1)
try:
    for actions in sequenza_azioni_del_proprio_controllore:
        world.step(actions)
        consigli = bridge.step(apply=True)
finally:
    bridge.release()  # prima di chiudere la connessione SUMO
```

`sequenza_azioni_del_proprio_controllore` rappresenta le azioni già prodotte
dal proprio esperimento LibSignal; non è una funzione aggiunta da DriveNow.
`bridge.step()` senza `apply=True` legge e restituisce i consigli senza scrivere
velocità. Chiamarlo una volta dopo ogni passo che fa avanzare il tempo; dopo
`world.reset()` creare un nuovo adapter. La quota equipaggiata è stabile per
ID veicolo e seme. Il controllo rilascia le auto vicino o dentro gli incroci,
quando manca il consiglio e alla chiusura dell'esperimento. Mantiene i controlli
SUMO predefiniti; non cambia speedMode o laneChangeMode.

## Finestre di verde: contratto esplicito

La rete XML può contenere un piano fisso che LibSignal sostituisce. Per questo
l'adapter **ignora sempre quel piano come previsione**. Senza una fonte esplicita
di finestre future non emette consigli basati su un verde garantito. Continua
comunque a leggere i veicoli e calcolare ciò che il motore può ricavare senza
prevedere le luci. Questo comportamento non dimostra un beneficio GLOSA.

Per un controllore che rende disponibile un programma impegnativo e noto:

```python
bridge = LibSignalAdvisor(world, windows_fn=finestre_impegnate,
                          penetration=0.5, seed=1)
```

Il callback `finestre_impegnate(edge_id, next_edge_id, t)` restituisce
`([(inizio, fine), ...], nome_gruppo)` oppure `None` se non conosce quel movimento.
Gli intervalli sono in secondi **relativi a `t`**, solo per verdi garantiti,
escludendo il giallo. Una lista vuota indica nessun verde noto nell'orizzonte;
`None` indica assenza di previsione. I margini del motore DriveNow restano attivi.
Il chiamante deve mantenere la previsione coerente con le successive azioni
semaforiche: il solo colore attuale o l'XML non bastano per un agente adattivo.
Questa integrazione non aggiunge un previsore di azioni RL.

## Verifica ripetibile con LibSignal reale

Da DriveNow, con Python 3.12, creare un ambiente separato:

```bash
python -m venv .venv-libsignal
.venv-libsignal/bin/python -m pip install -r requirements-libsignal.txt
git clone https://github.com/DaRL-LibSignal/LibSignal.git ../LibSignal
git -C ../LibSignal checkout 127af9f93902778e556de2eedb2b606c4c9447e6
.venv-libsignal/bin/python tools/libsignal_smoke.py --libsignal-root ../LibSignal
```

Su Windows usare `.venv-libsignal\Scripts\python.exe`.
Lo script carica il modulo SUMO reale dal checkout indicato, senza importare
il pacchetto `world` che richiederebbe anche CityFlow. Non modifica upstream.
Crea in una cartella temporanea un flusso sintetico sulla rete 1×1 di DriveNow,
inizializza `World`, esegue 90 passi con azioni alternate, calcola i consigli e
verifica che l'adapter non cambi lo stato delle luci. L'inizializzazione upstream
esegue inoltre 500 passi per individuare le fasi, prima del reset del controllo.
Non allena agenti e non scarica dati o modelli durante l'esecuzione.

Il workflow `LibSignal integration` ripete questa verifica e i test del ponte.
La prova locale ha prodotto 1.865 campioni veicolo; è un controllo di
compatibilità, **non un benchmark di traffico**. CityFlow, addestramento RL e
confronti prestazionali non sono inclusi. Il percorso TraCI è verificato dal
controllo reale; il backend libsumo non è stato eseguito.

Per confrontare algoritmi usare lo stesso scenario, domanda, durata e warm-up,
più semi e quote DriveNow 0%/100%; riportare viaggi finiti, tempo di viaggio,
fermate ed energia nei freni. Non confondere un consiglio restituito con una
riduzione misurata delle fermate. Il modello DriveNow aggrega le auto per
strada e non distingue le corsie; le svolte con code separate richiedono cautela
nell'interpretazione degli esperimenti.

Nessun sorgente o dataset di LibSignal viene redistribuito: restano nel checkout
esterno con le proprie condizioni d'uso e attribuzioni. Il commit fissato e i
punti di collegamento (`World.net`, `World.eng`, `World.interval`, `step/reset`)
vanno ricontrollati prima di aggiornare upstream.
