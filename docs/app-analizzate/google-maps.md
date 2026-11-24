# Google Maps – scheda da fonti pubbliche

- Pacchetto `com.google.android.apps.maps`
- Data: 2026-11-24. **Fonti pubbliche, non l'APK**.

## Dati dei semafori (punti 2 e 12)

| Cosa | Trovato | Fonte |
|---|---|---|
| Semafori | disegnati sulla mappa (con gli stop) dal 2022; in Android Auto un riquadro sull'incrocio successivo avvisa di semafori e stop (2026) | [BGR](https://bgr.com/2196167/waze-useful-new-feature-traffic-lights/), [BGR Android Auto](https://www.bgr.com/2268294/google-maps-new-traffic-light-feature-android-auto/) |
| Fasi e consiglio di velocità | non offerti nelle fonti; nelle Fiandre Google Maps non è collegata agli iVRI (2025) | [VRT](https://www.vrt.be/vrtnws/nl/2025/07/23/al-200-000-weggebruikers-hebben-app-die-verkeerslichten-sneller/) |

## Annunci a voce (punto 27)

Da verificare (APK) per motore e frasi; dall'ottobre 2026 conversazione con Gemini anche in
CarPlay ([borncity.com](https://borncity.com/news/google-gemini-in-carplay-sprachgesteuerte-navigation-startet-weltweit/)).

## Android Auto (punto 33)

| Cosa | Trovato | Fonte |
|---|---|---|
| Interfaccia | tachimetro con velocità attuale accanto al limite (luglio 2026); tempo, limiti e semafori sempre visibili (settembre 2026); modalità a schermo intero (maggio 2026) | [googlewatchblog.de](https://www.googlewatchblog.de/2026/07/android-auto-google-maps-navigation-hat-endlich-einen-tacho-grosses-update-zeigt-die-aktuelle-geschwindigkeit/), [borncity.com](https://borncity.com/news/android-auto-google-maps-zeigt-tempo-und-ampeln-dauerhaft-an/), [auto-motor-und-sport.de](https://www.auto-motor-und-sport.de/tech-zukunft/update-fuer-android-auto-google-macht-das-auto-schlauer-im-vollbildmodus/) |
| Manifest | da verificare (APK); Maps è integrata in Android Auto, non usa le librerie per app di terzi | – |

## Cosa ne prende DriveNow

- Punto 33: il riferimento per chi guida è un riquadro piccolo per l'incrocio successivo e
  velocità attuale accanto al limite, sempre nello stesso posto: il pannello di DriveNow
  deve stare in un angolo fisso e non coprire la manovra.
- Nessuna fonte per dati semaforici: DriveNow non può appoggiarsi a Google Maps per le fasi.
