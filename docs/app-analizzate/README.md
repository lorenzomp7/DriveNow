# App di riferimento analizzate

Schede sulle app che danno già consigli ai semafori o che decidono quando e come parlare a
chi guida: da dove prendono i dati dei semafori, come annunciano, se supportano Android
Auto, quali permessi e servizi usano per la posizione in background. Ogni scoperta rimanda
a un punto del Piano DriveNow (foglio «Modifiche» del file «Piano di battaglia»):

| Punto | Tema | Cosa cercare nell'app |
|---|---|---|
| 2 | Qualità della previsione per semaforo, consiglio nascosto se scarsa | soglie di qualità, messaggi «previsione non valida» |
| 12 | Età e ritardo del dato semaforico | broker e topic (MQTT, SPaT/MAP, feed cittadini), timestamp, intervalli di risottoscrizione |
| 17 | GPS che salta oltre la linea da fermi | servizi di posizione, filtri, aggancio alla linea di arresto |
| 27 | Annunci a voce | motore TTS, frasi, distanze e tempi degli avvisi |
| 33 | Pannello che non copra la manovra, Android Auto | `androidx.car.app` nel manifest, servizi `CarAppService` |

## Regole

- Gli APK sono di terzi e **non entrano nella repo**: né APK, né codice decompilato, né
  risorse (immagini, suoni, testi). Nella repo va solo la scheda in Markdown.
- Si leggono dichiarazioni (manifest, permessi, servizi, librerie incluse, domini) per
  capire funzioni e interoperabilità. Niente copia di codice o risorse.
- Si analizzano solo APK ottenuti legalmente (installati sul proprio telefono e scaricati
  con `adb`, o forniti dall'editore). Niente aggiramento di protezioni: REA stesso lo esclude
  (`DISCLAIMER.md` del progetto).
- App open source (PrioBike): si legge il codice sorgente, citando file e commit.
- Ogni scheda riporta versione dell'app, data dell'analisi e strumenti usati; ogni
  scoperta dice da dove viene (file del manifest, classe, file sorgente) e a quale punto
  del Piano serve.

## Strumento: REA

[REA – Reverse Engineer Anything](https://github.com/morluto/rea) (licenza MIT, pacchetto
npm `rea-agents`, verificato su 6.10.1) è un server MCP e una CLI. Per gli APK usa JADX e
Apktool già installati sulla macchina e l'`adb` di chi lo usa; tutto gira in locale. Costo:
0 € (REA, JADX, Apktool, adb sono gratuiti).

REA è integrato come sottomodulo git `third_party/rea` (commit `b1b0bdf`, versione 6.10.1);
`python tools/devtools.py setup rea` installa in `.tools/` il pacchetto npm della stessa
versione e Apktool 2.12.1 (controllato con SHA-256), che `tools/app_scan.py` usa da lì.

```bash
python tools/devtools.py setup rea
export PATH="$PWD/.tools/rea/node_modules/.bin:$PWD/.tools/bin:$PATH"
rea inspect-adb-client                   # adb trovato? (REA_ADB_PATH per sceglierlo)
rea list-adb-devices
rea resolve-adb-packages <serial> trafficpilot   # nome del pacchetto
rea pull-adb-package <serial> <pacchetto> --output-directory /percorso/fuori/dalla/repo
```

Per ogni APK scaricato (anche gli split):

```bash
rea inspect-android-package /percorso/base.apk --detail summary --evidence_output /percorso/fuori/dalla/repo/app.evidence.json
rea inspect-apk-signature /percorso/base.apk           # firma, per legare la scheda a una build precisa
rea decode-android-resources /percorso/base.apk --locales de --locales it --string-tables-only   # frasi degli annunci
rea search-android-classes /percorso/base.apk mqtt      # e poi: spat, mapem, tts, car.app, location
rea inspect-dart-aot /percorso/base.apk                 # app Flutter: motore e simboli Dart
```

Da `inspect-android-package` servono: permessi, servizi (posizione in primo piano o in
background), ricevitori, intent filter, provider, `meta-data` (Android Auto:
`com.google.android.gms.car.application`, servizi con `androidx.car.app.CarAppService`).
Da classi e risorse: domini e porte dei dati semaforici, formati (SPaT/MAP J2735, ETSI
SPATEM/MAPEM, MQTT, FROST/SensorThings), motore e frasi della sintesi vocale.

Le prove (`evidence.json`) restano fuori dalla repo, come gli APK.

## Dall'APK alla scheda: `tools/app_scan.py`

Lo script passa l'APK a REA (`decode-android-resources`, che usa Apktool, e
`inspect-apk-signature`) e scrive le tabelle della scheda: versione, firma, permessi, servizi
in primo piano, Android Auto, librerie riconoscibili dall'elenco dei file, stringhe sui temi
della scheda. Le prove REA vanno nella cartella indicata, fuori dalla repo; lo script rifiuta
APK e prove dentro la repo.

```bash
python tools/devtools.py setup rea
python tools/app_scan.py ../apks/base.apk ../apks/split_config.arm64_v8a.apk --app "trafficpilot" \
    --evidence-dir ../apks/evidence --source "telefono proprio, adb" --out docs/app-analizzate/trafficpilot-apk.md
```

Cosa resta da leggere a mano: come l'app usa ciò che dichiara (da dove arrivano i dati dei
semafori, quando parla). Per questo REA usa JADX con il suo ponte `jadx-headless-mcp`
(`REA_JADX_MCP_JAR`), che va scaricato e verificato da chi analizza; qui non è installato.

## App analizzate

| App | Perché | Scheda | Fonte |
|---|---|---|---|
| PrioBike (TU Dresden) | consigli ai semafori di Amburgo, open source | [priobike.md](priobike.md) | codice sorgente |
| Organic Maps | navigatore open source con Android Auto e voce | [organic-maps.md](organic-maps.md) | APK ufficiale, `tools/app_scan.py` |
| trafficpilot (GEVAS) | prognosi rosso/verde dalle centrali del traffico, Android Auto | [trafficpilot.md](trafficpilot.md) | fonti pubbliche |
| Priotalker (Yunex) | collaudo degli iVRI olandesi, richiesta di priorità | [priotalker.md](priotalker.md) | fonti pubbliche |
| Sway (Be-Mobile) | tempo al verde e annuncio d'arrivo agli iVRI fiamminghi | [sway.md](sway.md) | fonti pubbliche |
| Google Maps | interfaccia in Android Auto, semafori sulla mappa | [google-maps.md](google-maps.md) | fonti pubbliche |
| Waze | annunci a voce riferiti ai semafori | [waze.md](waze.md) | fonti pubbliche |
| Traffic Lanes 2 | interfaccia (gioco) | [traffic-lanes-2.md](traffic-lanes-2.md) | fonti pubbliche |
| Traffix | interfaccia (gioco) | [traffix.md](traffix.md) | fonti pubbliche |

Le schede da fonti pubbliche segnano «da verificare (APK)» dove serve il manifest: si
completano con `tools/app_scan.py` su un APK preso dal proprio telefono con
`rea pull-adb-package`. Nessuna scoperta è scritta a memoria: ogni riga ha la sua fonte.
