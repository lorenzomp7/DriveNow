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
  server.py       server della mappa (HTTP + Server-Sent Events, solo libreria standard)
web/              mappa: index.html, style.css, app.js
data/sumo/        reti della repository Traffc_light_control
tests/            pytest (i test SUMO si saltano se SUMO non è installato)
```

Test:

```bash
pip install pytest
python -m pytest
```
