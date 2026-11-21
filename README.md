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
- **i semafori** mostrano il colore e i secondi al prossimo cambio. Quando
  segui un'auto restano in evidenza solo i prossimi due sul suo percorso (il
  primo con un anello bianco); gli altri si attenuano e perdono i secondi. Il
  pulsante "Solo il suo percorso" li mostra di nuovo tutti;
- **il pannello "Il tuo veicolo"** segue un'auto e le dà il consiglio come lo
  vedrebbe un guidatore: velocità consigliata, fascia, prossimo incrocio,
  conto alla rovescia del semaforo e, alla voce "Poi", il semaforo dopo;
- **il confronto** misura, sui viaggi completati, fermate, frenate, energia
  buttata nei freni e tempo di viaggio delle auto che seguono il consiglio
  rispetto a quelle che non lo seguono.

Clic su un'auto per seguirla, rotella per lo zoom, trascina per spostarti.

### Con le reti di Traffc_light_control

DriveNow è nato dalla repository Traffc_light_control (ora dismessa): ne usa
le reti SUMO a griglia 1×1, 2×2, 3×3 e 4×4 (`.net.xml`, copiate in `data/sumo/`) e può far
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
| `--autopilot` | no | le auto DriveNow guidano da sole con i propri sensori (simulatore interno) |
| `--sensors S` | camera+radar | `perfect`, `radar`, `camera`, `camera+radar`, `camera+radar+lidar` |
| `--weather W` | clear | `clear`, `night`, `rain`, `fog` |
| `--no-light-timing` | no | con `--autopilot`: tempi dei semafori sconosciuti, solo la telecamera li legge |
| `--double-parking N` | 0 | N auto all'ora si fermano nella corsia per 15–40 s |

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
7. **Varchi nella strada principale.** A una precedenza DriveNow guarda le
   auto sulla strada principale, fino a 150 m per lato, e calcola quando
   l'incrocio è libero: da 3,5 s prima a 1,5 s dopo il passaggio di ogni auto
   è occupato. Se alla solita velocità si arriva in un varco, il consiglio
   resta il tetto del punto 6. Altrimenti è la fascia di velocità che porta
   all'incrocio nel varco successivo, come per un verde; se nessuna velocità
   ragionevole ci arriva, si lascia scorrere l'auto fino alla linea. Chi gira
   a destra dà precedenza solo a chi va nella stessa direzione; chi gira a
   sinistra lasciando la strada principale dà precedenza al traffico che
   arriva di fronte. Se un'auto segue a meno di 30 m, niente rallentamento in
   anticipo: la si costringerebbe a frenare. Serve sapere dove sono le auto
   sulla strada principale: un sensore all'incrocio o le auto stesse che
   condividono la posizione.

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
| Città demo (simulatore interno, 3 semi) | 1,33 → 0,52 | 2,49 → 1,31 | 96 → 23 kJ | 107 → 112 s (+4%) |
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

Per provare DriveNow su dati veri ci sono due scenari reali di Amburgo,
entrambi nell'ora di punta di giovedì 14 settembre 2023, dalle 17 alle 18:

- **Gärtnerstraße** (default): Osterstraße → Gärtnerstraße → Breitenfelder
  Straße, circa 1,8 km. Quasi tutti i semafori del tratto hanno dati reali.
- **Willy-Brandt-Straße / Ludwig-Erhard-Straße**, nel centro (circa 1,9 km,
  9 impianti semaforici con dati, molti altri senza).

```bash
pip install eclipse-sumo traci sumolib
python -m drivenow.server --hamburg                 # Gärtnerstraße
python -m drivenow.server --hamburg willy-brandt
```

Da dove vengono i dati:

- **Semafori: reali.** Sono gli stati registrati secondo per secondo dalla
  città di Amburgo, nella raccolta pubblicata dalla TU Dresden. Ogni passo,
  SUMO mostra lo stato registrato in quel momento.
- **Mappa: reale.** Viene da OpenStreetMap, convertita in rete SUMO. I
  semafori stanno dove li ha Amburgo; dove Amburgo non fornisce dati restano
  quelli di OpenStreetMap, con un programma fisso stimato da SUMO.
- **Traffico: in parte reale.** Dove esistono, i volumi sono tarati sui
  conteggi dei rilevatori di Amburgo in quell'ora. Dove mancano rilevatori
  (l'asse principale di Willy-Brandt-Straße, alcuni tratti di Gärtnerstraße)
  il volume è un'ipotesi, scritta in `scenario.json`.

Dettagli, fonti e licenze sono in [`data/hamburg/README.md`](data/hamburg/README.md).
Tutto si ricostruisce con
`python tools/hamburg_build.py --scenario gaertnerstrasse --cache CARTELLA`
(o `--scenario willy-brandt`).

### Previsione dei semafori

Questi semafori hanno un ciclo fisso (45–90 s a seconda dell'impianto e
dell'ora), ma la durata del verde varia con il traffico. DriveNow non
guarda il futuro registrato. Per ogni segnale impara dagli ultimi 20 cicli
la probabilità di verde in ogni secondo del ciclo, e considera verde un
secondo futuro solo se quella probabilità arriva all'80%
(`drivenow/hamburg/signals.py`).

Il ciclo viene dal dato "secondo del ciclo" che ogni impianto pubblica. Quel
dato però ha buchi lunghi nella registrazione: a Gärtnerstraße manca per
quasi tutta l'ora di prova. In quel caso il ciclo si ricava dagli inizi del
verde del semaforo stesso. Se non c'è un ciclo regolare (una strada
principale che diventa rossa solo a richiesta), la previsione è la quota di
tempo in cui il semaforo è stato verde nell'ultima mezz'ora. Se non si sa
proprio nulla, DriveNow non dà consigli per quel semaforo, invece di
considerarlo sempre rosso.

Ecco quanto la previsione indovina lo stato reale nell'ora di prova
(Willy-Brandt-Straße):

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

Le fermate alle precedenze sono quasi tutte inevitabili: l'asse principale
ha tanto traffico che varchi di 5 secondi non se ne aprono quasi mai, e il
consiglio giusto resta lasciar scorrere l'auto fino alla linea. Il consiglio
sui varchi (punto 7) aiuta invece chi gira a sinistra lasciando l'asse. Media
di due simulazioni, ora di punta, previsione:

| Precedenze | Fermate | Frenate | Energia nei freni | Tempo |
|---|---|---|---|---|
| Solo tetto di velocità | 3,21 | 10,67 | 309 kJ | 331 s |
| Varchi | 3,23 | 10,48 | 283 kJ | 340 s |
| Varchi, ma non con un'auto vicina dietro (default) | 3,22 | 10,59 | 288 kJ | 333 s |

Puntare ai varchi toglie il 7–8% dell'energia nei freni. Senza la regola
sull'auto che segue costa però il 2,6% di tempo, perché chi rallenta per
girare a sinistra rallenta anche chi gli sta dietro; con la regola il costo
scende allo 0,7%. Nella città demo, dove la precedenza ha meno traffico, i
varchi tolgono l'11–13% dell'energia nei freni senza costi di tempo.

Sui 9 impianti con dati reali, con l'oracolo, le fermate calano del 10%. Il collo di
bottiglia quindi non è la previsione, che è quasi buona quanto l'oracolo, ma
la **copertura**: dei 35 impianti semaforici della zona simulata, solo 9
hanno dati reali. Per questo c'è il secondo scenario.

### Semafori senza dati: imparati dalle auto

Molti semafori non pubblicano nulla. Le auto DriveNow però li vedono ogni
giorno, e da quello che fanno si ricava il loro orario
(`drivenow/probe.py`):

- un'auto ferma alla linea che riparte: il verde è appena cominciato;
- un'auto che passa la linea: è verde;
- un'auto ferma alla linea: è rosso.

Dagli inizi del verde si trova la durata del ciclo (quella per cui cadono
tutti nello stesso punto del ciclo); la fine del verde sta tra gli ultimi
passaggi e le prime auto ferme al rosso. Se le osservazioni non stanno in un
ciclo fisso, il semaforo resta senza previsione.

Willy-Brandt-Straße, dopo 40 minuti di ora di punta con il 100% di auto
DriveNow: 48 dei 98 accessi semaforici senza dati di Amburgo sono stati
imparati (gli altri hanno visto troppo poche auto). Su questi la previsione è
giusta il 93,5% delle volte, da 0 a 60 s in avanti: un verde promesso che non
arriva nel 2,7% dei casi, un verde reale non previsto nel 3,8%. È quanto la
previsione costruita sui dati ufficiali.

Effetto in simulazione, un'ora, previsione e consiglio sulle precedenze
attivi in entrambi i casi:

| Scenario | Semafori senza dati | Fermate | Frenate | Energia nei freni | Tempo |
|---|---|---|---|---|---|
| Willy-Brandt-Straße (media di 2 semi) | nessun consiglio | 3,22 | 10,59 | 288 kJ | 333 s |
| | imparati dalle auto | 3,15 | 10,11 | 249 kJ | 349 s |
| Gärtnerstraße (metà traffico) | nessun consiglio | 1,03 | 2,87 | 118 kJ | 184 s |
| | imparati dalle auto | 0,97 | 2,80 | 107 kJ | 184 s |

L'energia buttata nei freni cala del 14% a Willy-Brandt-Straße (−21% per chi
percorre l'asse) e del 9% a Gärtnerstraße; le fermate del 2–6%. A
Willy-Brandt-Straße il tempo di viaggio sale del 5%: la previsione è
prudente e chi la segue a volte rallenta per un verde che sarebbe durato.
La misura è anche pessimista: le auto partono senza sapere nulla e nei primi
10–15 minuti nessun semaforo è ancora imparato, mentre in un servizio reale
l'orario imparato resta da un giorno all'altro.

Rispetto a nessun consiglio (tabella più sopra), a Willy-Brandt-Straße
DriveNow ora toglie l'8% delle fermate e il 36% dell'energia nei freni, per
il 6% di tempo in più.

### Code e incroci "precedenza a destra"

Due cause di fermata alle precedenze, sull'asse principale:

- **La coda del semaforo successivo che arriva fino all'incrocio.** La coda
  ora si conta lungo tutto il percorso fino al semaforo, non solo sul suo
  tratto d'accesso. E se davanti c'è una coda ferma senza un semaforo noto
  dietro (un semaforo senza dati, un incrocio intasato), si lascia scorrere
  l'auto fino alla fine della coda invece di frenare lì.
- **Gli incroci senza strada principale.** OpenStreetMap li segna come
  "precedenza a destra" (35 a Willy-Brandt-Straße); prima erano trattati
  come se nessuno dovesse dare precedenza. Ora ogni accesso dà precedenza a
  chi arriva da destra, con lo stesso consiglio sui varchi.

| Willy-Brandt-Straße | Fermate | Frenate | Energia nei freni | Tempo | Viaggi finiti |
|---|---|---|---|---|---|
| Prima (media di 2 semi) | 3,15 | 10,11 | 249 kJ | 349 s | 2.931 |
| Con code e precedenza a destra | 3,04 | 9,54 | 221 kJ | 337 s | 2.877 |

L'energia nei freni cala di un altro 11%, le fermate del 4% e anche il
tempo di viaggio scende del 4%. Le due parti contano in modo diverso: la
precedenza a destra da sola accorcia i tempi (−2,5%) senza cambiare
l'energia; il conteggio delle code toglie il 12% dell'energia. Un limite: le
auto finite nell'ora sono il 2% in meno, quindi qualche auto lenta in più
resta in rete alla fine e il tempo medio è un po' ottimista. A Gärtnerstraße,
che ha poche code di questo tipo, l'energia cala del 5% e il resto non
cambia.

Il modello non conosce le corsie: un'auto ferma nella corsia di svolta può
far rallentare chi va dritto. Nonostante questo il bilancio resta positivo.

Riassunto, Willy-Brandt-Straße all'ora di punta, 0% contro 100% di auto
DriveNow: fermate 3,44 → 3,04 (−12%), energia nei freni 387 → 221 kJ (−43%),
tempo di viaggio 329 → 337 s (+2%).

### Quando un semaforo cambia orario

Le città cambiano il piano dei semafori a orari fissi (punta, morbida,
notte), e un semaforo può guastarsi. Un orario imparato dalle auto resta
però valido per mezz'ora di osservazioni, e un cambio sposta poco
l'adattamento complessivo. Per questo, a ogni ricalcolo, DriveNow confronta
l'orario anche con i soli ultimi 5 minuti (`drivenow/probe.py`):

- **auto ferme alla linea quando l'orario dice verde**: è l'errore che conta,
  un verde promesso che non c'è (si escludono i primi secondi del verde,
  quando la prima auto sta ancora partendo);
- **auto che ripartono lontano dall'inizio del verde previsto**: un inizio del
  verde fuori posto di più di 5 s.

Se almeno il 30% delle auto ferme sta nel verde previsto, o se due terzi
degli inizi del verde sono fuori posto, l'orario è sbagliato: il semaforo
perde la previsione e le osservazioni più vecchie di 5 minuti si buttano,
così lo si reimpara solo dal comportamento nuovo.

La prima idea era più semplice: controllare la quota di osservazioni che
l'orario spiega negli ultimi minuti, come per l'adattamento complessivo. Non
funziona: un orario superato ne spiegava ancora, in mediana, il 91%. Dove il
verde occupa gran parte del ciclo, un orario che dice quasi sempre "verde"
indovina per caso.

Per provarlo, `HamburgWorld.replan` cambia il piano di tutti i semafori
senza dati di Amburgo: il verde dura dal 20% in meno al 25% in più e il ciclo
riparte da un punto a caso. `tools/probe_accuracy.py` confronta le previsioni
imparate con lo stato vero di SUMO, per il movimento che ogni auto sta per
fare. Willy-Brandt-Straße, un'ora, 100% di auto DriveNow:

| Previsioni imparate dalle auto | Giuste a 5 s | Verde promesso, era rosso (5 s) | (60 s) |
|---|---|---|---|
| Orari fissi, prima | 94,0% | 3,8% | 5,4% |
| Orari fissi, con il controllo | 94,2% | 3,8% | 5,3% |
| 15 minuti dopo il cambio, prima | 63,0% | 26,2% | 18,5% |
| 15 minuti dopo il cambio, con il controllo | 68,1% | 22,0% | 16,2% |

Con orari fissi il controllo non fa danni: in un'ora toglie la previsione a
circa 10 accessi, senza effetti sull'accuratezza. Dopo un cambio la migliora,
ma resta lontana da quella normale, perché servono qualche minuto di
osservazioni per accorgersene e qualche ciclo per reimparare.

Sulla guida l'effetto non si vede (media di 2 semi, 100% di auto DriveNow):

| Willy-Brandt-Straße | Fermate | Frenate | Energia nei freni | Tempo |
|---|---|---|---|---|
| Orari fissi, prima | 3,04 | 9,54 | 221 kJ | 337 s |
| Orari fissi, con il controllo | 3,03 | 9,52 | 222 kJ | 334 s |
| Cambio al minuto 30, prima | 3,04 | 9,63 | 228 kJ | 344 s |
| Cambio al minuto 30, con il controllo | 3,02 | 9,59 | 228 kJ | 341 s |

Il cambio di piano costa poco (+3% di energia nei freni) e le differenze
sono dentro il rumore tra un seme e l'altro. Il controllo resta come rete di
sicurezza: non costa niente e su strada evita che un orario superato venga
usato per mezz'ora.

**Orari "incerti": provati e lasciati spenti.** Si può anche dare una
previsione con meno osservazioni (3 inizi del verde invece di 5, adattamento
del 75% invece dell'85%), o declassare un orario con qualche errore recente,
marcandola come incerta: il consiglio la usa solo per rallentare al massimo
di 10 km/h, mai per lasciar scorrere l'auto fino alla linea, e la mappa
disegna quel semaforo come un cerchio vuoto con il conto alla rovescia
preceduto da "~". Le previsioni incerte sono giuste solo l'82% delle volte
(verde promesso che non arriva nel 13–15% dei casi), mentre quelle confermate
promettono un verde falso un po' meno spesso (2,6% invece di 3,8%). Sulla
guida però non conviene:

| Willy-Brandt-Straße, media di 2 semi | Fermate | Energia nei freni | Tempo | Viaggi finiti |
|---|---|---|---|---|
| Solo orari confermati (default) | 3,03 | 222 kJ | 334 s | 2.856 |
| Incerti, e confermati solo dopo 8 cicli | 3,04 | 233 kJ | 337 s | 2.844 |
| Incerti, confermati come prima | 2,98 | 226 kJ | 347 s | 2.778 |
| Solo previsioni nuove con meno osservazioni | 2,98 | 226 kJ | 343 s | 2.760 |

Chiedere 8 cicli per confermare toglie per i primi 10–12 minuti il consiglio
di lasciar scorrere l'auto verso il rosso, che è quello che risparmia energia.
Senza quella regola le fermate calano del 2%, ma l'energia nei freni sale del
2%, il tempo del 2–3% e i viaggi finiti nell'ora sono il 3–4% in meno: si
rallenta per verdi che non ci sono. Il livello incerto resta nel codice
(`ProbeLearner(levels=True, confirm_cycles=8, confirm_clean=True)`, oppure
`--learner levels` negli strumenti), ma è spento.

```bash
python tools/probe_accuracy.py --scenario willy-brandt --replan 30 --learner old    # o check, levels
```

```bash
python tools/hamburg_experiment.py predict --scenario willy-brandt --replan 30 --learner check --seed 1
```

### Traffico lento più avanti: provato e lasciato spento

Quando c'è una coda ferma davanti e nessun semaforo noto dietro, DriveNow
lascia scorrere l'auto fino alla fine della coda. Il pannello del guidatore
ora lo dice esplicitamente: "Coda ferma tra 120 m".

Si è provato ad andare oltre, con l'idea degli avvisi di rallentamento delle
app di navigazione. Si considera anche il traffico che si muove ma è almeno
15 km/h più lento di noi, e si alza il piede in tempo per raggiungerlo alla
sua velocità: dietro un'auto che continua a muoversi basta
`v ≤ v_lento + √(2·0,7·d)`. Si mira dietro alle auto che lo precedono, e non
si fa nulla se è la coda di un semaforo con previsione sicura, cioè se
finisce entro la lunghezza della coda più 50 m dalla linea, perché lì il
consiglio sul verde conta già la coda.

| Media di 2 semi | Fermate | Frenate | Energia nei freni | Tempo | Viaggi finiti |
|---|---|---|---|---|---|
| Willy-Brandt-Straße, regola di prima | 3,03 | 9,52 | 222 kJ | 334 s | 2.856 |
| Traffico lento e code ferme | 2,98 | 9,53 | 229 kJ | 350 s | 2.710 |
| Solo code ferme, anche con un semaforo noto più avanti | 2,93 | 9,34 | 219 kJ | 340 s | 2.742 |
| Traffico lento solo oltre 40 m e sopra 30 km/h | 2,97 | 9,57 | 231 kJ | 349 s | 2.687 |
| Gärtnerstraße (metà traffico), regola di prima | 0,99 | 2,86 | 102 kJ | 187 s | 606 |
| Traffico lento e code ferme | 0,99 | 2,81 | 102 kJ | 180 s | 606 |

Nel traffico fitto dell'ora di punta di Willy-Brandt-Straße rallentare in
anticipo dietro ad auto lente allarga i vuoti: passano meno auto, la coda
cresce, e i viaggi finiti nell'ora calano del 5–6%. Conta solo la regola
sulle code ferme, che toglie il 3% delle fermate, ma anche lì i viaggi finiti
sono il 4% in meno e il tempo sale del 2%. A Gärtnerstraße, con meno
traffico, il tempo di viaggio scende del 3,5% e il resto non cambia. Nel
complesso non conviene: la regola resta nel codice (`Advisor.slow_traffic`,
`--slow-traffic` nell'esperimento) ma è spenta.

### Un numero che non balla

Il consiglio si ricalcola più volte al secondo, e il numero può cambiare di
1–2 km/h da un aggiornamento all'altro: a Willy-Brandt-Straße cambia in media
86 volte per viaggio, una ogni 4 secondi. Il pannello del guidatore mostra
quindi una versione filtrata (`drivenow/display.py`):

- il numero cambia solo se si sposta di almeno 3 km/h, o se esce dalla fascia
  (troppo veloce vorrebbe dire arrivare col rosso);
- un tipo di consiglio nuovo (per esempio "rallenta" dopo "verde in arrivo")
  deve durare 2 s prima di sostituire il vecchio, tranne quando è urgente:
  rosso inevitabile, o velocità mostrata troppo alta per la nuova fascia;
- il prossimo semaforo, rotonda o precedenza si mostra subito;
- gli annunci (per una futura voce; oggi il riquadro lampeggia) solo per un
  tipo di consiglio nuovo o un nuovo incrocio, al massimo uno ogni 8 s salvo
  urgenze.

| Per viaggio | Willy-Brandt-Straße | Gärtnerstraße |
|---|---|---|
| Cambi del consiglio calcolato | 86 | 32 |
| Cambi del consiglio mostrato | 45 | 15 |
| Annunci | 12 | 4 |

Nelle simulazioni le auto DriveNow seguono il consiglio calcolato, come un
guidatore perfetto. Se seguono quello mostrato:

| Media | Fermate | Frenate | Energia nei freni | Tempo | Viaggi finiti |
|---|---|---|---|---|---|
| Willy-Brandt-Straße (2 semi), consiglio calcolato | 3,03 | 9,52 | 222 kJ | 334 s | 2.856 |
| Consiglio mostrato | 2,95 | 9,37 | 227 kJ | 337 s | 2.720 |
| Mostrato, ma le salite di velocità subito | 3,03 | 9,58 | 231 kJ | 350 s | 2.760 |
| Gärtnerstraße (1 seme, metà traffico), calcolato | 0,98 | 2,79 | 102 kJ | 183 s | 606 |
| Consiglio mostrato | 0,99 | 2,79 | 103 kJ | 185 s | 606 |

Seguire il numero filtrato non porta vantaggi misurabili: a Gärtnerstraße
non cambia nulla, a Willy-Brandt-Straße le fermate calano del 3% ma l'energia
nei freni sale del 2% e i viaggi finiti nell'ora sono il 5% in meno. La
variante che mostra subito ogni aumento di velocità va peggio. Il filtro resta
sul pannello, perché nessun guidatore vero segue un numero che cambia ogni
4 secondi, ma le simulazioni continuano a usare il consiglio calcolato
(`follow_shown`, `--follow-shown` nell'esperimento, per provare l'altro).

### Auto che rallentano in modo diverso

Il consiglio assume che, alzando il piede, ogni auto perda 0,7 m/s². Le auto
vere sono diverse: un'elettrica che recupera energia rallenta molto di più,
un'auto che va in folle molto di meno. `drivenow/profile_learner.py` fa
imparare a ogni auto il proprio valore: una volta al secondo, nei secondi in
cui il guidatore sta alzando il piede per seguire il consiglio, confronta la
velocità con quella del secondo prima (con l'errore di ±0,2 m/s di un
telefono) e tiene la mediana, dopo almeno 8 secondi buoni.

Per provarlo, `--vehicle-mix` dà alle auto DriveNow tre comportamenti
plausibili (non misurati): il 25% veleggia (0,35 m/s² a piede alzato, 1,2 in
accelerazione), il 50% è un'auto termica normale (0,7 e 1,4), il 25% è
un'elettrica con recupero (1,3 e 2,0). Frenate ed energia nei freni si
contano oltre la decelerazione a piede alzato di ciascuna auto: il recupero
di un'elettrica non è una frenata.

| Media di 2 semi | Fermate | Frenate | Energia nei freni | Tempo | Viaggi finiti |
|---|---|---|---|---|---|
| Willy-Brandt-Straße, auto tutte uguali | 3,03 | 9,52 | 222 kJ | 334 s | 2.856 |
| Auto diverse, il consiglio usa 0,7 per tutte | 3,01 | 9,69 | 227 kJ | 352 s | 2.700 |
| Auto diverse, valore imparato | 2,94 | 9,52 | 227 kJ | 347 s | 2.623 |
| Auto diverse, valore vero | 3,07 | 9,59 | 226 kJ | 359 s | 2.680 |
| Gärtnerstraße (metà traffico), auto tutte uguali | 0,99 | 2,86 | 102 kJ | 187 s | 606 |
| Auto diverse, 0,7 per tutte | 1,00 | 2,88 | 102 kJ | 185 s | 606 |
| Auto diverse, valore imparato | 1,00 | 2,87 | 103 kJ | 184 s | 606 |
| Auto diverse, valore vero | 1,00 | 2,92 | 103 kJ | 187 s | 608 |

L'apprendimento funziona: il valore imparato sbaglia in media di 0,07–0,09
m/s². Ma serve tempo: a Willy-Brandt-Straße metà delle auto lo impara entro la
fine del viaggio, a Gärtnerstraße, dove i viaggi sono brevi, poco più di una
su cinque. Soprattutto, conoscere il valore giusto non cambia i risultati:
nemmeno quello vero fa meglio di 0,7 per tutte. Il consiglio punta ad
arrivare 1,5 s dopo l'inizio del verde dentro una fascia larga, e il tratto
in cui l'auto cambia velocità è breve, quindi sbagliare la decelerazione di
qualche decimo sposta l'arrivo di poco. A Willy-Brandt-Straße tempo e viaggi
finiti peggiorano con le auto diverse in tutte e tre le varianti, ma la
differenza è dentro la variabilità che questo scenario mostra a ogni
cambiamento.

Anche l'accelerazione si potrebbe imparare allo stesso modo, ma nel traffico
di città un'auto raramente ha spazio per accelerare quanto può: le
elettriche, che accelerano a 2,0 m/s², venivano misurate tra 0,3 (mediana) e
0,9 (80° percentile). Per questo si impara solo il valore a piede alzato. Il
default resta 0,7 per tutte (`--profiles fixed`); `--profiles learned` e
`--profiles true` provano le altre due.

### Senza sapere dove gira l'auto

In simulazione ogni auto DriveNow conosce il suo percorso, quindi sa se al
prossimo semaforo andrà dritta o girerà. Conta: a Willy-Brandt-Straße 19
accessi su 48 con dati hanno semafori diversi a seconda della direzione, a
Gärtnerstraße 15 su 27. Su strada, senza una destinazione impostata, la svolta
non si sa. `Advisor.turns` prova due modi di farne a meno:

- `straight`: oltre il tratto su cui si trova, l'auto va dritta;
- `common`: al primo semaforo davanti vale solo il verde comune a tutte le
  direzioni, finché l'auto non ha imboccato la sua.

In entrambi, a 50 m dalla linea la corsia in cui si trova l'auto rivela la
svolta (`commit_distance`, `--commit`).

| Media di 2 semi | Fermate | Frenate | Energia nei freni | Tempo | Viaggi finiti |
|---|---|---|---|---|---|
| Willy-Brandt-Straße, svolta nota | 3,03 | 9,52 | 222 kJ | 334 s | 2.856 |
| Dritto, corsia nota a 50 m | 2,98 | 9,59 | 231 kJ | 356 s | 2.801 |
| Dritto, svolta mai nota | 2,90 | 9,39 | 229 kJ | 338 s | 2.664 |
| Gärtnerstraße (metà traffico), svolta nota | 0,99 | 2,86 | 102 kJ | 187 s | 606 |
| Dritto, corsia nota a 50 m | 0,99 | 2,82 | 101 kJ | 180 s | 606 |
| Dritto, svolta mai nota | 0,99 | 2,76 | 99 kJ | 177 s | 606 |

Non sapere la svolta costa poco: a Willy-Brandt-Straße il 3–4% di energia nei
freni in più, a Gärtnerstraße niente (lì tempo ed energia scendono un po',
probabilmente perché chi gira segue il verde dell'asse principale e rallenta
meno). Il verde comune non cambia nulla rispetto al dritto: contando su 10
minuti di entrambi gli scenari non ha mai cambiato la previsione usata. Dove
le direzioni hanno semafori diversi, la previsione dà quasi sempre lo stesso
verde a tutte, e dove non lo fa il tratto è corto (la rete di Amburgo spezza
la strada dove le corsie si dividono, spesso a meno di 50 m dalla linea) e la
corsia ha già rivelato la svolta. In simulazione resta la svolta nota; su
strada senza destinazione basta `straight`.

### Gärtnerstraße: un corridoio coperto

Qui 9 degli 11 impianti semaforici della zona hanno dati reali, e così il
53% dei link semaforici di SUMO (gli altri sono soprattutto corsie di svolta
e strade laterali senza dati). La rete comprende solo una fascia di 80 m
attorno al corridoio, quindi le strade laterali sono brevi.

La previsione, misurata sui segnali usati dalla simulazione:

| Fra | 5 s | 15 s | 30 s | 60 s | 90 s |
|---|---|---|---|---|---|
| Stato corretto | 96,8% | 96,5% | 96,3% | 96,0% | 95,9% |
| Previsto verde, era rosso | 1,5% | 1,7% | 1,8% | 2,0% | 2,0% |
| Verde reale non previsto | 1,7% | 1,8% | 1,9% | 1,9% | 2,2% |

Metà del traffico stimato (a pieno traffico la rete ritagliata si
intasa), un'ora, 0% contro 100% di auto DriveNow. "Asse" sono i viaggi che
percorrono il corridoio per almeno il 60% della strada (circa 360 viaggi);
"tutti" sono tutti i viaggi (circa 610):

| Viaggi | Consiglio | Fermate | Frenate | Energia nei freni | Tempo |
|---|---|---|---|---|---|
| Asse | nessuno | 0,98 | 2,71 | 136 kJ | 160 s |
| | previsione | 0,94 | 2,48 | 100 kJ | 169 s |
| | oracolo | 0,91 | 2,46 | 101 kJ | 164 s |
| Tutti | nessuno | 1,06 | 3,15 | 159 kJ | 189 s |
| | previsione | 1,02 | 2,86 | 118 kJ | 178 s |
| | oracolo | 1,02 | 2,83 | 117 kJ | 180 s |

Con la copertura quasi completa l'energia buttata nei freni cala di un
quarto (−26%), le frenate dell'8–9% e le fermate del 4–7%. Sull'asse la
previsione costa 9 s a viaggio (+5,5%) contro i 3,5 s dell'oracolo: sono i
verdi che il modello non dà per certi, per cui l'auto rallenta per niente.
Sull'insieme dei viaggi il tempo invece cala, perché si formano meno code.

È una sola simulazione per caso, con un solo seme casuale: le differenze
piccole (le fermate, il tempo) vanno prese come indicazioni, non come
misure precise.

## Auto che guidano da sole: telecamere, radar, lidar

Fin qui il consiglio era per un guidatore, e l'auto davanti, la coda e il
colore del semaforo venivano dalla simulazione (su strada: dalle auto
connesse e dai tempi pubblicati dei semafori). Con `--autopilot` le auto
DriveNow guidano da sole e vedono la strada con i **propri sensori**, come
una Tesla. A differenza di Tesla, che usa solo telecamere, DriveNow può
aggiungere radar, lidar e i tempi dei semafori trasmessi dalla strada (V2I).

```bash
python -m drivenow.server --autopilot                                  # telecamera + radar, sereno
python -m drivenow.server --autopilot --sensors camera --weather fog   # solo telecamera, nebbia
python -m drivenow.server --autopilot --double-parking 30              # auto in doppia fila
```

Seguendo un'auto che guida da sola, il pannello dice cosa vede ("auto a 22 m
(telecamera + radar) · semaforo rosso"), e la mappa disegna, tratteggiato,
l'oggetto dove lo mettono i sensori.

### I sensori (`drivenow/perception.py`)

Le strade del simulatore hanno una corsia, quindi la scena è lungo il
percorso: la prima auto davanti (i sensori non vedono attraverso di lei), il
prossimo semaforo, e gli oggetti che un radar scambia per ostacoli. La
telecamera non è simulata a pixel: è simulato quello che esce da un
riconoscitore di immagini (una rete neurale che trova le auto e legge i
semafori), cioè se trova l'oggetto, a che distanza lo mette e quanto spesso
sbaglia. Un riconoscitore vero si collega allo stesso punto.

| Sensore | Portata (sereno) | Errore sulla distanza | Cosa non sa fare |
|---|---|---|---|
| Telecamera | 150 m (auto), 120 m (semafori) | cresce con la distanza: ~2,5 m a 50 m, ~7 m a 100 m | misura male distanza e velocità; notte, pioggia e soprattutto nebbia la accorciano |
| Radar | 160 m | 0,3 m, velocità 0,15 m/s | non distingue un'auto da un tombino o da un cartello: ogni tanto vede un ostacolo fermo che non c'è ("fantasma", 2 per km); non legge i colori |
| Lidar | 120 m | pochi centimetri | non legge i colori; pioggia e nebbia lo accorciano molto |

| Meteo | Telecamera (portata) | Semafori | Radar | Lidar |
|---|---|---|---|---|
| Notte | 60% | 100% (sono luci) | 100% | 100% |
| Pioggia | 70% | 80% | 90% | 60% |
| Nebbia | 30% | 40% | 95% | 35% |

Questi numeri sono plausibili ma non misurati su sensori veri: si cambiano in
cima a `perception.py`.

**Fusione.** Ogni oggetto ha un filtro di Kalman su distanza e velocità di
avvicinamento; ogni rilevazione aggiorna l'oggetto più vicino per distanza
*e* velocità, oppure ne crea uno nuovo, che si usa dopo due rilevazioni. Una
regola viene dalle auto vere: un oggetto **fermo** che vede solo il radar si
ignora, a meno che telecamera o lidar non l'abbiano visto due volte
nell'ultimo secondo o che sia stato visto muoversi (un'auto che si è
fermata). Così spariscono i fantasmi del radar, ma è anche il motivo per cui
un radar da solo non trova un'auto già ferma quando entra nel suo campo: con
il solo radar le auto non partono nemmeno, perché non possono fidarsi di
nessun ostacolo fermo. Il colore del semaforo cambia solo quando due delle
ultime tre letture sono d'accordo.

### Come guida (`drivenow/autopilot.py`)

Solo i pedali: con una corsia sola non c'è niente da sterzare. A ogni passo
l'auto prende la più bassa di queste accelerazioni:

- **l'auto davanti**, come la vedono i sensori, con 1,5 s di distanza
  (un guidatore del simulatore ne tiene 1,2). Usa la distanza misurata meno
  due volte la sua incertezza: un'auto vista male si tiene più lontana;
- **la linea di arresto**, se deve fermarsi: rosso o giallo letti dalla
  telecamera o dati dai tempi del semaforo (basta uno dei due). Se i tempi
  dicono che arrivando sarà verde, continua a veleggiare come un guidatore
  DriveNow;
- **il consiglio DriveNow**, rallentando solo alzando il piede;
- **quello che non vede ancora**: mai più veloce di quanto serve per fermarsi
  comodamente (2 m/s²) entro la distanza a cui vedrebbe un'auto ferma. Con
  la nebbia sono circa 36 m, quindi 42 km/h. Senza tempi del semaforo,
  finché non lo vede verde deve poter fermarsi alla linea;
- **frenata d'emergenza** (6 m/s²) se l'urto arriverebbe entro 1,5 s,
  contando la velocità di avvicinamento più bassa compatibile con la misura,
  perché una stima rumorosa non deve inchiodare l'auto.

Precedenze e rotonde usano la stessa regola dei guidatori del simulatore:
il traffico che incrocia è visto senza errori.

### Risultati

`tools/perception_experiment.py`: 30 minuti per caso, tutte le auto DriveNow
e a guida autonoma, 30 auto all'ora che si fermano in doppia fila per 15–40 s
(ostacoli fermi mai visti muoversi). Città demo, circa 1.000 km guidati per
caso. Valori medi per viaggio; "auto non vista" è la quota di istanti in cui
c'era davvero un'auto entro 40 m e i sensori non la davano.

| Meteo | Sensori | Frenate | Energia nei freni | Tempo | Errore sulla distanza | Auto non vista | Frenate fantasma |
|---|---|---|---|---|---|---|---|
| Sereno | perfetti (riferimento) | 1,46 | 22,2 kJ | 112 s | 0 | 0 | 0 |
| | telecamera | 2,27 | 23,1 kJ | 111 s | 0,62 m | 1,9% | 0 |
| | telecamera + radar | 1,59 | 22,0 kJ | 110 s | 0,31 m | 1,2% | 5 |
| | + lidar | 1,66 | 22,2 kJ | 111 s | 0,31 m | 1,0% | 1 |
| Notte | telecamera | 2,72 | 25,8 kJ | 112 s | 0,94 m | 1,7% | 1 |
| | telecamera + radar | 1,73 | 23,0 kJ | 112 s | 0,35 m | 1,8% | 7 |
| | + lidar | 1,83 | 24,1 kJ | 113 s | 0,37 m | 1,2% | 8 |
| Pioggia | telecamera | 2,53 | 24,0 kJ | 111 s | 0,81 m | 2,2% | 1 |
| | telecamera + radar | 1,73 | 22,7 kJ | 112 s | 0,32 m | 1,6% | 3 |
| | + lidar | 1,77 | 23,6 kJ | 112 s | 0,33 m | 1,5% | 8 |
| Nebbia | telecamera | 3,70 | 29,3 kJ | 125 s | 1,32 m | 2,2% | 1 |
| | telecamera + radar | 1,89 | 22,3 kJ | 121 s | 0,35 m | 1,1% | 5 |
| | + lidar | 1,94 | 22,5 kJ | 121 s | 0,42 m | 1,3% | 8 |

Le frenate fantasma sono il totale dei casi (frenare per un oggetto che non
c'è, senza un'auto vera vicina), su circa 1.000 km.

In nessun caso, né qui né nella griglia 3×3 (circa 1.340 km per caso), ci
sono stati tamponamenti o semafori passati col rosso; le situazioni con
meno di 1,5 s all'urto sono state al massimo una per caso. Cosa si vede:

- **La sola telecamera basta per non urtare, ma guida peggio.** Misura la
  distanza con un errore doppio o triplo, quindi l'auto corregge di più:
  +55% di frenate col sereno, +150% con la nebbia, rispetto a sensori
  perfetti. Con il radar le frenate tornano quasi quelle di riferimento
  (+9%), anche con la nebbia.
- **Il lidar in città aggiunge poco.** Il radar dà già la distanza al
  decimetro e il lidar vede un po' meglio solo vicino. Serve dove questo
  modello non arriva: pedoni, ciclisti, forme.
- **La nebbia costa tempo a tutti** (+8–11%): nessun sensore rende sicuro
  andare più veloci di quanto lascia vedere la telecamera, perché solo lei e
  il lidar confermano un ostacolo fermo.
- **Il prezzo del radar sono i fantasmi**: da 1 a 8 frenate inutili ogni
  1.000 km nonostante il filtro sugli oggetti fermi.

Nella griglia 3×3 il quadro è lo stesso: energia nei freni 4,3 kJ con
sensori perfetti, 6,1 con la sola telecamera, 4,8 con telecamera e radar
(sereno); 10,2 e 5,8 con la nebbia.

**I tempi dei semafori non si vedono con una telecamera.** Una telecamera
legge il colore di adesso, non quando cambierà. Togliendo i tempi
(`--no-light-timing`) l'auto vede il rosso e si ferma come una persona, e il
risparmio di DriveNow sparisce:

| Città demo | Fermate | Frenate | Energia nei freni | Tempo |
|---|---|---|---|---|
| Nessun DriveNow, guidano persone | 1,28 | 2,41 | 94,0 kJ | 106 s |
| Telecamera + radar, con i tempi dei semafori | 0,52 | 1,59 | 22,0 kJ | 110 s |
| Telecamera + radar, senza tempi | 1,35 | 2,79 | 63,9 kJ | 111 s |
| Sola telecamera, senza tempi | 1,34 | 5,10 | 66,2 kJ | 112 s |

Senza i tempi resta un po' di risparmio (64 kJ contro 94) perché l'auto
autonoma, vedendo il rosso da lontano, alza il piede prima di una persona.
Ma i tempi dei semafori valgono più di qualsiasi sensore: è la risorsa che
DriveNow aggiunge a quello che l'auto vede da sola.

**Limiti.** Una corsia, quindi niente sterzo, sorpassi, cambi di corsia,
pedoni o ciclisti; il traffico che incrocia alle precedenze è visto senza
errori; le code e le auto lontane, usate dal consiglio, vengono ancora dalle
auto connesse e non dai sensori. Il simulatore lascia entrare le auto in un
incrocio senza guardare lo spazio che lasciano: un'auto che si immette a
meno di 10 m davanti non è contata come tamponamento di chi segue, per
nessun gruppo. I parametri dei sensori sono stime, non misure; un solo seme
per caso.

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
  davanti. Un'auto con sensori propri vede da sola il veicolo davanti e il
  colore del semaforo: al posto del modello di `perception.py` vanno le
  uscite del riconoscitore d'immagini e del radar dell'auto.
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
  probe.py        orari dei semafori senza dati, imparati dalle auto e ricontrollati
  display.py      quello che vede il guidatore: numero stabile, annunci distanziati
  profile_learner.py  quanto rallenta ogni auto a piede alzato, imparato dalla sua guida
  positioning.py  la posizione come la sa un telefono (rumore, ritardo, buchi) e il filtro di Kalman
  perception.py   sensori dell'auto (telecamera, radar, lidar, meteo) e loro fusione
  autopilot.py    guida autonoma sui pedali, da quello che vedono i sensori
  hamburg/        dati reali di Amburgo: storico e previsione dei semafori, mondo SUMO
  server.py       server della mappa (HTTP + Server-Sent Events, solo libreria standard)
web/              mappa: index.html, style.css, app.js
data/sumo/        reti a griglia 1×1–4×4 (dalla vecchia Traffc_light_control)
data/hamburg/     scenario reale di Amburgo (rete, semafori registrati, traffico)
tools/            costruzione dello scenario di Amburgo, esperimenti (anche sensori e meteo:
                  perception_experiment.py), accuratezza delle previsioni imparate dalle
                  auto, registrazione delle pagine
tests/            pytest (i test SUMO si saltano se SUMO non è installato)
```

Test:

```bash
pip install pytest
python -m pytest
```
