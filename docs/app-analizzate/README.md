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

```bash
npm install --global rea-agents          # oppure npx -y rea-agents@latest <comando>
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

## App da analizzare

| App | Perché | Scheda | Stato |
|---|---|---|---|
| PrioBike (TU Dresden) | consigli ai semafori di Amburgo, open source | [priobike.md](priobike.md) | fatta dal codice sorgente |
| trafficpilot | consigli di velocità sui semafori reali | [modello](_modello.md) | serve l'APK |
| Priotalker | idem, per auto | [modello](_modello.md) | serve l'APK |
| Sway | idem | [modello](_modello.md) | serve l'APK |
| Google Maps | quando e come parla, Android Auto | [modello](_modello.md) | serve l'APK |
| Waze | idem | [modello](_modello.md) | serve l'APK |
| Traffic Lanes 2, Traffix | interfaccia (giochi di traffico) | [modello](_modello.md) | serve l'APK |

Per le app chiuse la scheda si compila solo dopo l'analisi dell'APK della versione indicata:
finché manca, nella tabella resta «serve l'APK» e nessuna scoperta viene scritta a memoria.
