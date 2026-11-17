# Amburgo: dati reali

Corridoio di Willy-Brandt-Straße / Ludwig-Erhard-Straße, nel centro di
Amburgo: circa 1,9 km e 9 impianti semaforici (ID 305, 2438, 467, 79, 78,
96, 50, 246, 310). L'ora di prova va da giovedì 14 settembre 2023 alle 17:00
(ora locale) alle 18:00. Il file contiene anche 90 minuti di storico prima di
quell'ora, che servono alla previsione.

| File | Contenuto | Fonte |
|---|---|---|
| `signals.csv.gz` | ogni cambio di stato dei semafori (`primary_signal`), gli inizi ciclo (`cycle_second`) e i rilevatori di veicoli (`detector_car`) del corridoio | registrazione TU Dresden del servizio *Traffic Lights Data* di Amburgo |
| `lanes.json` | le relazioni corsia di ingresso → corsia di uscita di ogni impianto, con geometria e ID dei datastream | API SensorThings di Amburgo (`tld.iot.hamburg.de`) |
| `corridor.net.xml` | rete SUMO della zona; semafori solo dove Amburgo ne ha | OpenStreetMap, convertito con `netconvert` |
| `links.json` | per ogni link semaforico di SUMO, la corsia di Amburgo corrispondente e la qualità dell'abbinamento (`direct`, `relaxed`, `none`) | calcolato da `tools/hamburg_build.py` |
| `routes.rou.xml` | un'ora di traffico (8.387 viaggi) | conteggi reali dei rilevatori di Amburgo dove esistono, più un'ipotesi di 900 veicoli/ora per tratto sull'asse principale, che non ha rilevatori |
| `scenario.json` | inizio dell'ora di prova, storico, ipotesi di traffico | |

Si ricostruisce tutto con:

```bash
python tools/hamburg_build.py --cache /tmp/hamburg-cache
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
