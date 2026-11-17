# Amburgo: dati reali

Due scenari, ognuno nella sua cartella. Per entrambi l'ora di prova va da
giovedì 14 settembre 2023 alle 17:00 (ora locale) alle 18:00, e i file
contengono anche 90 minuti di storico prima di quell'ora, che servono alla
previsione.

| Cartella | Corridoio | Impianti semaforici |
|---|---|---|
| `gaertnerstrasse/` | Osterstraße → Gärtnerstraße → Breitenfelder Straße, circa 1,8 km | 87, 1334, 1315, 504, 1046, 910, 168, 684, 683, 682 |
| `willy-brandt/` | Willy-Brandt-Straße / Ludwig-Erhard-Straße, circa 1,9 km | 305, 2438, 467, 79, 78, 96, 50, 246, 310 |

In ogni cartella:

| File | Contenuto | Fonte |
|---|---|---|
| `signals.csv.gz` | ogni cambio di stato dei semafori (`primary_signal`), gli inizi ciclo (`cycle_second`) e i rilevatori di veicoli (`detector_car`) del corridoio | registrazione TU Dresden del servizio *Traffic Lights Data* di Amburgo |
| `lanes.json` | le relazioni corsia di ingresso → corsia di uscita di ogni impianto, con geometria e ID dei datastream | API SensorThings di Amburgo (`tld.iot.hamburg.de`) |
| `corridor.net.xml` | rete SUMO della zona; semafori solo dove Amburgo ne ha | OpenStreetMap, convertito con `netconvert` |
| `links.json` | per ogni link semaforico di SUMO, la corsia di Amburgo corrispondente e la qualità dell'abbinamento (`direct`, `relaxed`, `along`, `none`) | calcolato da `tools/hamburg_build.py` |
| `routes.rou.xml` | un'ora di traffico (1.507 viaggi a Gärtnerstraße, 4.103 a Willy-Brandt-Straße) | conteggi reali dei rilevatori di Amburgo dove esistono, più un volume ipotizzato sull'asse principale dove mancano |
| `scenario.json` | inizio dell'ora di prova, storico, impianti, ipotesi di traffico | |

Note sui dati:

- Il dato `cycle_second` ha buchi lunghi. A Gärtnerstraße manca per quasi
  tutta l'ora di prova; la previsione allora ricava il ciclo dai semafori
  stessi (vedi `drivenow/hamburg/signals.py`).
- `along` indica un attraversamento pedonale a metà isolato: Amburgo lo
  descrive come parte dell'incrocio vicino, e si usa il segnale della corsia
  che ci passa sopra. Gli abbinamenti non esatti il cui segnale è verde meno
  del 10% dell'ora vengono scartati, perché bloccherebbero la strada.

Si ricostruisce tutto con:

```bash
python tools/hamburg_build.py --scenario gaertnerstrasse --cache /tmp/hamburg-cache
python tools/hamburg_build.py --scenario willy-brandt --cache /tmp/hamburg-cache
```

## Codici dei semafori

0 spento, 1 rosso, 2 giallo, 3 verde, 4 rosso-giallo, 5 giallo lampeggiante,
6 verde lampeggiante, 9 sconosciuto.

## Licenze e attribuzioni

- **Semafori.** Jeschor, D. M.; Matthes, P.; Springer, T.; Pape, S.; Fröhlich, S.,
  *Traffic Light Data of Hamburg collected in September and October 2023
  (Observations from SensorThings API)*, TU Dresden, 2024, licenza
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/),
  <https://opara.zih.tu-dresden.de/handle/123456789/605>. I dati originali
  sono della Freie und Hansestadt Hamburg (LSBG), con licenza
  [Datenlizenz Deutschland – Namensnennung – 2.0](https://www.govdata.de/dl-de/by-2-0).
- **Corsie e geometrie.** Freie und Hansestadt Hamburg, servizio *Traffic Lights Data*,
  [dl-de/by-2-0](https://www.govdata.de/dl-de/by-2-0).
- **Mappa.** © i contributori di [OpenStreetMap](https://www.openstreetmap.org/copyright),
  licenza [ODbL](https://opendatacommons.org/licenses/odbl/).
