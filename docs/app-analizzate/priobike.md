# PrioBike (TU Dresden) – scheda

- Progetto: [priobike/priobike-flutter-app](https://github.com/priobike/priobike-flutter-app),
  licenza MIT, app Flutter per ciclisti ad Amburgo
- Versione letta: `pubspec.yaml` 1.0.7, commit `d8c1f0c6eae1b7ce085f9ee6cf688a07b913ba1e`
  (2 dicembre 2024)
- Data dell'analisi: 2026-11-24; metodo: lettura del codice sorgente (app open source, REA non
  serve). Nessun codice copiato in DriveNow: qui ci sono solo osservazioni e rimandi ai file.

## Dati dei semafori (punti 2 e 12)

| Cosa | Trovato | Dove |
|---|---|---|
| Previsione | servizio di previsione proprio, MQTT, un topic per gruppo di segnale (`subscribe(sg.id)`), QoS «at least once» | `lib/ride/services/prediction.dart` r. 104 |
| Broker | `priobike.vkw.tu-dresden.de` porte 20050/20032 (production/staging), `priobike.flow-d.de:20050` (release) | `lib/settings/models/backend.dart`, `predictionServiceMQTTPath/Port` |
| Formato | JSON: `startTime`, `value` (un valore al secondo da `startTime`), `greentimeThreshold` (verde se `value` ≥ soglia), `predictionQuality` in [0, 1] | `lib/ride/messages/prediction.dart` r. 82-124 |
| Qualità per secondo | la distanza di `value` dalla soglia, riscalata tra minimo e massimo del vettore, dà una qualità per ogni secondo (vicino alla soglia = incerto) | idem r. 178-196 |
| Età del dato | i secondi già passati da `startTime` vengono tolti dal vettore; se il vettore è finito la previsione è scartata | idem r. 144-151 |
| Aggiornamento | una previsione nuova è attesa 60 s dopo `startTime`: nel frattempo l'app si disconnette dal broker (energia) e si riconnette a quell'ora | `prediction.dart` r. 200-212 |
| Dati grezzi | osservazioni FROST/SensorThings di Amburgo via MQTT (`v1.1/Datastreams(<id>)/Observations` su `tld.iot.hamburg.de`): segnale primario, secondo del ciclo, programma, rilevatori auto e bici; tenute 180 s | `lib/ride/services/datastream.dart` |
| Soglia per parlare | consigli a voce solo con qualità ≥ 0,85; se scende sotto mentre prima era sopra: «Achtung, aktuelle Prognose nicht mehr gültig» | `lib/ride/services/audio.dart` r. 38-39, 234-245, 647 |

## Annunci a voce (punto 27)

| Cosa | Trovato | Dove |
|---|---|---|
| Motore | `flutter_tts` (TTS di sistema), voce tedesca scelta per nome quando c'è, velocità regolabile; `audio_session` abbassa la musica durante l'annuncio | `pubspec.yaml`, `audio.dart` r. 116-157 |
| Quando | due finestre di distanza dalla prossima luce: tra 300 e 200 m e tra 100 e 50 m, un annuncio per finestra | `audio.dart` r. 33-36, 293-313 |
| Cosa dice | «In <distanza arrotondata a 25 m> meter Ampel/Radampel», poi «rot in» o «grün in» con i secondi al cambio più vicino all'arrivo; il numero detto è corretto del tempo passato a parlare; da fermi al rosso un conto alla rovescia «Grün in 5 …» | `audio.dart` r. 370-420, 586-630, 498-501 |
| Velocità usata | mediana degli ultimi ~20 s di velocità sopra 1,5 m/s (default 5 m/s) per calcolare l'arrivo | `audio.dart` r. 315-338 |

## Posizione in background (punto 17)

| Cosa | Trovato | Dove |
|---|---|---|
| Permessi | `ACCESS_FINE_LOCATION`, `ACCESS_BACKGROUND_LOCATION`, `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_LOCATION`, `WAKE_LOCK`, `POST_NOTIFICATIONS` | `android/app/src/main/AndroidManifest.xml` r. 8-16 |
| Servizio | `geolocator` con notifica in primo piano, una posizione al secondo, `distanceFilter` 0; precisione «bestForNavigation» solo in carica, altrimenti «best» | `lib/positioning/services/positioning.dart` r. 242-264 |
| Aggancio al percorso | la posizione viene proiettata sul percorso (`positioning.snap`) e la distanza alla prossima luce si calcola lungo il percorso | `audio.dart` r. 564, `ride.calcDistanceToNextSG` |

## Android Auto (punto 33)

Nessuna dichiarazione `androidx.car.app` o `com.google.android.gms.car.application` nel
progetto Android: l'app non supporta Android Auto.

## Cosa ne prende DriveNow

- Punto 2: una qualità per secondo ricavata dalla distanza dalla soglia, e una soglia unica
  sotto cui non si dà il consiglio (PrioBike usa 0,85), con un avviso quando la qualità cala
  durante l'avvicinamento.
- Punto 12: ogni previsione ha un istante d'inizio; l'età si toglie dal vettore e una
  previsione esaurita non vale più. Con dati che arrivano a intervalli noti (60 s) si sa
  anche quando aspettarsi il dato nuovo e quando considerarlo in ritardo.
- Punto 17: posizione proiettata sul percorso e distanza alla luce lungo il percorso, non in
  linea d'aria.
- Punto 27: annunci a finestre di distanza (non a tempo), una volta per finestra, con la
  musica abbassata; conto alla rovescia solo da fermi al rosso.
- Punto 33: nessun riferimento da qui; servono le schede di Google Maps e Waze.
