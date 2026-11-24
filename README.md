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

Perché conviene, con i conti (accelerare o frenare, frizione o marcia):
[consumi](docs/consumi.md).

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

### Semafori comandati dall'agente PPO

Con `tools/ppo_bench.py` i semafori della griglia 2×2 li comanda davvero l'agente PPO del
repository da cui viene Traffc_light_control (addestrato con `tools/ppo_train.py`, pesi fuori
dalla repo), e il consiglio riceve solo le finestre a cui l'agente è impegnato
(`drivenow/committed.py`: verde minimo, prossima decisione, giallo, verde massimo).
Sugli stessi veicoli, tre semi: nessun verde promesso falso; con il piano noto il consiglio
toglie il 90 % delle fermate, con l'agente le fermate non calano ma l'energia nei freni sì
(12-31 %); usare solo le finestre certe con un agente che ha un verde minimo costa il 9 % di
tempo, certe + probabili no. Dettagli, comandi e limiti in
[docs/ppo-semafori.md](docs/ppo-semafori.md).

### Repository integrate (`third_party/`)

Tre repository del Piano sono dentro DriveNow come sottomoduli git, fissati a un commit:

| Cartella | Repository | Licenza | Usato da |
|---|---|---|---|
| `third_party/ppo-traffic-light` | [MagMueller/Multi-Agent-Distributed-PPO-Traffc-light-control](https://github.com/MagMueller/Multi-Agent-Distributed-PPO-Traffc-light-control) | nessuna dichiarata: solo collegato, non copiato | `tools/ppo_train.py`, `tools/ppo_bench.py` (pesi in `data/ppo/`) |
| `third_party/flameox` | [morluto/flameox](https://github.com/morluto/flameox) | MIT | profilazione, `tools/sim_profile.py` |
| `third_party/rea` | [morluto/REA](https://github.com/morluto/REA) | MIT | schede delle app dall'APK, `tools/app_scan.py` |

```bash
git submodule update --init --depth 1          # scarica le tre repo
python tools/devtools.py setup ppo flameox rea # ambienti e strumenti in .tools/
python tools/devtools.py run ppo               # confronto PPO (docs/ppo-semafori.md)
python tools/devtools.py run flameox           # profilo del simulatore (docs/operational.md)
```

Il server (`python -m drivenow.server`) non le richiede.

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
| `--pedestrians N` | 0 | N pedoni all'ora per strisce (a metà delle strade più lunghe di 150 m) |

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
| Città demo (simulatore interno, 3 semi, 30 min) | 1,33 → 0,59 | 2,70 → 1,50 | 99 → 25 kJ | 107 → 112 s (+4%) |
| Griglia 2×2 della repo base (SUMO, 30 min) | 1,35 → 0,16 | 2,60 → 0,73 | 146 → 20 kJ | 92 → 95 s (+3%) |
| Griglia 3×3 della repo base (SUMO, 30 min) | 2,23 → 0,23 | 4,59 → 1,11 | 230 → 28 kJ | 133 → 136 s (+2%) |

Città demo: semi 1–3, 220 auto/ora per ingresso, nessun riscaldamento
(contano i viaggi finiti dall'inizio), circa 1.180 viaggi finiti per seme. Il
simulatore interno fa entrare a turno le auto che girano nella stessa strada
(prima le lasciava sovrapporsi): rispetto alla misura precedente le fermate
DriveNow salgono da 0,52 a 0,59 e l'energia nei freni da 23 a 25 kJ.

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
  il volume è un'ipotesi, scritta in `scenario.json`. Quell'ipotesi è bassa: sull'asse
  principale è circa 6,6 volte (Willy-Brandt-Straße) e 7 volte (Gärtnerstraße) sotto i volumi
  ufficiali 2019 (DTV × 9% ÷ 2 per senso). C'è perciò anche una variante tarata, vedi
  "Altri dati aperti di Amburgo" più sotto.

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
varchi tolgono l'8% dell'energia nei freni (27,0 → 24,8 kJ, semi 1–3,
30 min) con lo 0,4% di tempo in meno.

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

### Con il GPS di un telefono

In simulazione ogni auto sa esattamente dove si trova. Un telefono no:
`positioning.Phone` trasforma la posizione vera in quello che riporterebbe
un telefono qualunque:

- **Errore lungo la strada:** circa ±5 m per la posizione e ±0,5 m/s per la velocità.
- **Frequenza e ritardo:** una lettura al secondo, che arriva con 1 s di ritardo.
- **Buchi di segnale:** in media uno ogni 5 minuti, lunghi da 5 a 20 s
  (sottopassi, palazzi alti).

Si assume che l'auto sia sulla sua strada (map matching), quindi l'incertezza
riguarda solo quanto è avanti lungo il percorso. Il consiglio può usare questi
dati in tre modi (`--gps`):

- `raw`: l'ultima lettura così com'è, vecchia di 1–2 s.
- `filtered`: un filtro di Kalman su posizione e velocità lungo la strada.
  Media il rumore, porta la stima a "adesso" oltre il ritardo e durante un
  buco continua a stimare, con un'incertezza che cresce.
- `filtered` con sospensione: quando l'incertezza supera 15 m
  (`--gps-max-sigma`) il consiglio si ferma e l'auto guida come senza
  DriveNow.

| Media di 2 semi | Fermate | Frenate | Energia nei freni | Tempo | Viaggi finiti |
|---|---|---|---|---|---|
| Willy-Brandt-Straße, posizione esatta | 3,03 | 9,52 | 222 kJ | 334 s | 2.857 |
| GPS grezzo | 3,23 | 9,38 | 232 kJ | 372 s | 2.676 |
| GPS filtrato | 3,20 | 9,58 | 226 kJ | 355 s | 2.858 |
| Filtrato, sospeso oltre 15 m | 3,17 | 9,51 | 228 kJ | 353 s | 2.777 |
| Gärtnerstraße (metà traffico), posizione esatta | 0,99 | 2,86 | 102 kJ | 187 s | 606 |
| GPS grezzo | 1,02 | 2,34 | 77 kJ | 190 s | 604 |
| GPS filtrato | 1,00 | 2,75 | 94 kJ | 178 s | 607 |
| Filtrato, sospeso oltre 15 m | 1,00 | 2,77 | 97 kJ | 185 s | 607 |

L'errore della posizione usata dal consiglio, misurato a ogni aggiornamento:

| Modo | Errore mediano | 90° percentile | Errore medio |
|---|---|---|---|
| Grezzo | 4,1–4,4 m | 12–14 m | 2,5–3,6 m indietro |
| Filtrato | 1,9–2,0 m | 4,0 m | 1,5–1,8 m avanti |

- **Grezzo:** usare le letture così come sono costa caro a Willy-Brandt-Straße:
  - tempo di viaggio +11%;
  - energia nei freni +5%;
  - 6% di viaggi finiti in meno.

  A Gärtnerstraße invece l'energia nei freni scende, il motivo non l'ho
  verificato.
- **Filtrato:** il filtro rimette a posto quasi tutto:
  - **Willy-Brandt-Straße:** energia +2% e stessi viaggi finiti, ma restano
    circa +6% sia di tempo sia di fermate. È il costo che resta da capire,
    probabilmente il piccolo anticipo della stima quando l'auto rallenta.
  - **Gärtnerstraße:** il filtrato fa perfino un po' meglio della posizione
    esatta. È una differenza dentro la variabilità che il consiglio ha già,
    quindi non un vantaggio.
- **Sospensione:** non aggiunge niente. Si ferma nel 3% degli aggiornamenti,
  cioè durante i buchi, e lì la stima del filtro bastava già. Resta come rete
  di sicurezza per buchi più lunghi di quelli simulati.

Su strada va quindi usata la posizione filtrata, mai l'ultima lettura grezza.

Un dettaglio della simulazione: la rete SUMO non conta la lunghezza degli
incroci, quindi al telefono passo la distanza davvero percorsa, incroci
compresi. Prima che lo correggessi, mentre un'auto attraversava un incrocio
il telefono vedeva una posizione ferma e una velocità non nulla, e il filtro
sembrava sbagliare molto di più: 90° percentile di 16 m invece di 4.

Restano esatti, in questa prova, la posizione delle altre auto (code, veicolo
davanti) e i passaggi da cui si imparano i semafori senza dati: qui il
telefono simulato riguarda solo la posizione dell'auto che riceve il
consiglio.

### Dove sono le altre auto

La consulenza guarda le auto intorno in tre momenti:
- **la coda davanti:** quante auto sono ferme prima della linea;
- **chi segue da vicino:** con un'auto a ridosso non si rallenta presto;
- **i varchi sulla strada principale:** a una precedenza.

Finora la simulazione le conosceva tutte, anche quelle senza DriveNow. Su strada
non è così.

**Che cosa si può sapere davvero.** Nessun fornitore di dati dà le singole auto
in movimento: sono dati personali.
- **TomTom Traffic Flow:** per un punto dà la velocità attuale e quella libera del
  tratto di strada, con alcuni minuti di ritardo.
- **Waze for Cities:** dà le code (linea, velocità, lunghezza, livello), ma solo
  agli enti pubblici.
- **Le auto DriveNow:** sono le uniche che si possono conoscere una per una, e
  solo perché il loro telefono lo dice.

Il "database delle auto in movimento" (`drivenow/fleet.py`, `FleetDB`) ha quindi
due strati:
- **Le auto DriveNow una per una.** Ogni telefono manda la sua posizione una
  volta al secondo, con un nome di comodo, e dopo 3 s senza notizie l'auto viene
  dimenticata. Un'auto DriveNow ferma in coda rivela anche le auto che non si
  vedono: fino alla linea (o fino alla prima auto vista che riparte) la strada è
  ferma, quindi quel tratto si riempie di auto ferme ogni 7,5 m. Con un percorso
  file, ogni posizione finisce anche in un archivio SQLite per analisi e repliche.
- **Il traffico aggregato per tratto.** Se un tratto scorre sotto metà della sua
  velocità libera, l'arrivo alla linea non può essere più rapido di quella
  velocità.

In più c'è una regola di sicurezza. Un varco sulla strada principale in cui non
si vede nessuno non è un varco libero se le auto senza DriveNow non si vedono,
come un semaforo sconosciuto non è un verde. Con meno del 90% di auto DriveNow
la consulenza non rallenta più per prendere un varco: dà la solita precedenza.

Per la strada vera:
- `TomTomFlow` (`drivenow/traffic_sources.py`) interroga Flow Segment Data per
  il punto medio di ogni tratto. Distribuisce le richieste in base al budget
  della quota e una risposta aggiorna tutti i tratti lungo il segmento restituito.
- `WazeJams` legge le code del feed partner.
- `POST /api/report` del server riceve la posizione di un telefono.
- `tools/edge_points.py` calcola lon/lat e direzione di ogni tratto della rete,
  già salvati in `data/hamburg/*/edge_points.json`.

Gli adattatori sono provati solo su risposte scritte da me secondo i formati
pubblicati: una prova dal vivo richiede la chiave TomTom e l'accesso a
`api.tomtom.com`, che dall'ambiente di sviluppo è bloccato.

**Come l'ho misurato.** In simulazione `--occupancy` sceglie che cosa vede la
consulenza:
- `truth`: tutte le auto, come finora;
- `fleet`: solo le auto DriveNow;
- `fleet+flow`: le auto DriveNow più la velocità media di ogni tratto.

In `fleet+flow` la velocità è calcolata sulle auto presenti, mediata su 60 s e
consegnata con 60–120 s di ritardo: è un'ipotesi su com'è un dato tipo TomTom,
non il dato TomTom. Risultati per le sole auto DriveNow, media di 2 semi, 60 min:

| | Fermate | Frenate | Energia nei freni | Tempo | Viaggi finiti |
|---|---|---|---|---|---|
| Willy-Brandt-Straße, 25% DriveNow, tutte le auto | 3,16 | 9,77 | 245 kJ | 334 s | 739 |
| Solo le auto DriveNow | 3,33 | 10,48 | 269 kJ | 343 s | 719 |
| Più il traffico aggregato | 3,25 | 10,29 | 264 kJ | 340 s | 726 |
| Willy-Brandt-Straße, 50% DriveNow, tutte le auto | 3,04 | 9,64 | 234 kJ | 349 s | 1.348 |
| Solo le auto DriveNow | 3,10 | 10,08 | 249 kJ | 336 s | 1.474 |
| Più il traffico aggregato | 3,09 | 9,75 | 239 kJ | 338 s | 1.422 |
| Gärtnerstraße (metà traffico), 25% DriveNow, tutte le auto | 1,02 | 2,81 | 110 kJ | 186 s | 148 |
| Solo le auto DriveNow | 1,01 | 2,87 | 115 kJ | 187 s | 148 |
| Più il traffico aggregato | 1,07 | 2,82 | 110 kJ | 198 s | 148 |
| Gärtnerstraße (metà traffico), 50% DriveNow, tutte le auto | 0,95 | 2,73 | 102 kJ | 175 s | 293 |
| Solo le auto DriveNow | 0,97 | 2,77 | 106 kJ | 176 s | 293 |
| Più il traffico aggregato | 0,98 | 2,72 | 101 kJ | 183 s | 292 |

- **Vedere solo le auto DriveNow costa.** L'energia nei freni sale del 3–10%: di
  più con meno auto DriveNow e sulla strada più trafficata (Willy-Brandt-Straße
  al 25%: +10%, con il 7% di frenate in più). È il prezzo, finora nascosto, del
  passaggio dalla simulazione alla strada.
- **Il traffico aggregato ne recupera gran parte.** A Willy-Brandt-Straße al 50%
  si torna a +2%, a Gärtnerstraße allo stesso livello di quando si vedevano
  tutte le auto. Al 25% su Willy-Brandt-Straße recupera solo un quinto.
- **Ma a Gärtnerstraße costa tempo:** +5–6%, in entrambi i semi. La causa più
  probabile è che la velocità media di un tratto davanti a un semaforo è bassa
  anche solo per il rosso, e la consulenza la legge come traffico lento,
  rimandando l'arrivo. Il prossimo passo è usarla solo dove il tratto lento non
  si spiega con un semaforo noto.
- **Il tempo a Willy-Brandt-Straße non si confronta bene tra le righe.** Lì il
  numero di viaggi finiti cambia molto da una prova all'altra (al 50%: 1.348
  contro 1.474), quindi la congestione non è la stessa.
- **Le altre auto, senza DriveNow, non cambiano in modo apprezzabile.**

Non ho separato quanto pesa la regola sui varchi rispetto alle code non viste:
entrambe sono attive in `fleet` e `fleet+flow`. In simulazione il default resta
`truth`, per confrontare con i risultati precedenti; i numeri da aspettarsi su
strada sono quelli di `fleet+flow`.

### Auto stimate da tre fonti: telefoni, spire, velocità per tratto

Nessuno ha tutte le auto una per una, ma tre fonti insieme danno una buona stima
di quante sono ferme a ogni semaforo:
- **i telefoni DriveNow:** le nostre auto una per una (`fleet.py`);
- **le spire ai semafori di Amburgo:** per alcune corsie la città pubblica in
  diretta se la spira davanti alla linea è occupata. Ogni passaggio da libera a
  occupata è un'auto;
- **la velocità per tratto tipo TomTom:** emulata in simulazione, come nella
  sezione precedente.

**Lo stimatore delle code** (`drivenow/estimator.py`) parte sempre dal colore del
semaforo; le spire danno i due numeri che il colore lascia aperti.
- **Col rosso:** ogni auto che arriva si mette in coda. La coda comincia quando
  la prima auto si ferma sulla spira davanti alla linea, e poi cresce al ritmo
  degli arrivi, cioè i passaggi degli ultimi 5 minuti, congelati quando scatta il
  rosso, perché col rosso nessuno passa. Se col rosso la spira è libera, la coda
  non c'è. Quello che restava alla fine del verde si porta nel rosso.
- **Col verde:** la coda riparte, e ogni passaggio sulla spira è un'auto che
  esce. Finisce quando il conto arriva a zero o quando sulla spira non passa
  nessuno per 3 s.
- **Il giallo conta come rosso**, come nella consulenza.
- **Una corsia ha il verde se ce l'ha una qualsiasi delle direzioni che partono
  da lì** (dritto, destra…). Una prima versione guardava una sola direzione, e
  alcune corsie risultavano rosse per minuti mentre le auto passavano.

Solo dove il colore non è noto le spire vengono usate da sole:
- un'auto ferma sulla spira per più di 3 s è la testa di una coda, che cresce al
  ritmo degli arrivi;
- quando la spira si libera, la coda si svuota un passaggio alla volta.

In simulazione i colori vengono dalla registrazione che comanda i semafori di
SUMO; dal vivo dal flusso della città.

La coda stimata si somma a quella che mostrano i telefoni, dalla linea
all'indietro, anche sui tratti precedenti. La rete di Amburgo spezza gli accessi
dove le corsie si dividono, e molte spire stanno su tratti di 8 m. Su questi
accessi la velocità per tratto non si usa più: la coda la contano già le spire,
e la velocità media bassa per il rosso non viene più scambiata per traffico lento.

**Dove stanno le spire.** `drivenow/hamburg/detectors.py` mette ogni spira sulla
corsia SUMO che sorveglia: lo ricava da `links.json` e dalle connessioni della
rete. Abbinate a una corsia SUMO ne restano:
- 15 corsie su 12 accessi a Willy-Brandt-Straße;
- 11 corsie su 6 accessi a Gärtnerstraße.

Stanno quasi tutte su strade laterali: l'asse principale di Willy-Brandt-Straße
non ne ha. La distanza dalla linea non è nei dati: l'ho messa a 2 m
(`--det-offset`).

Nell'ora simulata le spire emulate contano un totale diverso da quello della
registrazione:

| Scenario | Spire emulate | Registrazione |
|---|---|---|
| Willy-Brandt-Straße | 945–985 auto | 1.118 |
| Gärtnerstraße (metà traffico) | 200–213 auto | 123 |

A Gärtnerstraße alcune spire vere contano poco o niente.

**Risultati** per le sole auto DriveNow, media di 2 semi, 60 min, `--occupancy fused`, confrontati con la sezione precedente. La colonna "Spire senza semaforo" è la prima versione dello stimatore:

| | Tutte le auto | Solo DriveNow | Più velocità per tratto | Spire senza semaforo | Spire con semaforo |
|---|---|---|---|---|---|
| Willy-Brandt-Straße 25%: energia nei freni | 245 kJ | 269 kJ | 264 kJ | 258 kJ | 265 kJ |
| tempo | 334 s | 343 s | 340 s | 335 s | 344 s |
| Willy-Brandt-Straße 50%: energia nei freni | 234 kJ | 249 kJ | 239 kJ | 239 kJ | 238 kJ |
| tempo | 349 s | 336 s | 338 s | 347 s | 333 s |
| Gärtnerstraße 25%: energia nei freni | 110 kJ | 115 kJ | 110 kJ | 110 kJ | 109 kJ |
| tempo | 186 s | 187 s | 198 s | 181 s | 175 s |
| Gärtnerstraße 50%: energia nei freni | 102 kJ | 106 kJ | 101 kJ | 100 kJ | 100 kJ |
| tempo | 175 s | 176 s | 183 s | 178 s | 172 s |

**Errore sulle code.** Ogni 5 s, per ogni accesso con spira, confronto le auto
ferme vere con quelle stimate. Errore medio assoluto, media dei due semi; tra
parentesi lo sbilanciamento medio:

| Accessi con spira | Auto ferme in media | Solo DriveNow | Spire senza semaforo | Spire con semaforo |
|---|---|---|---|---|
| Willy-Brandt-Straße 25% | 2,3–2,4 | 1,2 (−1,1) | 1,06 (−0,7) | 0,96 (−0,7) |
| Willy-Brandt-Straße 50% | 2,6–2,9 | 0,7–0,8 (−0,6) | 0,81 (−0,4) | 0,61 (−0,3) |
| Gärtnerstraße 25% | 1,1–1,2 | 0,8 (−0,8) | 0,62 (+0,5) | 0,42 (+0,1) |
| Gärtnerstraße 50% | 1,2–1,3 | 0,6 (−0,6) | 0,61 (+0,5) | 0,36 (+0,1) |

- **Col semaforo la stima delle code è la migliore in tutti e quattro i casi.**
  A Gärtnerstraße l'errore è del 40–50% più basso che con i soli telefoni e lo
  sbilanciamento sparisce. A Willy-Brandt-Straße l'errore scende del 10–20%
  rispetto ai soli telefoni.
- **Sulla consulenza:**
  - a Gärtnerstraße l'energia resta al livello di quando si vedevano tutte le
    auto, e il costo in tempo della velocità per tratto (+5–6%) sparisce del
    tutto;
  - a Willy-Brandt-Straße al 50% l'energia è a +2% da quel livello;
  - a Willy-Brandt-Straße al 25% non migliora rispetto alla velocità per tratto
    (265 kJ contro 264): il tempo dei due semi è molto diverso (357 s e 331 s),
    e lì le spire coprono solo strade laterali.
- **Sugli accessi senza spira non cambia niente**, e sono la maggior parte: sul
  totale degli accessi l'errore resta quasi lo stesso. Il limite è la copertura
  delle spire, non il metodo.

**Il dato vero.** `drivenow/hamburg/live.py` si collega a
`wss://tld.iot.hamburg.de/mqtt` con la sola libreria standard: MQTT su
websocket, attraverso il proxy se c'è. Il broker chiude la connessione se
l'iscrizione arriva prima della sua conferma. `tools/hamburg_live.py` ascolta le
spire e i semafori di uno scenario e passa le spire allo stimatore. Esito:
ascolto di 10 minuti il 23 novembre 2026, dalle 5:08 ora di Amburgo (lunedì
all'alba, poco traffico):

| Scenario | Messaggi dalle spire | Spire che hanno parlato | Ritardo mediano | Messaggi dai semafori |
|---|---|---|---|---|
| Willy-Brandt-Straße | 210 | 19 su 38 | 1,1 s | 2.768 |
| Gärtnerstraße | 478 | 22 su 38 | 1,7 s | 3.023 |

Ogni auto fa due messaggi (occupata e poi libera), quindi sono circa 100 e 240
auto. Alla fine dell'ascolto lo stimatore dava un'auto ferma a un accesso di
Gärtnerstraße e nessuna altrove. Il flusso dal vivo quindi c'è, ed è quasi
immediato. Che le spire mute fossero ferme per il poco traffico o per un guasto
va visto con un ascolto nelle ore di punta.

### Dati pubblici su traffico, percorrenze, semafori, code e cantieri

Non c'è una fonte unica: ci sono centinaia di portali, ma usano pochi formati.
DriveNow ha quindi un adattatore per formato (`drivenow/sources/`), e ognuno scrive
nel database delle auto (`fleet.py`) tre cose:
- la velocità per tratto;
- le percorrenze;
- gli intralci (`drivenow/road_events.py`): cantieri, chiusure, restrizioni,
  limiti temporanei, incidenti, ostacoli, code con la loro lunghezza, meteo,
  ponti mobili, semafori fuori servizio. Ognuno ha la sua linea o il suo punto
  in lon/lat, inizio e fine, ed è abbinato ai tratti della rete.

| Adattatore | Fonte e formato | Cosa dà | Accesso |
|---|---|---|---|
| `datex2.py` | DATEX II v2 e v3, lo standard europeo: Paesi Bassi (NDW), Germania (Mobilithek), Francia, Belgio, Lussemburgo, Finlandia, Lettonia, Porto, Regno Unito, Scandinavia | situazioni, velocità e flussi per sito, percorrenze | aperto o registrazione |
| `autobahn.py` | API di Autobahn GmbH | cantieri (con limite), avvisi, chiusure sulle autostrade tedesche | aperto, senza chiave |
| `hamburg_traffic.py` | "Verkehrslage Hamburg" (WFS) | stato del traffico su ogni strada, ogni 5 minuti | aperto |
| `hamburg_police.py` | messaggi della polizia di Amburgo (WFS) | cantieri, chiusure, code, incidenti, semafori fuori servizio | aperto (DL-DE BY 2.0) |
| `hamburg/live.py` | semafori e spire di Amburgo (MQTT) | colori, secondi di ciclo, passaggi sulle spire | aperto |
| `digitraffic.py` | Fintraffic (Finlandia) | cantieri con limite e date, avvisi, limiti di peso | aperto |
| `torino.py` | 5T Torino | flusso e velocità per punto, ogni 5 minuti | aperto |
| `wzdx.py` | Work Zone Data Exchange (USA) e il registro dei feed USDOT | cantieri con limite e corsie chiuse | aperto o chiave |
| `here.py` | HERE Traffic API v7 | velocità, intensità delle code, incidenti, chiusure | chiave |
| `traffic_sources.py` | TomTom Traffic Flow; Waze for Cities | velocità per tratto; code | chiave; solo enti pubblici |
| `osm.py` | OpenStreetMap via Overpass | dove sono i semafori, limiti, strade in cantiere | aperto |

**DATEX II:** si leggono solo le posizioni date in coordinate. Quelle date solo in
codici Alert-C servono le tabelle di ogni paese: si contano e si scartano, senza
indovinarle. Il Belgio, per esempio, oggi ne ha 221 su 221.

**WZDx:** un evento "detour" è il percorso della deviazione, cioè la strada aperta
su cui viene mandato il traffico. Si tiene come "other" e non come chiusura:
altrimenti si chiuderebbe proprio la strada per aggirare il cantiere.

**Cosa si ricava:**
- **Percorrenza di ogni tratto** (`FleetDB.travel_time`), con la sua fonte e la
  sua età. Si prende la più diretta che c'è:
  1. quella misurata (DATEX II, NDW);
  2. quella delle auto DriveNow che l'hanno attraversato;
  3. la lunghezza divisa per la velocità per tratto (TomTom, HERE, Verkehrslage, DATEX);
  4. il limite.
- **Code:** una coda segnalata con la sua lunghezza (Waze, DATEX II, HERE,
  Autobahn) diventa auto ferme in fondo ai suoi tratti. Sugli accessi con
  semaforo noto resta lo stimatore delle spire.
- **Nella consulenza:**
  - un cantiere più avanti con limite più basso fa rallentare in tempo, senza
    nascondere i semafori dopo di lui (nuovo controllo `limit` nel motore);
  - una chiusura fa arrivare fermi prima, anche subito dopo un semaforo;
  - un semaforo segnalato fuori servizio non si usa: non è mai un verde;
  - sul pannello compaiono "Cantiere" e "Strada chiusa".
- **In simulazione:** `SumoWorld.load_road_events` dà gli intralci alla
  consulenza e, se richiesto, anche alle corsie di SUMO, così vi si attengono
  tutte le auto simulate.

**Il catalogo:** `data/traffic_sources.json` raccoglie 155 fonti in 25 paesi,
costruito con `tools/build_sources_catalog.py`:
- dai link di `graphhopper/open-traffic-collection`;
- dal registro USDOT dei cantieri (43 feed);
- dalle fonti verificate a mano.

Per ognuna ci sono:
- paese o zona;
- tipi di dato;
- formato;
- accesso (aperto, registrazione, chiave, solo enti);
- l'adattatore che la legge (81 fonti);
- l'esito del controllo da questo ambiente.

`tools/sources_catalog.py` le elenca per paese, tipo, accesso o adattatore, e con
`--check` prova a raggiungerle. Esito del controllo del 23 novembre 2026, dopo aver
aperto nell'ambiente di sviluppo gli host del catalogo:

| Esito | Fonti |
|---|---|
| Raggiunte | 87 |
| Senza risposta (il sito non risponde, interrompe o va in timeout) | 49 |
| Errore (HTTP 404: la pagina non c'è più) | 8 |
| Bloccate dalla rete di questo ambiente | 6 |
| Spostate su una home page (i dati non ci sono più) | 2 |
| Non controllata (MQTT di Amburgo, non HTTP; letta da `hamburg/live.py`) | 1 |

Prima di aprire gli host le fonti raggiunte erano 19. Dopo il controllo sono state aggiunte 2 fonti
di Amburgo: il WFS dei cantieri della città (raggiunto) e l'offerta DATEX II del LSBG su Mobilithek
(solo con abbonamento). L'ambiente accetta al massimo
128 host, quindi:
- 12 fonti spostate sono nel catalogo con il nuovo indirizzo (`moved_from` tiene
  il vecchio);
- restano bloccate le 4 pagine di documentazione di Google, HERE, TomTom e Waze,
  dove comunque non ci sono dati (il servizio dell'ambiente non le accetta);
- restano bloccati anche il secondo rimando di National Highways (Inghilterra) e
  il feed dell'Illinois, che chiede una chiave.

**Letture dal vivo** (`tools/public_data_check.py`, 23 novembre 2026, ore 12:14 UTC;
esito completo in `data/public_data_check_2026-11-23.json`):

| Fonte | Arrivato | Sulle reti di Amburgo |
|---|---|---|
| Polizia di Amburgo | 243 segnalazioni attive su 245: 156 chiusure, 62 cantieri, 19 restrizioni, 7 code, 1 semaforo fuori servizio | Willy-Brandt-Straße: 2 chiusure, 2 cantieri, 3 restrizioni; Gärtnerstraße: nessuna |
| Verkehrslage Amburgo | 645 + 356 tratti, dati di 4,5 minuti prima | velocità su 617 dei 867 tratti di Willy-Brandt-Straße e su 92 dei 105 di Gärtnerstraße |
| Autostrade intorno ad Amburgo (A1, A7, A23, A24, A25, A255) | 604 intralci: 528 cantieri, 67 chiusure, 5 code, 3 pericoli, 1 incidente (251 con limite) | nessuno: le due reti sono strade di città |
| NDW (Paesi Bassi) | 1.294 situazioni (1.287 con coordinate), 102 limiti temporanei, 1.634 aperture di ponti in programma, 20.619 siti (17.715 con velocità), 67.795 tratti (65.927 con percorrenza) | — |
| Finlandia | 824 cantieri (614 con limite), 19 avvisi, 20 limiti di peso | — |
| Torino | 112 punti, velocità media 63,6 km/h | — |
| Belgio | 221 situazioni, tutte solo in Alert-C | — |
| Porto (DATEX II v3) | pubblicazione valida, nessun condizionamento in corso | — |
| Cantieri USA (WZDx, 25 feed aperti dei 28 attivi senza chiave) | 42.167 eventi: 14.969 cantieri, 1.110 chiusure, 26.088 deviazioni ("other"); 8.946 attivi ora, 1.368 con limite | — |

**Limiti:**
- **HERE e TomTom:** sono provati solo su risposte scritte secondo il formato
  pubblicato, perché manca la chiave. Lo stesso vale per Overpass: l'host è aperto,
  ma interrompe la connessione da qui. Questi file di prova finiscono in `_written.json`.
- **WZDx:** dei 28 feed attivi senza chiave non si leggono New York (risposta
  vuota), St. Charles (connessione interrotta) e Kansas (timeout).
- **Direzione:** i messaggi della polizia di Amburgo sono punti senza direzione.
  Una chiusura in un senso solo si abbina a entrambi.
- **Velocità dalla Verkehrslage:** è stimata da una classe (scorrevole 100%,
  densa 70%, lenta 40%, a singhiozzo 15% della velocità libera). Sono ipotesi
  mie, non numeri della città.
- **Google Maps, Waze e Apple Maps** il traffico ce l'hanno, ma non lo danno
  come dato: si veda "Dove sono le altre auto".

### Cantieri e chiusure di Amburgo nelle simulazioni

**DATEX II per Amburgo: solo con abbonamento.** L'unico feed DATEX II con i cantieri delle
strade di Amburgo è "Traffic Disturbance Roadworks" del LSBG su Mobilithek (offerta
110000000003540000):
- DATEX II v2, aggiornato ogni ora, licenza aperta;
- per riceverlo servono un account Mobilithek, l'approvazione del fornitore e un certificato
  macchina rilasciato da Mobilithek.

Il client è pronto, in `drivenow/sources/mobilithek.py`. Legge i dati come prevede la
specifica tecnica di Mobilithek (§7.1.2.2.1):
- GET su `https://mobilithek.info:8443/…/subscription/<id>/clientPullService?subscriptionID=<id>`;
- TLS reciproco con il certificato, gzip, `If-Modified-Since`;
- 204/304 = niente di nuovo, 403 = abbonamento non autorizzato.

È provato solo su una risposta scritta secondo il formato (`tests/data/lsbg_written_v2.xml`):
senza abbonamento non ho dati veri. **Non funziona dalle sessioni cloud di sviluppo**: il loro
proxy intercetta il TLS e non lascia passare né il certificato client né la porta 8443. Si
usa da un computer con connessione diretta:

```bash
openssl pkcs12 -in macchina.p12 -out macchina.pem -nodes
python tools/hamburg_road_events.py --scenario willy-brandt --mobilithek-subscription ID --cert macchina.pem
```

**Fonti aperte usate ora** (`tools/hamburg_road_events.py`; le risposte grezze sono salvate
in `data/hamburg/<scenario>/road_events.json`, quindi le prove si possono ripetere):
- **Messaggi della polizia** (`hamburg_police.py`). "rechter/linker Fahrstreifen gesperrt"
  chiude quella corsia. Un messaggio valido solo in certe ore ("Mo - Fr zwischen 10:00 Uhr und
  16:00 Uhr") è escluso fuori da quelle ore.
- **Cantieri della città** (`hamburg_roadworks.py`, WFS "Bauweiser"): 135 cantieri, letti
  come punti con data di inizio e fine.
  - È una chiusura solo se il testo dice "Vollsperrung" e nulla la limita a un tratto, a
    un'ora o a una fase: 2 su 135.
  - Il limite di velocità c'è solo se il testo lo scrive esplicitamente: 1 su 135.
  - Il feed non dice quali corsie sono chiuse.
- **Strade citate:** i messaggi sono punti senza direzione, e un punto vicino a un incrocio è
  vicino a più strade. Si tengono quindi solo i tratti della strada citata ("Hamburg,
  Repsoldstraße zwischen …"). Prima di questa correzione la chiusura della Repsoldstraße
  chiudeva anche il Nordkanalbrücke.

**Le date: un "cosa succederebbe se".** Le simulazioni riproducono il 14 settembre 2023 dalle
17:00. Dei cantieri pubblicati oggi, 14 erano in vigore quel giorno ma nessuno sulle due reti.
Gli intralci letti il 23 novembre 2026 (16:44 ad Amburgo) sono quindi applicati, così come
erano in quel momento, all'ora registrata: i semafori restano quelli del 2023.

| Willy-Brandt-Straße | Cosa succede nella simulazione |
|---|---|
| Repsoldstraße, Hahntrapp: chiuse (polizia) | tratti chiusi, auto deviate |
| Ludwig-Erhard-Straße, Willy-Brandt-Straße: corsia di destra chiusa (polizia) | una corsia chiusa su 3 tratti ciascuna, in entrambi i sensi (i messaggi non dicono quale) |
| Kirchenallee (una corsia), Raboisen (senso unico), Steinstraße (cantiere della città) | nessun effetto: corsia non indicata, senso unico non rappresentato |
| Spaldingstraße, corsia di destra | escluso: solo lun–ven 10–16 |

Sulla Gärtnerstraße non resta nulla di applicabile. Il cantiere della città è "abschnittsweise
Vollsperrung", cioè chiusa a tratti senza dire quale, e la polizia non segnala nulla. Per
questo non ci ho fatto simulazioni.

**Prove sulla Willy-Brandt-Straße:**
- 25 simulazioni: 5 seed × 5 condizioni;
- 60 minuti ciascuna, di cui 10 di riscaldamento non contati;
- previsione dei semafori dalla registrazione ("predict");
- metà delle auto con DriveNow, nelle prove con DriveNow;
- viaggi contati: da 2.052 a 2.463 per esecuzione.

I seed cambiano l'imprecisione dei guidatori e quali auto hanno DriveNow; il traffico è
quello ricostruito per quell'ora. Le colonne riportano, per viaggio, tempo, fermate ed energia
di frenata, con media ± deviazione standard sui 5 seed. Con DriveNow sono quelle delle auto
DriveNow; senza DriveNow, di tutte le auto.

| Condizione | Tempo (s) | Fermate | Frenata (kJ) | Auto ancora in rete alla fine |
|---|---|---|---|---|
| senza DriveNow, senza intralci | 331,9 ± 7,3 | 3,43 | 376 ± 4 | 753 |
| senza DriveNow, con gli intralci | 368,0 ± 36,5 | 3,25 | 381 ± 9 | 722 |
| DriveNow, senza intralci | 345,8 ± 15,9 | 3,01 | 222 ± 2 | 900 |
| DriveNow, con gli intralci (li conosca o no) | 385,2 ± 38,9 | 3,04 | 232 ± 4 | 770 |

Con gli intralci, in ogni esecuzione sono state deviate 533 auto e 8 sono state tolte perché
non avevano un'altra strada.

**Cosa si vede:**
- **Gli intralci di oggi pesano:** +36 s per viaggio senza DriveNow (+11%), con molta
  variabilità tra i seed (± 37 s), dovuta alle deviazioni e alle corsie chiuse sull'asse
  principale.
- **DriveNow aiuta anche con gli intralci:**
  - le sue auto frenano il 39% in meno di tutte le auto senza DriveNow (232 contro 381 kJ),
    quasi come senza intralci (−41%);
  - il prezzo è di 14–17 s in più per viaggio (+4–5%).
- **Conoscere gli intralci non cambia nulla qui.** "Conosce" e "non conosce" danno gli stessi
  numeri, perché:
  - questi intralci non hanno limiti di velocità;
  - le auto deviate non entrano mai nei tratti chiusi;
  - il consiglio non usa le corsie chiuse: le vede solo attraverso le code.

  Servirebbero i limiti dei cantieri, che il feed DATEX II del LSBG dovrebbe avere e le fonti
  aperte no.
- **Da notare, anche senza intralci:** con metà delle auto DriveNow alla fine dell'ora restano
  in rete più auto (900 contro 753) e i viaggi completati sono l'8% in meno. Va capito a parte.

**Limiti:**
- **Punti senza direzione:** una corsia chiusa in un solo senso viene chiusa in entrambi.
- **Testi interpretati:** chiusure e corsie sono ricavate dal testo con regole prudenti, che
  nel dubbio non chiudono nulla.
- **Niente orari reali:** gli intralci sono di oggi, i semafori e il traffico del 2023.

Risultati per condizione: `data/hamburg/willy-brandt/road_events_results_2026-11-23.json`.

### Altri dati aperti di Amburgo: volumi, limiti ufficiali, strisce pedonali, stato del traffico

Quattro dataset della città (Behörde für Verkehr und Mobilitätswende, servizi WFS su
`geodienste.hamburg.de`, licenza [DL-DE BY 2.0](https://www.govdata.de/dl-de/by-2-0)):

| Dataset | Cosa contiene | Uso qui | Lettore |
|---|---|---|---|
| Verkehrsmengen 2019 (DTV) | veicoli al giorno per tratto di strada principale, i due sensi insieme | traffico tarato (`routes_dtv.rou.xml`) | `drivenow/sources/hamburg_volumes.py` |
| Zulässige Höchstgeschwindigkeiten | limite per tratto e senso, con le regole a orario ("Mo-Fr 6-19 h, sonst 50") | limiti ufficiali in simulazione | `drivenow/sources/hamburg_speed_limits.py` |
| Fußgängerüberwege | strisce pedonali (punti) | regola prudente nel consiglio | `drivenow/sources/hamburg_crossings.py` |
| Verkehrslage | classe di scorrimento ogni 5 minuti, solo dal vivo | controllo delle velocità simulate | `drivenow/sources/hamburg_traffic.py` |

Le prime tre si leggono con `python tools/hamburg_public_data.py` e si salvano in
`data/hamburg/<scenario>/public_data.json` (risposte grezze più l'ora di lettura). Il traffico
tarato si costruisce con `python tools/hamburg_build.py --scenario ... --demand dtv`.

**Cosa cambia nelle simulazioni** (opzioni di `tools/hamburg_experiment.py`; senza opzioni
tutto resta come prima):

- **`--demand dtv`, traffico tarato.**
  - Sull'asse principale ogni tratto con un volume ufficiale riceve DTV × 9% ÷ 2 auto nell'ora,
    per senso. Il 9% come quota dell'ora di punta e la divisione a metà tra i sensi sono
    ipotesi, scritte in `scenario.json`.
  - I volumi sono del 2019, i semafori del 2023.
  - Le strade laterali tengono il traffico di prima, perché non hanno conteggi aperti.
  - Willy-Brandt-Straße: 372 tratti con volume, 49.037 viaggi caricati nell'ora (prima 4.103).
    Gärtnerstraße: 48 tratti, 9.780 viaggi (prima 1.507).
  - Il flusso ottenuto rispetto all'obiettivo, per tratto: mediana 0,92 a Willy-Brandt-Straße,
    0,98 a Gärtnerstraße.
- **`--official-limits`, limiti ufficiali.** All'ora registrata (giovedì, dalle 17:00) il
  limite della città sostituisce quello di OpenStreetMap, sia per il consiglio sia per le auto
  in SUMO.
  - Differiscono 38 tratti su 830 a Willy-Brandt-Straße: 16 da 50 a 30, 15 da 50 a 20 e 2 da
    100 a 50.
  - A Gärtnerstraße ne differiscono 4 su 105.
- **`--crossings`, strisce pedonali.**
  - Nei 30 m prima delle strisce il consiglio non chiede mai di accelerare: "accelera" diventa
    "mantieni" (`hold:crossing`). Il pannello le mostra come prossimo controllo.
  - Il limite di velocità non cambia.
  - Le reti SUMO non hanno pedoni, quindi cambia solo il consiglio, non la sicurezza misurata.
  - Le strisce cadono su 42 tratti a Willy-Brandt-Straße e su 5 a Gärtnerstraße.

**Risultati.**
- **Impostazione:**
  - 36 esecuzioni: 2 reti, 6 condizioni, 3 seed (1, 2, 3).
  - Ogni esecuzione dura 60 minuti, con 10 di riscaldamento.
  - Semafori registrati, previsione "predict", penetrazione di DriveNow 0,5.
- **Cosa contano le colonne:**
  - "Viaggi contati" sono i viaggi completati dopo il riscaldamento, il minimo e il massimo tra
    i seed. Con DriveNow contano solo le auto DriveNow.
  - Tempo e frenata sono medie per viaggio, ± la deviazione standard tra i seed.
  - "Velocità sulle principali" è la mediana, tra i tratti principali, della velocità media
    divisa per il limite.

Gärtnerstraße:

| Condizione | Seed | Viaggi contati | Tempo (s) | Fermate | Frenata (kJ) | Altre auto: tempo (s) / frenata (kJ) | In rete alla fine | Velocità sulle principali (mediana, % del limite) |
|---|---|---|---|---|---|---|---|---|
| senza DriveNow, traffico ipotizzato | 3 | 927–951 | 175,6 ± 4,0 | 1,08 | 146 ± 2 | — | 293 | 76% |
| DriveNow, traffico ipotizzato | 3 | 430–482 | 181,6 ± 14,1 | 1,02 | 88 ± 1 | 177,6 ± 12,9 / 145 | 300 | 78% |
| senza DriveNow, traffico tarato | 3 | 4.569–4.623 | 121,6 ± 4,2 | 1,20 | 117 ± 2 | — | 556 | 55% |
| DriveNow, traffico tarato | 3 | 2.187–2.236 | 156,8 ± 0,9 | 1,48 | 51 ± 0 | 147,6 ± 1,9 / 100 | 657 | 51% |
| senza DriveNow, tarato + limiti + strisce | 3 | 4.448–4.628 | 123,6 ± 2,4 | 1,19 | 116 ± 1 | — | 587 | 51% |
| DriveNow, tarato + limiti + strisce | 3 | 2.142–2.195 | 160,6 ± 12,8 | 1,45 | 50 ± 3 | 154,3 ± 6,1 / 98 | 637 | 54% |

Willy-Brandt-Straße:

| Condizione | Seed | Viaggi contati | Tempo (s) | Fermate | Frenata (kJ) | Altre auto: tempo (s) / frenata (kJ) | In rete alla fine | Velocità sulle principali (mediana, % del limite) |
|---|---|---|---|---|---|---|---|---|
| senza DriveNow, traffico ipotizzato | 3 | 2.395–2.442 | 328,2 ± 7,3 | 3,43 | 376 ± 5 | — | 739 | 87% |
| DriveNow, traffico ipotizzato | 3 | 1.014–1.092 | 356,1 ± 10,2 | 2,97 | 222 ± 3 | 339,3 ± 15,6 / 338 | 930 | 73% |
| senza DriveNow, traffico tarato | 3 | 19.752–19.876 | 142,8 ± 6,3 | 0,85 | 50 ± 1 | — | 4.343 | 11% |
| DriveNow, traffico tarato | 3 | 8.477–8.683 | 135,5 ± 9,8 | 0,72 | 25 ± 0 | 133,8 ± 13,0 / 38 | 4.571 | 8% |
| senza DriveNow, tarato + limiti + strisce | 3 | 19.100–19.648 | 133,6 ± 6,9 | 0,77 | 48 ± 1 | — | 4.367 | 10% |
| DriveNow, tarato + limiti + strisce | 3 | 8.487–8.849 | 127,8 ± 11,4 | 0,70 | 25 ± 1 | 129,5 ± 9,9 / 40 | 4.601 | 8% |

**Cosa mostrano** (media ± deviazione standard su 3 seed; non è una prova definitiva):
- **DriveNow frena molto meno**, in ogni condizione. A Gärtnerstraße 88 kJ per viaggio contro 146
  senza DriveNow (traffico ipotizzato) e 51 contro 117 (traffico tarato). A Willy-Brandt-Straße 222
  contro 376 e 25 contro 50. Frena meno anche delle altre auto nella stessa esecuzione.
- **Il tempo di DriveNow è un po' più lungo** di quello delle altre auto nella stessa esecuzione:
  +5% a Willy-Brandt-Straße con il traffico ipotizzato (356,1 contro 339,3 s) e +6% a Gärtnerstraße
  con quello tarato (156,8 contro 147,6 s). Negli altri casi la differenza sta dentro la dispersione
  tra i seed.
- **Nel traffico denso DriveNow rallenta anche gli altri.** A Gärtnerstraße con il traffico tarato,
  quando metà delle auto usa DriveNow, le altre impiegano 147,6 s contro 121,6 s senza DriveNow
  (+21%), e alla fine restano in rete 657 auto invece di 556. Con il traffico ipotizzato questo
  effetto non si vede.
- **Willy-Brandt-Straße con il traffico tarato si blocca**: sulle principali la velocità mediana è
  l'8–11% del limite e alla fine restano in rete circa 4.300–4.600 auto. I tempi contano solo i
  viaggi che riescono a finire, quindi in quella condizione i numeri dicono poco.
- **Limiti ufficiali e strisce pedonali** cambiano i risultati meno della dispersione tra i seed
  (per esempio a Gärtnerstraße senza DriveNow 121,6 ± 4,2 s contro 123,6 ± 2,4 s).
- **Le due varianti di traffico non si confrontano sul tempo**: i viaggi sono diversi (con quello tarato
  sono molti di più e su percorsi diversi). Si confronta solo dentro la stessa variante.

**Confronto con lo stato del traffico (Verkehrslage).**
- **Come funziona:** `python tools/hamburg_verkehrslage_check.py --read` legge lo stato dal
  vivo. Poi `--compare FILE` mette ogni tratto principale in una classe in due modi e conta
  quanto spesso coincidono:
  - in base alla lettura;
  - in base alla simulazione, cioè la velocità media sul limite, assegnata alla classe di
    `SPEED_SHARE` più vicina. Quelle quote (fliessend 1,0, dicht 0,7, zäh 0,4, stockend 0,15)
    sono ipotesi.
- **Lettura usata:** martedì 24 novembre 2026, 17:07 ora di Amburgo, un giorno feriale all'ora
  della registrazione. Classi osservate sui tratti della rete:
  - Willy-Brandt-Straße: 393 scorrevoli, 203 densi e 12 rallentati (zäh), su 608.
  - Gärtnerstraße: 42 scorrevoli e 50 densi, su 92.
- **Quanto spesso la classe simulata coincide** con quella letta, su 61 tratti principali a
  Willy-Brandt-Straße e 40 a Gärtnerstraße:

  | Condizione | Willy-Brandt-Straße | Gärtnerstraße |
  |---|---|---|
  | senza DriveNow, traffico ipotizzato | 49% | 35% |
  | DriveNow, traffico ipotizzato | 39% | 38% |
  | senza DriveNow, traffico tarato | 5% | 32% |
  | DriveNow, traffico tarato | 8% | 32% |
  | senza DriveNow, tarato + limiti + strisce | 3% | 32% |
  | DriveNow, tarato + limiti + strisce | 5% | 30% |

- **Cosa dice:**
  - A Willy-Brandt-Straße il traffico tarato è molto più lento della realtà: la simulazione è
    più lenta della lettura nel 90–93% dei tratti. È coerente con il blocco descritto sopra, quindi
    lì la quota del 9% per l'ora di punta è probabilmente troppo alta per questa rete simulata.
  - Il traffico ipotizzato è più vicino: coincide nel 39–49% dei tratti, ed è più lento nel 46–56%.
  - A Gärtnerstraße le due varianti coincidono in modo simile (30–38%). Con il traffico ipotizzato
    la simulazione è più veloce della lettura nel 28–30% dei tratti, con quello tarato nel 5–12%.
- **Cautele:**
  - Una sola lettura di 5 minuti, di un altro giorno e di un altro anno rispetto ai semafori
    (2023) e ai volumi (2019).
  - Le quote di `SPEED_SHARE` che traducono la velocità in classe sono ipotesi: con quote diverse
    le percentuali cambiano.
  - La lettura notturna delle 00:19 dello stesso giorno, usata prima come prova del controllo, è
    stata sostituita. La lettura salvata è in `data/hamburg/<scenario>/verkehrslage.json`.

**Limiti:**
- **Anni diversi:** volumi del 2019, semafori e traffico laterale del 2023, limiti e strisce di
  oggi.
- **Ora di punta ipotizzata:** la quota del 9% è un'ipotesi. Con questa quota Willy-Brandt-Straße
  si blocca nella simulazione; nella realtà forse no, perché la rete simulata ha meno
  alternative e nessun ingresso graduale prima delle 17:00.
- **Niente pedoni:** la regola delle strisce non si può valutare per la sicurezza.

Risultati per condizione: `data/hamburg/open_data_results_2026-11-24.json` (con l'impostazione delle esecuzioni).

### Cantieri USA (WZDx) in simulazione

I cantieri dei feed WZDx sono negli Stati Uniti, quindi le prove girano su reti americane
costruite intorno a cantieri reali, attivi il 23 novembre 2026.

**Come si costruisce uno scenario.** `tools/wzdx_build.py` legge i feed WZDx aperti e prende i
cantieri:
- in vigore per l'ora successiva;
- con un limite ridotto o corsie chiuse;
- lunghi da 300 a 2.000 m.

Poi scarica la mappa OpenStreetMap della zona e la trasforma in una rete SUMO con le stesse
opzioni usate per Amburgo. Tiene il cantiere solo se nella rete restano almeno 3 semafori
vicini. In `data/wzdx/<nome>/` salva:
- la rete;
- il traffico;
- le coordinate dei tratti;
- `events.json`, cioè le voci del feed lette in quel momento: è una registrazione, quindi le
  prove si possono ripetere.

```bash
python tools/wzdx_build.py --pick 2 --cache /tmp/wzdx
python tools/wzdx_experiment.py predict --scenario modot-44-66-7th-st-lp-44-mo-66 --lights learned --events aware --seed 1
python tools/wzdx_summary.py CARTELLA_RISULTATI
```

| Scenario | Cantiere (dal feed) | Semafori nella rete (vicino al cantiere) |
|---|---|---|
| `idot-ia-12`, Sioux City (Iowa) | Gordon Drive (IA-12) chiusa nei due sensi, con deviazione | 12 (5) |
| `kytc-ky-864`, Louisville (Kentucky) | Logan Street (KY-864), una corsia chiusa verso nord per 1,6 km | 31 (14) |
| `modot-44-66-7th-st-lp-44-mo-66`, Joplin (Missouri) | East 7th Street (Route 66), limite di 56 km/h per 1,6 km | 7 (4) |

**Cosa fa la simulazione** (`drivenow/sumo_world.py`, `drivenow/wzdx_world.py`):
- **Orario:** l'orologio della simulazione parte dall'ora in cui il feed è stato letto. Ogni
  cantiere vale tra il suo inizio e la sua fine, e alla fine le corsie tornano come prima.
- **Limiti e corsie:** il limite si applica alle corsie in SUMO. Le corsie chiuse sono quelle
  indicate dal feed (contate da sinistra) quando il loro numero coincide con quello di SUMO;
  altrimenti si chiudono da destra. Una corsia resta sempre aperta, salvo che la strada sia
  chiusa.
- **Strada chiusa:** le auto il cui percorso la attraversa vengono deviate. Lo stesso vale per
  le auto il cui percorso non è più percorribile dopo una chiusura di corsie. Un'auto senza
  alternativa viene tolta e contata ("senza via").
- **Il consiglio:** può conoscere i cantieri ("conosce") oppure no ("non conosce"; la strada li
  ha comunque).
- **Misura di sicurezza:** si misura per quanto tempo il consiglio indica più del limite del
  cantiere + 2 km/h.

**I semafori:** OpenStreetMap dà dove sono, ma per queste strade non esistono tempi aperti.
SUMO assegna quindi un piano fisso stimato. Ci sono due casi:
- **tempi noti:** il consiglio conosce quel piano, come se la città lo trasmettesse (SPaT);
- **tempi imparati:** il consiglio impara ogni accesso dalle auto DriveNow (`probe.ProbeLearner`),
  come per i semafori senza dati di Amburgo. Un semaforo non ancora imparato non dà consiglio:
  non vale mai come verde.

**Le prove:**
- 105 simulazioni: 3 scenari × 7 condizioni × 5 seed;
- 60 minuti ciascuna, di cui 10 di riscaldamento non contati;
- traffico ipotizzato di 900 auto/h entranti (per queste strade non ci sono conteggi aperti);
- metà delle auto con DriveNow nelle prove con DriveNow.

Viaggi completati e contati, dopo il riscaldamento: da 665 a 701 per esecuzione, di cui circa
metà DriveNow.

Il file del traffico è uno solo per scenario. I seed cambiano quindi l'imprecisione dei
guidatori in SUMO e quali auto hanno DriveNow, non la domanda: lo scarto (±, deviazione standard
sui 5 seed) misura solo quella variabilità.

Le colonne riportano, per viaggio: tempo, fermate ed energia dissipata in frenata. Con DriveNow
sono quelle delle auto DriveNow; senza DriveNow, di tutte le auto.
"Oltre il limite" è la quota del tempo passato nel cantiere in cui il consiglio indicava più del
suo limite.

| Scenario | Condizione | Tempo (s) | Fermate | Frenata (kJ) | Oltre il limite |
|---|---|---|---|---|---|
| Sioux City | senza DriveNow, senza cantiere | 193,0 ± 0,6 | 1,6 | 533 ± 2 | — |
| | senza DriveNow, con il cantiere | 211,4 ± 0,7 | 2,1 | 557 ± 4 | — |
| | DriveNow, tempi noti | 227,4 ± 7,4 | 1,3 | 242 ± 8 | — |
| | DriveNow, tempi imparati | 224,2 ± 7,6 | 1,5 | 288 ± 10 | — |
| Louisville | senza DriveNow, senza cantiere | 186,2 ± 0,2 | 1,9 | 915 ± 5 | — |
| | senza DriveNow, con il cantiere | 186,9 ± 0,5 | 1,9 | 917 ± 4 | — |
| | DriveNow, tempi noti | 196,4 ± 4,8 | 1,2 | 481 ± 16 | — |
| | DriveNow, tempi imparati | 193,0 ± 3,3 | 1,5 | 538 ± 15 | — |
| Joplin | senza DriveNow, senza cantiere | 167,0 ± 0,6 | 1,0 | 403 ± 3 | — |
| | senza DriveNow, con il cantiere | 167,4 ± 0,5 | 1,0 | 390 ± 3 | — |
| | DriveNow, tempi noti, conosce il cantiere | 176,0 ± 1,5 | 0,5 | 184 ± 3 | 0,0% |
| | DriveNow, tempi noti, non lo conosce | 176,1 ± 1,6 | 0,6 | 187 ± 3 | 2,0 ± 0,2% |
| | DriveNow, tempi imparati, conosce il cantiere | 175,0 ± 1,1 | 0,7 | 219 ± 6 | 0,0% |
| | DriveNow, tempi imparati, non lo conosce | 175,1 ± 1,6 | 0,8 | 224 ± 7 | 2,1 ± 0,3% |

In tutte le prove DriveNow c'è anche la versione "non conosce il cantiere". A Sioux City e
Louisville dà numeri identici a "conosce": lì il cantiere non ha limite, e le auto deviate non
entrano mai nel tratto chiuso. Tutti i numeri sono in `data/wzdx/results_2026-11-23.json`.

**Cosa si vede:**
- **Con il cantiere, DriveNow aiuta ancora.** Le auto DriveNow frenano circa la metà
  (−48% a −57% con i tempi noti, −41% a −48% con i tempi imparati) e si fermano meno.
  - **Prezzo:** 6–16 s in più per viaggio, cioè il 3–8%.
  - **Il cantiere chiuso (Sioux City)** allunga i viaggi di tutti: +18 s senza DriveNow, +25 s
    per le auto DriveNow.
  - **37 auto su circa 900** non avevano un'altra strada e sono state tolte: i loro viaggi non
    sono contati.
- **Conoscere il cantiere conta dove c'è un limite (Joplin).** Il consiglio che non lo conosce
  indica più di 56 km/h per il 2% del tempo passato nel cantiere; quello che lo conosce, mai.
  - La frenata scende di poco, circa il 2%, dentro la variabilità tra i seed.
  - L'effetto è piccolo perché il limite del cantiere coincide con quello della strada (35 mph)
    su quasi tutta la sua lunghezza. Supera il limite stradale solo su 4 tratti dove OSM non ha
    `maxspeed` e SUMO mette 100 km/h.
- **Una corsia chiusa (Louisville)** cambia poco i tempi: +0,7 s senza DriveNow.
  - Ha però costretto a deviare 204 auto, la cui svolta partiva dalla corsia chiusa.
  - 24 auto sono state tolte perché non avevano un'altra strada.
- **Tempi imparati contro tempi noti:** 6–9 punti di frenata in meno di vantaggio, ma sempre
  sopra il 40%.

**Errori trovati facendo queste prove (corretti, con test):**
- **Cantieri e limiti di strada.** Con gli intralci caricati, il consiglio trattava come
  cantiere ogni calo normale del limite lungo il percorso. Ora un controllo "cantiere" nasce
  solo da un limite temporaneo più basso di quello della strada.
- **Semafori stimati e riuniti.** Quando SUMO dava al semaforo un nome diverso da quello
  dell'incrocio ("GS_…" per quelli stimati, impianti riuniti), `load_sumo_net` lasciava
  l'incrocio senza il suo programma: a Sioux City erano 10 su 12.
- **WZDx:**
  - un limite `NaN` (feed dell'Indiana) ora vale "nessun limite";
  - due o più corsie per auto tutte chiuse sono una chiusura anche se la banchina resta aperta
    (Iowa);
  - una sola corsia elencata come chiusa non lo è (Kentucky).

**Limiti:**
- I semafori e il traffico non sono quelli veri: il piano è stimato da SUMO e il volume è
  ipotizzato.
- **Chiusure di corsie:** quale corsia chiudere si deduce dall'ordine del feed solo quando il
  numero di corsie coincide.
- **Deviazioni:** si usa il percorso più rapido di SUMO, non il percorso alternativo indicato
  dal feed ("detour").
- Le auto tolte per mancanza di strada non entrano nelle medie.

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
python -m drivenow.server --autopilot --double-parking 30 --pedestrians 60
```

Seguendo un'auto che guida da sola, il pannello dice cosa vede ("auto a 22 m
(telecamera + radar) · semaforo rosso · pedone che aspetta"), e la mappa
disegna, tratteggiato, l'oggetto dove lo mettono i sensori, più le strisce
pedonali e chi le sta usando.

### I sensori (`drivenow/perception.py`)

Le strade del simulatore hanno una corsia, quindi la scena è lungo il
percorso: la prima auto davanti (i sensori non vedono attraverso di lei), il
prossimo semaforo, le strisce pedonali, le auto sulla strada principale
quando bisogna dare precedenza, e gli oggetti che un radar scambia per
ostacoli. La telecamera non è simulata a pixel: è simulato quello che esce
da un riconoscitore di immagini (una rete neurale che trova auto e pedoni e
legge i semafori), cioè se trova l'oggetto, a che distanza lo mette e quanto
spesso sbaglia. Un riconoscitore vero si collega allo stesso punto.

| Sensore | Auto davanti (sereno) | Pedoni | Strada principale (di lato) | Cosa non sa fare |
|---|---|---|---|---|
| Telecamera | 150 m; errore ~2,5 m a 50 m, ~7 m a 100 m | 80 m | 80 m | misura male distanze e velocità; notte, pioggia e soprattutto nebbia la accorciano; l'unica che legge il semaforo (120 m) |
| Radar | 160 m; errore 0,3 m e 0,15 m/s | male: metà delle volte, entro 60 m | 80 m, solo auto in movimento | ogni tanto vede un ostacolo fermo che non c'è ("fantasma", 2 per km); non legge i colori |
| Lidar | 120 m; pochi centimetri | 60 m | 80 m | non legge i colori; pioggia e nebbia lo accorciano molto |

| Meteo | Telecamera: auto | Telecamera: pedoni | Semafori | Radar | Lidar |
|---|---|---|---|---|---|
| Notte | 60% | 50% (non sono illuminati) | 100% (sono luci) | 100% | 100% |
| Pioggia | 70% | 70% | 80% | 90% | 60% |
| Nebbia | 30% | 30% | 40% | 95% | 35% |

Questi numeri sono plausibili ma non misurati su sensori veri: si cambiano in
cima a `perception.py`.

**Fusione.** Ogni oggetto davanti ha un filtro di Kalman su distanza e
velocità di avvicinamento; ogni rilevazione aggiorna l'oggetto più vicino per
distanza *e* velocità, oppure ne crea uno nuovo, che si usa dopo due
rilevazioni; due tracce dello stesso oggetto si fondono. Una regola viene
dalle auto vere: un oggetto **fermo** che vede solo il radar si ignora, a
meno che telecamera o lidar non l'abbiano visto due volte nell'ultimo secondo
o che sia stato visto muoversi (un'auto che si è fermata). Così spariscono i
fantasmi del radar, ma è anche il motivo per cui un radar da solo non trova
un'auto già ferma: con il solo radar le auto non partono nemmeno, perché non
possono fidarsi di nessun ostacolo fermo. Allo stesso modo un pedone c'è se
telecamera o lidar l'hanno visto due volte nell'ultimo secondo, o una volta
insieme al radar. Il colore del semaforo cambia solo quando due delle ultime
tre letture sono d'accordo. Le auto sulla strada principale si ricordano per
un secondo, portate avanti alla loro velocità.

### Come guida (`drivenow/autopilot.py`)

Solo i pedali: con una corsia sola non c'è niente da sterzare. A ogni passo
l'auto prende la più bassa di queste accelerazioni:

- **l'auto davanti**, come la vedono i sensori, con 1,5 s di distanza (un
  guidatore del simulatore ne tiene 1,2). Usa la distanza misurata meno due
  volte la sua incertezza: un'auto vista male si tiene più lontana;
- **un'auto che gira nella stessa strada** da un'altra direzione e arriva
  prima all'incrocio: le si va dietro (vale per tutti, vedi sotto);
- **la linea di arresto**, se deve fermarsi: rosso o giallo letti dalla
  telecamera o dati dai tempi del semaforo (basta uno dei due). Se i tempi
  dicono che arrivando sarà verde, continua a veleggiare come un guidatore
  DriveNow. Alle precedenze si ferma se un'auto della strada principale
  arriva entro 4 s, contando due volte l'incertezza della misura;
- **un pedone sulle strisce** che i sensori trovano: si ferma prima; per uno
  che aspetta sul marciapiede, se riesce a fermarsi senza frenare forte;
- **il consiglio DriveNow**, rallentando solo alzando il piede;
- **quello che non vede ancora**: mai più veloce di quanto serve per fermarsi
  comodamente (2 m/s²) entro la distanza a cui vedrebbe un'auto ferma (con
  la nebbia circa 36 m, quindi 42 km/h); lo stesso davanti a strisce
  pedonali ancora fuori vista e, senza tempi, a un semaforo che non vede
  ancora verde;
- **frenata d'emergenza** (6 m/s²) se l'urto arriverebbe entro 1,5 s,
  contando la velocità di avvicinamento più bassa compatibile con la misura,
  perché una stima rumorosa non deve inchiodare l'auto.

### Il simulatore per questa prova

Tre cose aggiunte al simulatore interno, che valgono anche per chi guida:

- **si entra a turno**: due auto che girano nella stessa strada da direzioni
  diverse non si sovrappongono più, passa prima quella che arriva prima;
- **doppia fila** (`--double-parking N`): N auto all'ora si fermano nella
  corsia per 15–40 s, ostacoli fermi mai visti muoversi;
- **pedoni** (`--pedestrians N`): strisce a metà di ogni strada più lunga di
  150 m, N persone all'ora per strisce. Aspettano 1,5 s sul marciapiede e
  attraversano (4 s nella corsia) quando nessuna auto in movimento è troppo
  vicina per fermarsi; il 5% invece attraversa senza guardare. Chi è
  investito da un'auto che non poteva fermarsi neanche frenando al massimo
  (8 m/s²) si conta a parte.

Le persone del simulatore vedono tutto senza errori e reagiscono subito:
il confronto con loro è a loro favore.

### Risultati

`tools/perception_experiment.py`: semi 1, 2 e 3, 30 minuti ciascuno, nessun
riscaldamento (contano i viaggi finiti dall'inizio), 220 auto all'ora per
ingresso, tutte DriveNow a guida autonoma (tranne le prime due righe),
30 auto all'ora in doppia fila, 60 pedoni all'ora per strisce. Città demo:
circa 3.450 viaggi finiti, 3.000 km e 4.000 pedoni per caso (somma dei tre
semi). Valori per viaggio: media dei tre semi, tra parentesi il seme
migliore e il peggiore. "Non vista" è la quota di istanti in cui c'era
davvero un'auto entro 40 m e i sensori non la davano. I conteggi a destra
sono totali dei tre semi.

| Città demo | Frenate | Energia nei freni | Tempo | Errore distanza | Non vista | Pedoni investiti | Precedenze mancate | Frenate fantasma |
|---|---|---|---|---|---|---|---|---|
| Persone, senza DriveNow | 3,03 (2,99–3,06) | 113,7 kJ | 108 s | | | 0 | 0 | |
| Persone con il consiglio DriveNow | 1,97 (1,91–2,03) | 39,3 kJ | 114 s | | | 0 | 0 | |
| Sensori perfetti (riferimento) | 2,17 (2,14–2,20) | 37,9 kJ | 116 s | 0 | 0 | 2 | 0 | 0 |
| Sereno, telecamera | 3,60 (3,53–3,66) | 41,4 kJ | 118 s | 0,55 m | 1,5% | 4 | 0 | 0 |
| Sereno, telecamera + radar | 2,52 (2,48–2,55) | 40,6 kJ | 118 s | 0,19 m | 0,8% | 0 | 0 | 5 |
| Sereno, + lidar | 2,48 (2,42–2,56) | 39,3 kJ | 115 s | 0,16 m | 1,2% | 4 | 0 | 8 |
| Notte, telecamera | 3,99 (3,76–4,14) | 48,6 kJ | 119 s | 0,88 m | 1,5% | 3 | 0 | 5 |
| Notte, telecamera + radar | 2,46 (2,25–2,71) | 43,2 kJ | 117 s | 0,25 m | 1,1% | 3 | 0 | 15 |
| Notte, + lidar | 2,59 (2,53–2,63) | 42,7 kJ | 117 s | 0,24 m | 1,1% | 3 | 0 | 18 |
| Pioggia, telecamera | 3,59 (3,41–3,92) | 42,4 kJ | 116 s | 0,75 m | 1,3% | 10 | 0 | 5 |
| Pioggia, telecamera + radar | 2,55 (2,52–2,60) | 41,8 kJ | 117 s | 0,23 m | 1,2% | 2 | 0 | 12 |
| Pioggia, + lidar | 2,50 (2,43–2,64) | 42,2 kJ | 116 s | 0,21 m | 1,0% | 2 | 0 | 25 |
| Nebbia, telecamera | 5,31 (4,97–5,79) | 49,2 kJ | 131 s | 1,24 m | 1,8% | 11 | 9 | 8 |
| Nebbia, telecamera + radar | 2,95 (2,84–3,04) | 40,7 kJ | 129 s | 0,27 m | 1,5% | 3 | 0 | 12 |
| Nebbia, + lidar | 3,53 (3,51–3,57) | 44,0 kJ | 127 s | 0,28 m | 1,3% | 4 | 0 | 34 |

Chi è stato investito senza alcuna possibilità di fermarsi è contato a parte
e non compare qui: da 2 a 9 per caso, 9 anche per le persone senza DriveNow.

**Sicurezza.** In nessun caso a guida autonoma, né qui né nella griglia 3×3
(circa 4.000 km per caso), ci sono stati tamponamenti o semafori passati col
rosso; le persone senza DriveNow, nella città demo, un tamponamento e un
rosso. I pedoni investiti che si potevano evitare sono tutti pedoni che
attraversano senza guardare: anche con sensori perfetti ne restano 2, perché
l'auto frena a 6 m/s² mentre il conto usa 8 m/s²; con la telecamera sola
salgono fino a 10–11 con pioggia e nebbia, con telecamera e radar restano
0–3. Le precedenze mancate (entrare nell'incrocio meno di 2 s prima di
un'auto della strada principale) ci sono solo con la telecamera sola nella
nebbia: 9 su circa 3.000 km, perché di lato vede solo 24 m.

**Guida.** La sola telecamera misura le distanze con un errore tre volte
più grande e l'auto corregge di più: +66% di frenate col sereno, +145% con la
nebbia, rispetto a sensori perfetti. Con il radar le frenate restano a +13–36%.
La nebbia costa a tutti il 9–13% di tempo, perché nessun sensore rende sicuro
andare più veloce di quanto vede la telecamera o il lidar.

**Lidar.** In città aggiunge poco: il radar dà già la distanza al
decimetro. In questo modello fa anzi peggio su due punti, che non ho
spiegato: con la nebbia più frenate (3,53 contro 2,95, una differenza più
grande di quella tra i semi) e più frenate fantasma (8–34 contro 5–15). Va
indagato prima di trarne conclusioni sul lidar vero.

Nella griglia 3×3 il quadro è lo stesso: frenate 0,75 a viaggio con sensori
perfetti, 1,16 con la sola telecamera, 0,90 con telecamera e radar (sereno);
2,40 e 1,38 con la nebbia. Pedoni investiti evitabili: 16 con la sola
telecamera nella nebbia, 0–6 negli altri casi.

**I tempi dei semafori non si vedono con una telecamera.** Una telecamera
legge il colore di adesso, non quando cambierà. Togliendo i tempi
(`--no-light-timing`) l'auto vede il rosso e si ferma come una persona, e
gran parte del risparmio di DriveNow sparisce:

| Città demo, sereno | Fermate | Frenate | Energia nei freni | Tempo |
|---|---|---|---|---|
| Persone, senza DriveNow | 1,33 | 3,03 | 113,7 kJ | 108 s |
| Telecamera + radar, con i tempi dei semafori | 0,72 | 2,52 | 40,6 kJ | 118 s |
| Telecamera + radar, senza tempi | 1,34 | 3,54 | 80,5 kJ | 114 s |
| Sola telecamera, senza tempi | 1,36 | 6,01 | 83,0 kJ | 114 s |

Nella griglia 3×3 l'energia nei freni va da 18 kJ con i tempi a 96–98 kJ
senza, contro 115 delle persone. Senza i tempi resta un po' di risparmio
perché l'auto, vedendo il rosso da lontano, alza il piede prima di una
persona. Ma i tempi dei semafori valgono più di qualsiasi sensore: è la
risorsa che DriveNow aggiunge a quello che l'auto vede da sola.

**Limiti.** Una corsia: niente sterzo, sorpassi, cambi di corsia o
ciclisti, e per averli serve un simulatore con più corsie (per esempio SUMO
con il modello a sottocorsie), non un'aggiunta a questo. Le rotonde usano
ancora la regola del simulatore senza errori dei sensori. Le code e le auto
lontane, usate dal consiglio, vengono ancora dalle auto connesse e non dai
sensori. Le auto che girano nella stessa strada si vedono senza errori. I
parametri dei sensori e dei pedoni sono stime, non misure; tre semi bastano
per le frenate e i tempi, non per contare eventi rari come gli incidenti.

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
  posizione, sempre filtrato lungo la strada (vedi "Con il GPS di un
  telefono"); per le altre auto le posizioni dei telefoni DriveNow e il
  traffico aggregato per tratto (TomTom, Waze for Cities, vedi "Dove sono le
  altre auto"). Un'auto con sensori propri vede da sola il veicolo davanti e il
  colore del semaforo: al posto del modello di `perception.py` vanno le
  uscite del riconoscitore d'immagini e del radar dell'auto.
- **Mappa.** La geometria va presa da OpenStreetMap o dai MAPEM, al posto
  della rete SUMO.

## Struttura

```
drivenow/
  glosa.py        calcolo: tempi d'arrivo, fasce, consiglio (nessuna dipendenza)
  signals.py      piani semaforici a tempo fisso e finestre di verde
  committed.py    finestre di verde certe e probabili di un semaforo comandato da un agente
  network.py      rete: città demo e caricatore .net.xml di SUMO
  advisor.py      unisce rete, traffico e calcolo: consiglio per veicolo e campo per la mappa
  simulation.py   simulatore interno (IDM, semafori, rotonda, precedenza)
  sumo_world.py   ponte TraCI con SUMO
  probe.py        orari dei semafori senza dati, imparati dalle auto e ricontrollati
  probe_reports.py  cosa dicono le auto DriveNow dei semafori senza dati (per probe.py)
  wzdx_world.py   mondo SUMO intorno a un cantiere USA reale, con i cantieri del suo feed WZDx
  display.py      quello che vede il guidatore: numero stabile, annunci distanziati
  profile_learner.py  quanto rallenta ogni auto a piede alzato, imparato dalla sua guida
  positioning.py  il GPS di un telefono (rumore, ritardo, buchi) e il filtro di Kalman lungo la strada
  fleet.py        il database delle auto in movimento: auto DriveNow una per una e traffico per tratto
  traffic_sources.py  traffico aggregato da TomTom Traffic Flow e dalle code di Waze for Cities
  road_events.py  intralci comuni a tutte le fonti: cantieri, chiusure, code, semafori fuori servizio
  sources/        adattatori per formato: DATEX II (anche l'abbonamento Mobilithek), Autobahn, Amburgo
                  (polizia, cantieri della città, Verkehrslage), Finlandia, Torino, WZDx, HERE, OSM
  estimator.py    code ai semafori dalle spire e dai telefoni
  perception.py   sensori dell'auto (telecamera, radar, lidar, meteo) e loro fusione
  autopilot.py    guida autonoma sui pedali, da quello che vedono i sensori
  hamburg/        dati reali di Amburgo: storico e previsione dei semafori, mondo SUMO,
                  spire emulate (detectors.py), flusso dal vivo MQTT (live.py)
  server.py       server della mappa (HTTP + Server-Sent Events, solo libreria standard)
web/              mappa: index.html, style.css, app.js
data/sumo/        reti a griglia 1×1–4×4 (dalla vecchia Traffc_light_control)
data/hamburg/     scenario reale di Amburgo (rete, semafori registrati, traffico, lon/lat dei tratti)
data/wzdx/        tre scenari intorno a cantieri USA reali (rete OSM, traffico ipotizzato, cantieri letti dal feed)
data/traffic_sources.json  catalogo delle fonti di dati di traffico trovate (153 in 25 paesi)
tools/            costruzione degli scenari di Amburgo e dei cantieri USA (wzdx_build.py), esperimenti (anche sensori e meteo:
                  perception_experiment.py), accuratezza delle previsioni imparate dalle
                  auto, registrazione delle pagine, agente PPO (ppo_train.py, ppo_bench.py),
                  carichi fissi per misurare i tempi (sim_profile.py), schede delle app
                  dall'APK con REA (app_scan.py)
docs/app-analizzate/  schede sulle app di riferimento (fonti dei dati semaforici, annunci, Android Auto)
tests/            pytest (i test SUMO si saltano se SUMO non è installato)
```

Test:

```bash
pip install pytest
python -m pytest
```

## Test dell’interfaccia

I controlli browser automatici verificano la demo su desktop e telefono,
oltre ai test Python del motore. Comandi e procedura facoltativa con
[vibetest-use](https://github.com/browser-use/vibetest-use) sono nella
[guida ai test browser](docs/browser-testing.md).

## Istruzioni per gli agenti di sviluppo

La repo include le procedure di sviluppo di **agent-skills**, collegate da
[`AGENTS.md`](AGENTS.md) e adattate al flusso di lavoro DriveNow tramite le
regole del progetto. Vedi la [guida](docs/agent-skills.md).

## Esperimenti con LibSignal

Il [ponte SUMO per LibSignal](docs/libsignal.md) legge i veicoli dal suo mondo
simulato e può applicare i consigli DriveNow mentre LibSignal controlla i
semafori. Include una verifica eseguibile con il sorgente upstream reale;
le finestre di verde possono essere fornite dal controllore o stimate dagli stati già osservati con `learn_signals=True`.

## Confronto previsioni con Darts

L'[esperimento offline Darts](docs/darts.md) confronta NaiveSeasonal con il
previsore DriveNow sui dati di Amburgo, usando solo il passato per prevedere.
Include un rapporto riproducibile e non modifica automaticamente il modello
usato per i consigli alle auto.

## Sviluppo in container isolati

[Container-use](docs/container-use.md) dispone di configurazione Python per
DriveNow, installer verificato, avvio MCP e una prova automatica che esegue
test e demo HTTP dentro il container. Richiede un motore Docker disponibile.

## Verifica browser con Playwriter

L'[integrazione Playwriter](docs/playwriter.md) esegue controlli desktop/mobile
attraverso il server MCP reale, salva screenshot e genera la configurazione
per collegare il proprio client al browser.

## Installare e avviare tutti gli strumenti

```bash
python tools/devtools.py setup
python tools/devtools.py status
```

Un solo comando di avvio per ogni strumento, ad esempio
`python tools/devtools.py run playwriter`. La configurazione MCP di progetto
è in `.mcp.optional.json` (Playwriter, container-use e Vibetest, da caricare in locale
su richiesta); [comandi, attivazione e prerequisiti](docs/operational.md).
