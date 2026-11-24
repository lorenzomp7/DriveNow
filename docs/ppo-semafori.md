# Semafori comandati dal PPO e finestre «impegnate»

DriveNow è nato da Traffc_light_control, che a sua volta viene da
[Multi-Agent-Distributed-PPO-Traffc-light-control](https://github.com/MagMueller/Multi-Agent-Distributed-PPO-Traffc-light-control)
di MagMueller: stesse reti a griglia di `data/sumo/` (i file 2×2 sono identici byte per byte),
stesso SUMO. Lì un agente PPO per incrocio decide ogni secondo se cambiare fase; le fasi
verdi del file di rete durano 100000 s proprio perché le termina l'agente. Il futuro di
quei semafori non è noto, e finora DriveNow, per dare consigli, li sostituiva con il ciclo
fisso del `CycleRuleSet` della stessa repository.

Questa integrazione (Piano DriveNow, foglio «Integrazioni GitHub», DriveNow n. 1; punti 7 e
9 del foglio «Modifiche») fa girare il PPO vero e dà al consiglio solo ciò a cui l'agente è
impegnato.

## Le finestre «impegnate» (`drivenow/committed.py`)

Un agente non può violare le proprie regole: un verde dura almeno `min_green`, l'agente
decide solo ogni `decision_interval` secondi, un cambio passa sempre dal giallo (e
dall'eventuale tutto rosso), e con `max_green` un verde finisce entro quel limite. Dallo
stato presente (fase accesa e da quanto) `committed_windows` ricava:

- finestre **certe**: verde qualunque cosa decida l'agente. Con il verde acceso: fino alla
  prima decisione in cui il cambio è consentito. Con il verde dell'altra direzione: solo se
  il massimo dell'altra fase è così corto che il nostro verde, comunque inizi, è acceso in
  quell'intervallo. Con il giallo dell'altra direzione: dall'inizio sicuro del nostro verde
  per il verde minimo;
- finestre **probabili**: il verde acceso tenuto fino al massimo, oppure il prossimo verde
  all'ora in cui arriva al più tardi. Senza massimo il verde acceso è «aperto» (orizzonte
  intero, mai certo).

Non si legge nessun piano futuro: solo `getPhase` e il tempo trascorso nella fase. Una
decisione dovuta proprio adesso conta come ancora da prendere.

`CommittedSignalSource` applica la funzione a una rete SUMO con programmi a due verdi
(verde, giallo, verde, giallo) ed è un `windows_fn` per `Advisor` e `LibSignalAdvisor`:

- `mode="certain"`: solo le finestre certe, segnate certe (il contratto di
  `LibSignalAdvisor` in `docs/libsignal.md`: verdi garantiti, nessuna previsione se non ce
  ne sono);
- `mode="committed"`: le finestre certe quando dicono tutto (le probabili coincidono),
  altrimenti le probabili segnate **non certe**, che `glosa.advise` usa solo per piccoli
  cambi di velocità (al più 10 km/h in meno).

Con `record=True` tiene ogni finestra certa data al consiglio e `check(t)` dice quali
movimenti, in una finestra certa, in SUMO non sono verdi: la misura `false_green_s` del
confronto.

## Addestrare il PPO (`tools/ppo_train.py`)

Il repository non dichiara una licenza: il codice non è copiato in DriveNow. Lo script lo
importa da una copia separata e usa le sue classi (`IntersectionsEnv`, `NN_Model`,
`PPOWorker`) in un solo processo, senza interfaccia grafica. I pesi vanno fuori dalla repo,
con un file JSON accanto (parametri, rollout, tempo, commit del repository esterno).

```bash
pip install -r requirements-ppo.txt
git clone https://github.com/MagMueller/Multi-Agent-Distributed-PPO-Traffc-light-control ../ppo_ext
python tools/ppo_train.py --ppo-repo ../ppo_ext --out ../ppo_weights/ppo_2x2.pt --rollouts 200
```

Il repository è del 2023: lo script supplisce a due cose cambiate da allora (TraCI tiene le
connessioni in `traci.connection`, NumPy non ha più `np.float`/`np.int`) senza modificarne
i file. Iperparametri del repository (`constants/constants.json`), rete 2×2, 200 rollout da
2048 passi invece di 300 (21 minuti su 2 CPU).

## Il confronto (`tools/ppo_bench.py`)

```bash
python tools/ppo_bench.py --ppo-repo ../ppo_ext --weights ../ppo_weights/ppo_2x2.pt \
    --seeds 1 2 3 --out docs/benchmarks/ppo-2x2
```

Stessi veicoli in tutti i casi (punto 9): per ogni seme il file degli arrivi è scritto una
volta e dato a ogni caso (l'hash è in `docs/benchmarks/ppo-2x2.json`); la quota DriveNow è
0 % o 100 %, quindi anche le auto equipaggiate sono le stesse. L'agente vede lo stato del
repository letto da SUMO (auto in coda sui rilevatori di 150 m a fine di ogni arco, fase,
secondi nella fase, tempo normalizzato a 1250 s) e campiona l'azione dalla sua
distribuzione con un generatore con seme.

Casi: ciclo fisso senza consiglio e con il piano noto; PPO **come addestrato** (decide ogni
secondo, nessun verde minimo o massimo, come nel repository) e PPO **con verde 5-60 s**
(stesso agente; le richieste di cambio prima di 5 s di verde sono rifiutate, a 60 s il
cambio è imposto, come fanno SUMO-RL e GreenWave); per ciascuno nessun consiglio, solo
finestre certe, certe + probabili.

Rete 2×2, 216 veicoli/h per ingresso (la probabilità 0,06 al secondo del repository) per
1000 s, simulazione fino a 1250 s, riscaldamento 200 s (contano i viaggi conclusi dopo),
passo 0,2 s, semi 1, 2, 3, pesi sha256 `6a234a23e975…`:

| Semafori | Regole | Consiglio | Viaggi | Tempo (s) | Fermate | Energia freni (kJ) | Δ tempo | Δ fermate | Δ energia | Verde promesso falso (s) |
|---|---|---|---|---|---|---|---|---|---|---|
| ciclo fisso | – | nessuno | 418 | 93,6 ± 1,0 | 1,37 ± 0,03 | 149,1 ± 3,0 |  |  |  | 0 |
| ciclo fisso | – | piano noto | 419 | 95,6 ± 1,5 | 0,13 ± 0,03 | 17,0 ± 2,0 | +2,2 % | −90,5 % | −88,6 % | 0 |
| PPO | come addestrato | nessuno | 420 | 106,3 ± 3,4 | 2,22 ± 0,08 | 181,9 ± 1,0 |  |  |  | 0 |
| PPO | come addestrato | solo certe | 422 | 106,6 ± 1,9 | 2,19 ± 0,08 | 127,7 ± 2,9 | +0,3 % | −1,2 % | −29,8 % | 0 |
| PPO | come addestrato | certe + probabili | 420 | 105,0 ± 1,1 | 2,13 ± 0,07 | 135,7 ± 3,2 | −1,2 % | −3,9 % | −25,4 % | 0 |
| PPO | verde 5-60 s | nessuno | 417 | 85,6 ± 2,4 | 1,32 ± 0,08 | 156,7 ± 7,5 |  |  |  | 0 |
| PPO | verde 5-60 s | solo certe | 419 | 93,6 ± 1,1 | 1,61 ± 0,03 | 108,5 ± 2,5 | +9,4 % | +22,3 % | −30,7 % | 0 |
| PPO | verde 5-60 s | certe + probabili | 418 | 86,5 ± 2,3 | 1,34 ± 0,08 | 138,2 ± 5,9 | +1,1 % | +1,8 % | −11,8 % | 0 |

Media ± deviazione standard tra i semi (viaggi: media); Δ rispetto agli stessi semafori
senza consiglio. Dati per corsa in `docs/benchmarks/ppo-2x2.csv`.

Cosa dice:

- **Nessun verde promesso falso.** Nelle corse in cui il consiglio riceve finestre certe
  (8.000-22.000 per corsa; con «certe + probabili» arrivano sempre come probabili, perché il
  massimo verde lascia sempre un dubbio) erano sempre verdi in SUMO. Un test fa anche la prova contraria:
  con finestre calcolate per un verde minimo di 20 s mentre l'agente cambia dopo 5 s, il
  controllo trova verdi promessi falsi.
- **Con un agente si sa poco.** Con il piano noto il consiglio toglie il 90 % delle fermate;
  con il PPO le fermate non calano (−4 % al massimo, dentro la variabilità) perché
  l'agente non si impegna mai su un verde che arriverà. Cala l'energia nei freni (12-31 %):
  le auto arrivano più piano ai rossi già sicuri.
- **Solo le finestre certe costano tempo** quando l'agente ha un verde minimo: un verde
  acceso è certo solo per pochi secondi, dopo i quali il consiglio deve dare per rosso ciò
  che non sa, e le auto rallentano per luci che poi restano verdi (+22 % fermate, +9 % tempo).
  Certe + probabili non costa tempo ed è la scelta da usare con un agente.
- **Il PPO addestrato qui, lasciato libero, cambia troppo spesso**: circa 950 cambi per
  corsa (uno ogni 5 s per incrocio), più lento del ciclo fisso (106 s contro 94 s) e anche
  di un agente casuale che cambia con probabilità 0,1 a ogni decisione (96,5 s, 1,47
  fermate sugli stessi semi). Con il verde 5-60 s lo stesso agente diventa il migliore dei
  controllori (85,6 s contro 93,6 s del ciclo fisso e 93,5 s del casuale con le stesse
  regole). Sono 200 rollout invece di 300 e le auto di DriveNow non sono quelle
  dell'addestramento (accelerazione 1,4 m/s² invece di 0,8, velocità del tratto invece di
  15 m/s): un agente addestrato meglio potrebbe cambiare il quadro, non il risultato sulle
  finestre certe.

Limiti: una sola rete (2×2) e tre semi; quota DriveNow 0 % o 100 %, non intermedia (con
quote intermedie l'equipaggiamento in SUMO viene ancora dal generatore casuale, punto 9);
l'agente reagisce alle auto DriveNow, quindi «PPO con consiglio» confronta anche due
comportamenti diversi dell'agente. Non provato qui: `tools/libsignal_smoke.py` con
`CommittedSignalSource` (richiede l'ambiente LibSignal di `docs/libsignal.md`).

## Verifica

```bash
python -m pytest -q tests/test_committed.py tests/test_ppo_bench.py
```

`test_committed.py` prova la funzione pura (verde appena iniziato, oltre il minimo, vicino al
massimo, decisione dovuta adesso, verde dell'altra direzione, agente senza regole);
`test_ppo_bench.py` fa girare SUMO con un agente casuale che rispetta le regole e controlla
che le finestre certe siano sempre verdi, che il controllo veda un verde promesso falso e che
i casi abbiano gli stessi veicoli. Senza SUMO i test SUMO si saltano.

## Prossimi passi del Piano

L'ambiente `AgentWorld` di `tools/ppo_bench.py` (stato del repository, azione «cambia o no»,
regole dell'agente, finestre impegnate) è la base per il Gymnasium del punto 30 e per il
PettingZoo del punto 31: un agente per incrocio è già il modo in cui il PPO è addestrato.
