# Organic Maps – scheda dall'APK

- Pacchetto: `app.organicmaps.web`, versione `2025.07.13-9-Web` (`25071309`), SDK minimo 21, destinazione 36
- APK sha256: `764c15853e1d84e0e25d7735d4b3a1beba171dc8d10832538432a633100dcc16`
- Firma: `b9c7ae79a5a90270df08a132e536b9c666f5bef1f59b304fcecf8687865e4b5b` (schema v2)
- Data dell'analisi: 2026-11-24; strumenti: REA 6.10.1 (`decode-android-resources`, `inspect-apk-signature`), Apktool 2.12.1; `tools/app_scan.py`
- Fonte dell'APK: release ufficiale dell'editore su GitHub (organicmaps/organicmaps, tag 2025.07.13-9-android, file OrganicMaps-25071309-web-release.apk), sha256 verificato con il .sha256sum pubblicato; APK e prove REA fuori dalla repo

Questa parte è generata dalle dichiarazioni dell'APK (manifest, risorse, elenco dei file): dice che cosa l'app può fare e con quali librerie, non come lo usa.

## Dati dei semafori (punti 2 e 12)

| Cosa | Trovato | Dove |
|---|---|---|
| Librerie e motori | Google Play services location (fused), androidx.car.app (Android Auto) | elenco dei file: `play-services-location.properties`, `META-INF/androidx.car.app_app-projected.version` |
| Stringa | Traffic Lights | `@string/type.highway.traffic_signals` |

## Annunci a voce (punto 27)

| Cosa | Trovato | Dove |
|---|---|---|
| Servizi TTS interrogati | android.intent.action.TTS_SERVICE | manifest, `<queries>` |
| Stringa | Voice search | `@string/abc_searchview_description_voice` |
| Stringa | Voice Instructions | `@string/pref_tts_enable_title` |
| Stringa | TtsEnabled | `@string/pref_tts_enabled` |
| Stringa | TtsInfo | `@string/pref_tts_info` |
| Stringa | TtsInfoLink | `@string/pref_tts_info_link` |
| Stringa | TtsLanguage | `@string/pref_tts_language` |
| Stringa | Voice Language | `@string/pref_tts_language_title` |
| Stringa | Speech Synthesis settings were not found, are you sure your device supports it? | `@string/pref_tts_no_system_tts` |
| Stringa | Speech synthesis system settings | `@string/pref_tts_open_system_settings` |
| Stringa | "Check the volume or system Text-To-Speech settings if you don't hear the voice now." | `@string/pref_tts_playing_test_voice` |
| Stringa | TtsScreen | `@string/pref_tts_screen` |
| Stringa | TtsStreetNames | `@string/pref_tts_street_names` |

## Posizione in background (punto 17)

| Cosa | Trovato | Dove |
|---|---|---|
| Permessi di posizione e servizio | `ACCESS_COARSE_LOCATION`, `ACCESS_FINE_LOCATION`, `WAKE_LOCK`, `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_LOCATION`, `POST_NOTIFICATIONS` | manifest, `<uses-permission>` |
| Servizio in primo piano | `app.organicmaps.routing.NavigationService` (location) | manifest, `<service>` |
| Servizio in primo piano | `app.organicmaps.location.TrackRecordingService` (location) | manifest, `<service>` |
| Servizio in primo piano | `app.organicmaps.downloader.DownloaderService` (dataSync) | manifest, `<service>` |

## Android Auto (punto 33)

| Cosa | Trovato | Dove |
|---|---|---|
| Dichiarazione | `CarAppService` `app.organicmaps.car.CarAppService`, categoria NAVIGATION | manifest, `<service>` |
| Dichiarazione | `com.google.android.gms.car.application` = `@xml/automotive_app_desc` | manifest, `<meta-data>` |
| Dichiarazione | `androidx.car.app.minCarApiLevel` = `5` | manifest, `<meta-data>` |
| Dichiarazione | permesso `androidx.car.app.NAVIGATION_TEMPLATES` | manifest, `<uses-permission>` |
| Dichiarazione | permesso `androidx.car.app.ACCESS_SURFACE` | manifest, `<uses-permission>` |

## Tutti i permessi

`ACCESS_COARSE_LOCATION`, `ACCESS_FINE_LOCATION`, `ACCESS_LOCATION_EXTRA_COMMANDS`, `ACCESS_NETWORK_STATE`, `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_DATA_SYNC`, `FOREGROUND_SERVICE_LOCATION`, `FOREGROUND_SERVICE_SPECIAL_USE`, `INTERNET`, `POST_NOTIFICATIONS`, `READ_EXTERNAL_STORAGE`, `RECEIVE_BOOT_COMPLETED`, `WAKE_LOCK`, `androidx.car.app.ACCESS_SURFACE`, `androidx.car.app.NAVIGATION_TEMPLATES`, `app.organicmaps.web.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION`
## Cosa ne prende DriveNow

Organic Maps (licenza Apache 2.0) non è nell'elenco del Piano: è qui come app di navigazione
open source con Android Auto e voce, la prima analizzata con `tools/app_scan.py`.

- Punto 33: per comparire in Android Auto come navigatore servono un `CarAppService` con
  categoria `NAVIGATION`, i permessi `androidx.car.app.NAVIGATION_TEMPLATES` e
  `ACCESS_SURFACE` (la mappa è disegnata dall'app sulla superficie dell'auto) e
  `com.google.android.gms.car.application` nel manifest. Il loro codice per l'auto è
  pubblico (cartella `car` dell'app Android nel repository `organicmaps/organicmaps`).
- Punto 17: la navigazione gira in un servizio in primo piano di tipo `location` con
  notifica, senza `ACCESS_BACKGROUND_LOCATION`: la posizione resta accessibile a schermo
  spento perché il servizio è avviato mentre l'app è in primo piano.
- Punto 27: sintesi vocale di sistema (`TTS_SERVICE` tra le query), con scelta della lingua
  e opzione per leggere i nomi delle strade.
