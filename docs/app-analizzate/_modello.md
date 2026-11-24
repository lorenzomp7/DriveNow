# <Nome app> – scheda

- Pacchetto: `<com.esempio.app>`, versione `<versionName>` (`<versionCode>`)
- Firma (`rea inspect-apk-signature`): `<sha-256 del certificato>`
- Data dell'analisi: `<AAAA-MM-GG>`; strumenti: REA `<versione>`, JADX `<versione>`, Apktool `<versione>`
- Fonte dell'APK: `<telefono proprio via adb / editore>`; APK e prove fuori dalla repo

## Dati dei semafori (punti 2 e 12)

| Cosa | Trovato | Dove (manifest, classe, risorsa) |
|---|---|---|
| Domini, porte, broker | | |
| Formato (SPaT/MAP, SPATEM/MAPEM, MQTT, FROST, proprietario) | | |
| Qualità / soglie / «previsione non valida» | | |
| Età del dato, risottoscrizioni, timeout | | |

## Annunci a voce (punto 27)

| Cosa | Trovato | Dove |
|---|---|---|
| Motore TTS (Android TTS, proprio, file audio) | | |
| Frasi (stringhe, lingue) | | |
| Distanze o tempi degli avvisi | | |

## Posizione in background (punto 17)

| Cosa | Trovato | Dove |
|---|---|---|
| Permessi (`ACCESS_BACKGROUND_LOCATION`, `FOREGROUND_SERVICE_LOCATION`) | | |
| Servizi in primo piano (`foregroundServiceType`) | | |
| Librerie di posizione (fused, filtri) | | |

## Android Auto (punto 33)

| Cosa | Trovato | Dove |
|---|---|---|
| `androidx.car.app` / `CarAppService` / categoria | | |
| `meta-data` `com.google.android.gms.car.application` | | |

## Cosa ne prende DriveNow

- Punto `<n>`: `<idea, in parole nostre; niente codice o risorse copiate>`
