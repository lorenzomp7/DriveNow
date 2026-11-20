# Esperimento Darts sui semafori di Amburgo

Il comando `tools/darts_benchmark.py` usa davvero **Darts NaiveSeasonal**
(`u8darts==0.39.0`) per confrontare una previsione stagionale con
`CyclePredictor` di DriveNow. È un esperimento offline: il server e il consiglio
alle auto continuano a usare il motore esistente. Nessuna chiave API, GPU,
rete o addestramento neurale è necessario per eseguire il confronto dopo
l'installazione delle dipendenze.

## Avvio

Da DriveNow, con Python 3.12:

```bash
python -m venv .venv-darts
.venv-darts/bin/python -m pip install -r requirements-darts.txt
.venv-darts/bin/python tools/darts_benchmark.py
```

Su Windows usare `.venv-darts\Scripts\python.exe`. Il rapporto è scritto in
`test-results/darts.json`, escluso da Git. Parametri:

```bash
.venv-darts/bin/python tools/darts_benchmark.py --scenario gaertnerstrasse --signals 5 --minutes 20 --stride 17 --lookback 1800 --output test-results/darts-gaertnerstrasse.json
```

I modelli Torch/StatsForecast/XGBoost opzionali possono generare avvisi di
assenza all'import di Darts: NaiveSeasonal non li richiede. Non occorre
installarli per questa prova. Le dipendenze risolte sono fissate in
`requirements-darts.txt`; il vincolo diretto è in `requirements-darts.in`.
Aggiornare esplicitamente con
`uv pip compile requirements-darts.in -o requirements-darts.txt`, verificando
nuovamente installazione, test ed esperimento.

## Protocollo

- I segnali sono i primi N ID ordinati fra quelli associati alla rete dello
  scenario: selezione deterministica, non un campione rappresentativo di Amburgo.
- Ogni 17 secondi si effettua una nuova previsione fino a 90 secondi avanti.
  Il passo non coincide con i tipici cicli di 60 secondi.
- A ogni origine temporale, la cronologia per **entrambi** i modelli viene
  fisicamente troncata al presente. Darts riceve fino a 1.800 campioni passati,
  uno al secondo, comprendendo il campione attuale; il primo target è t+1.
- Il periodo è ricavato da `CyclePredictor.cycle()` sui soli dati passati,
  inclusa la sorgente del secondo del ciclo quando disponibile. È quindi un
  confronto fra modelli con una stima del periodo condivisa, non due sistemi
  completamente indipendenti. Il riferimento DriveNow usa la propria normale
  logica e finestra storica; non è vincolato allo stesso numero di campioni.
- NaiveSeasonal ripete l'ultimo ciclo osservato; non è una rete neurale né un
  modello di probabilità calibrato. I valori binari verdi/non verdi usano la
  soglia 0,8; DriveNow mantiene la sua soglia 0,8 e la logica del verde corrente.
- Dopo uno stato sconosciuto si usa soltanto il tratto noto contiguo più recente.
  Servono almeno due cicli; se mancano ciclo o dati, il confronto si astiene.
  Non si interpolano buchi né si trasformano stati ignoti in rosso.
- La verità futura viene letta solo per il punteggio, escludendo stati ignoti
  e target oltre l'ultima osservazione del segnale. Codici e unità seguono
  `SignalHistory` (incluso verde lampeggiante fra gli stati verdi).
- Accuratezza, falsi verdi e verdi mancati sono calcolati **sugli stessi campioni**.
  Le ultime due metriche hanno come denominatore tutti i campioni abbinati,
  non soltanto i verdi previsti o reali. La copertura è riportata separatamente.

Si tratta di una valutazione a origini successive: al passo seguente possono
entrare in training osservazioni precedentemente valutate, perché ormai note.
Nessun parametro viene scelto sulla base dei target futuri. Le previsioni e i
segnali sono correlati; i conteggi non sono prove statistiche indipendenti.

## Esecuzione registrata

[Rapporto JSON](benchmarks/darts-willy-brandt.json), generato con i valori
definiti di default: Willy-Brandt-Straße, primi 20 minuti, 5 segnali, 71 origini
per segnale, 355 campioni per orizzonte e copertura abbinata del 100%.
Il rapporto contiene ID, periodi stimati, parametri, versione Darts e SHA-256
dei quattro file di input, per rendere il confronto riproducibile.

| Orizzonte | Accuratezza DriveNow | Accuratezza Darts | Falsi verdi DriveNow | Falsi verdi Darts |
|---|---:|---:|---:|---:|
| 5 s | 96.06% | 95.77% | 0.00% | 1.97% |
| 15 s | 96.62% | 97.75% | 0.28% | 1.41% |
| 30 s | 95.49% | 95.49% | 0.00% | 2.25% |
| 60 s | 95.21% | 95.49% | 0.56% | 2.54% |
| 90 s | 95.77% | 94.65% | 0.00% | 2.82% |

Darts trova alcuni verdi che DriveNow scarta, ma aumenta anche i falsi verdi
in questo campione. Non emerge un motivo per sostituire automaticamente il
previsore in uso. Il risultato riguarda **solo NaiveSeasonal**, non dimostra
che tutti i modelli Darts siano peggiori. Non misura fermate, energia o tempi
di viaggio; per questo servirebbe un successivo esperimento SUMO controllato.

## Verifiche

I test `tests/test_darts_benchmark.py` verificano che alterare il futuro non
modifichi training e previsioni, che i buchi causino astensione, che l'orizzonte
parta da t+1 e che le metriche usino i campioni abbinati. Il workflow
`Darts benchmark` installa la libreria reale ed esegue un breve confronto sui
dati inclusi; non si limita ai test con sostituto del modello.

Fonti della libreria: [TimeSeries](https://unit8co.github.io/darts/generated_api/darts.timeseries.html)
e [modelli baseline](https://unit8co.github.io/darts/generated_api/darts.models.forecasting.baselines.html).
Provenienza e licenze dei dati restano in [data/hamburg/README.md](../data/hamburg/README.md).
