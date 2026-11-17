# DriveNow

**La velocità giusta per non frenare.** DriveNow calcola, in tempo reale, per
ogni tratto di strada e per ogni auto, la fascia di velocità (minima e
massima) con cui si arriva al prossimo semaforo **quando è verde**, senza
mai dover frenare. Per rotonde e incroci con precedenza calcola invece la
velocità massima da cui basta alzare il piede per arrivarci alla velocità
giusta.

Esempio: il semaforo diventa verde tra un minuto. Invece di andare a 50 km/h,
fermarsi e ripartire, DriveNow ti dice di scendere, per esempio, a 31 km/h
(fascia 24–36): se la tieni, arrivi alla linea proprio quando scatta il verde.
In letteratura questa tecnica si chiama GLOSA (*Green Light Optimal Speed
Advisory*).

![Mappa DriveNow](docs/screenshot.png)

## Come si usa

Serve solo Python 3.9+, senza dipendenze esterne:

```bash
python -m drivenow.server
```

Poi apri <http://localhost:8000>. La mappa si aggiorna 5 volte al secondo:

- **le strade sono colorate** con la fascia di velocità valida da quel punto:
  verde vuol dire che al limite arrivi col verde, arancione che devi
  rallentare (l'etichetta, per esempio `18–35`, dice di quanto), rosso che il
  rosso è inevitabile, viola che c'è una rotonda o una precedenza;
- **i semafori** mostrano il colore e i secondi al prossimo cambio;
- **il pannello "Il tuo veicolo"** segue un'auto e le dà il consiglio come lo
  vedrebbe un guidatore: velocità consigliata, fascia, prossimo incrocio,
  conto alla rovescia del semaforo;
- **il confronto** misura, sui viaggi completati, fermate, frenate, energia
  buttata nei freni e tempo di viaggio delle auto che seguono il consiglio
  rispetto a quelle che non lo seguono.

Clic su un'auto per seguirla, rotella per lo zoom, trascina per spostarti.

### Con le reti di Traffc_light_control

DriveNow parte dalla repository
[lorenzomp7/Traffc_light_control](https://github.com/lorenzomp7/Traffc_light_control):
legge le stesse reti SUMO (`.net.xml`, copiate in `data/sumo/`) e può far
girare il traffico direttamente in SUMO tramite TraCI.

```bash
python -m drivenow.server --net data/sumo/3_3_intersections.net.xml          # simulatore interno
```

```bash
pip install eclipse-sumo traci
python -m drivenow.server --sumo --net data/sumo/3_3_intersections.net.xml   # traffico in SUMO
```

Con `--sumo --gui` si apre anche `sumo-gui`.

Nella repository base i semafori sono comandati da un agente (PPO o regole),
che decide passo per passo: per questo nel file di rete le fasi durano 100000
secondi, e i tempi futuri non si possono conoscere. DriveNow installa quindi
in SUMO il ciclo fisso del `CycleRuleSet` della repository (20 s di verde per
direzione più 3 s di giallo), così la previsione e ciò che fa SUMO sono la
stessa cosa. Un test lo verifica confrontando ogni passo.

### Opzioni

| Opzione | Default | Cosa fa |
|---|---|---|
| `--net FILE` | città demo | rete SUMO da caricare |
| `--sumo` | no | fa girare il traffico in SUMO |
| `--speed N` | 1 | velocità della simulazione (1 = tempo reale) |
| `--penetration P` | 0.5 | quota di auto che seguono DriveNow (0–1) |
| `--demand N` | 240 | auto/ora per ogni strada di ingresso |
| `--port N` | 8000 | porta del server |

Velocità, quota DriveNow e traffico si cambiano anche dal pannello.

## Come funziona il calcolo

Tutto il calcolo è in `drivenow/glosa.py`, separato da mappa e simulazione.

1. **Finestre di verde.** Dal piano semaforico (`drivenow/signals.py`) si
   ricavano gli intervalli di verde futuri per la corsia dell'auto.
2. **Margini e traffico.** Ogni finestra si restringe: si arriva almeno 1 s
   dopo lo scatto del verde e almeno 1 s prima del giallo. Se c'è coda, il
   verde "utile" parte dopo 2 s più 2 s per ogni auto in coda. Se davanti c'è
   un'auto in movimento, non si può arrivare prima di lei più 1,5 s. Il giallo
   non conta mai come verde: DriveNow non consiglia di passare col giallo.
3. **Modello senza freno.** Per cambiare velocità il guidatore non frena: se
   deve rallentare alza il piede e l'auto decelera da sola (circa 0,7 m/s²);
   se deve accelerare lo fa a 1,3 m/s². Il tempo di arrivo alla linea tiene
   conto di questa transizione.
4. **Fascia.** Si cercano tutte le velocità tra 15 km/h e il limite che
   portano alla linea dentro una finestra di verde. Gli estremi della fascia si
   trovano per bisezione, perché il tempo d'arrivo cala sempre al crescere
   della velocità.
5. **Velocità consigliata.** Dentro la fascia si punta ad arrivare 1,5 s dopo
   l'inizio del verde utile. Puntare a un orario, e non a un punto della
   fascia, rende il consiglio stabile: chi lo segue riceve lo stesso numero
   all'aggiornamento successivo.
6. **Rotonde e precedenze.** La velocità massima è quella da cui, alzando il
   piede, si arriva all'ingresso a 25 km/h (20 km/h per una precedenza):
   `v = √(v_ingresso² + 2·0,7·d)`.

Se nessuna velocità prende il verde, il consiglio è di lasciar scorrere l'auto
fino alla linea, così si arriva piano e senza frenate brusche.

La mappa (`Advisor.speed_field`) usa lo stesso calcolo per un'auto che sta già
viaggiando a velocità costante, ogni 20 m di ogni tratto che porta a un
semaforo, a una rotonda o a una precedenza.

## Risultati in simulazione

Traffico simulato con il 100% delle auto DriveNow contro lo 0%, valori medi per
viaggio:

| Rete | Fermate | Frenate | Energia nei freni | Tempo di viaggio |
|---|---|---|---|---|
| Città demo (simulatore interno, 3 semi) | 1,33 → 0,55 | 2,49 → 1,32 | 96 → 25 kJ | 107 → 112 s (+4%) |
| Griglia 2×2 della repo base (SUMO, 30 min) | 1,35 → 0,16 | 2,60 → 0,73 | 146 → 20 kJ | 92 → 95 s (+3%) |
| Griglia 3×3 della repo base (SUMO, 30 min) | 2,23 → 0,23 | 4,59 → 1,11 | 230 → 28 kJ | 133 → 136 s (+2%) |

Il piccolo aumento del tempo di viaggio ha due cause. Chi segue DriveNow
rallenta prima delle rotonde invece di frenare all'ultimo. E non sfrutta mai
il giallo, mentre in simulazione i guidatori normali lo fanno.

Nella città demo restano più fermate che in SUMO perché ci sono una rotonda e
una precedenza con traffico vero, dove a volte fermarsi è inevitabile.

Per default si guarda solo il prossimo semaforo. Il calcolo sa concatenarne
più d'uno (`max_signals`) per cercare un'onda verde. In simulazione però
costava circa 3 s a viaggio senza togliere fermate, perché le code ai
semafori successivi non sono prevedibili.

## Dati reali: Amburgo

Per provare DriveNow su dati veri c'è uno scenario reale: il corridoio di
Willy-Brandt-Straße / Ludwig-Erhard-Straße, nel centro di Amburgo (circa
1,9 km, 9 impianti semaforici), nell'ora di punta di giovedì 14 settembre
2023, dalle 17 alle 18.

```bash
pip install eclipse-sumo traci sumolib
python -m drivenow.server --hamburg
```

Da dove vengono i dati:

- **Semafori: reali.** Sono gli stati registrati secondo per secondo dalla
  città di Amburgo, nella raccolta pubblicata dalla TU Dresden. Ogni passo,
  SUMO mostra lo stato registrato in quel momento.
- **Mappa: reale.** Viene da OpenStreetMap, convertita in rete SUMO. I
  semafori stanno dove li ha Amburgo; dove Amburgo non fornisce dati restano
  quelli di OpenStreetMap, con un programma fisso stimato da SUMO.
- **Traffico: in parte reale.** Dove esistono, i volumi sono tarati sui
  conteggi dei rilevatori di Amburgo in quell'ora. L'asse principale non ha
  rilevatori, quindi lì il volume è un'ipotesi (400 auto/ora per tratto).

Dettagli, fonti e licenze sono in [`data/hamburg/README.md`](data/hamburg/README.md).
Tutto si ricostruisce con `python tools/hamburg_build.py --cache CARTELLA`.

### Previsione dei semafori

Questi semafori hanno un ciclo fisso (45–90 s a seconda dell'impianto e
dell'ora), ma la durata del verde varia con il traffico. DriveNow non
guarda il futuro registrato. Per ogni segnale impara dagli ultimi 20 cicli
la probabilità di verde in ogni secondo del ciclo, e considera verde un
secondo futuro solo se quella probabilità arriva all'80%
(`drivenow/hamburg/signals.py`).

Ecco quanto la previsione indovina lo stato reale nell'ora di prova:

| Fra | 5 s | 15 s | 30 s | 60 s | 90 s |
|---|---|---|---|---|---|
| Stato corretto | 93,4% | 92,5% | 92,1% | 92,2% | 91,7% |
| Previsto verde, era rosso | 1,0% | 1,1% | 0,5% | 0,5% | 0,5% |
| Verde reale non previsto | 5,6% | 6,4% | 7,4% | 7,4% | 7,8% |

L'errore pericoloso, cioè promettere un verde che non arriva, è raro. Quello
più frequente è prudente: un verde reale che il modello non dà per certo.

### Effetto in simulazione

Ogni esperimento dura un'ora; il confronto è tra 0% e 100% di auto DriveNow.
L'"oracolo" usa il futuro registrato al posto della previsione e indica il
massimo ottenibile con una previsione perfetta.

| Traffico | Consiglio | Fermate | Frenate | Energia nei freni | Tempo |
|---|---|---|---|---|---|
| Ora di punta | nessuno | 3,44 | 12,15 | 387 kJ | 329 s |
| | previsione | 3,21 | 10,63 | 308 kJ | 336 s |
| | oracolo | 3,15 | 10,78 | 317 kJ | 327 s |
| Metà traffico | nessuno | 2,93 | 10,54 | 398 kJ | 254 s |
| | previsione | 2,90 | 10,13 | 326 kJ | 259 s |
| | oracolo | 2,89 | 10,13 | 328 kJ | 259 s |

L'energia buttata nei freni cala del 18–20% e le frenate dal 4 al 13%. Le
fermate, invece, quasi non cambiano. Contando dove si fermano le auto (metà
traffico, primi 25 minuti), il motivo si vede:

| Dove avviene la fermata | Quota |
|---|---|
| Semafori presi da OpenStreetMap, senza dati reali e quindi senza consiglio | 53% |
| Incroci con precedenza | 24% |
| I 9 impianti con dati reali di Amburgo | 23% |

Su questi ultimi, con l'oracolo, le fermate calano del 10%. Il collo di
bottiglia quindi non è la previsione, che è quasi buona quanto l'oracolo, ma
la **copertura**: dei 35 impianti semaforici della zona simulata, solo 9
hanno dati reali. Il passo successivo è scegliere un corridoio in cui tutti i semafori
sono coperti (la città ne pubblica circa 800) e ripetere la misura.

## Dal simulatore alla strada vera

Il motore di calcolo non sa da dove arrivano i dati. La simulazione interna e
il ponte SUMO gli passano la stessa cosa: piani semaforici, posizioni e
velocità dei veicoli. Per usarlo su strade reali bisogna sostituire queste due
fonti:

- **Tempi dei semafori.** Lo standard è il messaggio SPaT/MAP (ETSI
  SPATEM/MAPEM in Europa, SAE J2735 negli USA). Lo trasmettono le unità C-ITS
  a bordo strada e alcune centrali del traffico cittadine. Dove non c'è, i
  tempi si possono stimare dai passaggi osservati, e la stima va mostrata con
  la sua incertezza. Con semafori adattivi (come l'agente PPO della
  repository base) servono la previsione della centrale o un modello
  predittivo.
- **Posizione e traffico.** GPS dello smartphone o dell'auto per la propria
  posizione, dati di traffico (o i veicoli connessi) per code e veicolo
  davanti.
- **Mappa.** La geometria va presa da OpenStreetMap o dai MAPEM, al posto
  della rete SUMO.

## Struttura

```
drivenow/
  glosa.py        calcolo: tempi d'arrivo, fasce, consiglio (nessuna dipendenza)
  signals.py      piani semaforici a tempo fisso e finestre di verde
  network.py      rete: città demo e caricatore .net.xml di SUMO
  advisor.py      unisce rete, traffico e calcolo: consiglio per veicolo e campo per la mappa
  simulation.py   simulatore interno (IDM, semafori, rotonda, precedenza)
  sumo_world.py   ponte TraCI con SUMO
  hamburg/        dati reali di Amburgo: storico e previsione dei semafori, mondo SUMO
  server.py       server della mappa (HTTP + Server-Sent Events, solo libreria standard)
web/              mappa: index.html, style.css, app.js
data/sumo/        reti della repository Traffc_light_control
data/hamburg/     scenario reale di Amburgo (rete, semafori registrati, traffico)
tools/            costruzione dello scenario di Amburgo, esperimenti, registrazione delle pagine
tests/            pytest (i test SUMO si saltano se SUMO non è installato)
```

Test:

```bash
pip install pytest
python -m pytest
```
