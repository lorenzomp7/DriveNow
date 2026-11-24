# trafficpilot (GEVAS software) – scheda da fonti pubbliche

- Editore: GEVAS software (Monaco di Baviera); Android e iOS (App Store id1376583513)
- Data: 2026-11-24. **Fonti pubbliche, non l'APK**: le righe «da verificare» si chiudono con
  `tools/app_scan.py` su un APK preso dal proprio telefono (`rea pull-adb-package`).

## Dati dei semafori (punti 2 e 12)

| Cosa | Trovato | Fonte |
|---|---|---|
| Da dove | prognosi rosso/verde calcolata **sui server della centrale del traffico** della città (Düsseldorf, Leipzig, Hannover…), dal calcolatore centrale che riceve i dati degli impianti | [iphone-ticker.de](https://www.iphone-ticker.de/traffic-pilot-gruene-welle-app-fuer-radfahrer-143570/), [l-iz.de](https://www.l-iz.de/wirtschaft/mobilitaet/2025/10/handyapp-fur-leipzig-digitaler-ampelphasen-assistent-grune-welle-637626), [visit-hannover.com](https://www.visit-hannover.com/en/Hannoverweb/Innovation/Zukunft/Testbetrieb-der-%22trafficpilot%22-App-f%C3%BCr-effizienteren-Stadtverkehr) |
| Quale semaforo | analisi della mappa e scelta del semaforo successivo nella direzione di marcia **lato server**; l'app manda la posizione via rete mobile | iphone-ticker.de |
| Cosa mostra | solo il semaforo successivo; un utente segnala qualche secondo di attesa prima dei dati di quello dopo | [appshunter.io](https://appshunter.io/ios/app/trafficpilot/id1376583513) |
| Qualità | la prognosi è mostrata con colori e un'indicazione di affidabilità | [vodafone.de](https://www.vodafone.de/featured/article/gruene-welle-app-traffic-pilot-bringt-radfahrer-entspannter-ans-ziel-74123) |
| Copertura | non ovunque: le prognosi ci sono solo nelle città collegate (Leipzig: 300 impianti all'avvio) | [teltarif.de](https://www.teltarif.de/dienste/pg2-android-auto.html), l-iz.de |
| Protocollo, età del dato | da verificare (APK) | – |

## Annunci a voce (punto 27)

Da verificare (APK): le fonti parlano di visualizzazione e consiglio di velocità, non di voce.

## Posizione in background (punto 17)

Da verificare (APK). Modi separati per auto e bici.

## Android Auto (punto 33)

| Cosa | Trovato | Fonte |
|---|---|---|
| Supporto | Android Auto e CarPlay dall'aggiornamento di fine ottobre 2026, con navigazione integrata | teltarif.de, notizia del 01.11.26 |
| Dichiarazioni nel manifest | da verificare (APK) | – |

## Cosa ne prende DriveNow

- Punto 12: tutta la logica (mappa, semaforo successivo, prognosi) sta sul server; l'app è
  un visualizzatore. Il ritardo tra il passaggio di un semaforo e i dati del successivo è
  un problema visibile agli utenti: DriveNow deve avere già il semaforo dopo.
- Punto 2: affidabilità mostrata insieme alla prognosi.
- Punto 33: la stessa app passa ad Android Auto quando aggiunge la navigazione: il modello
  «navigatore» di Android Auto (vedi `organic-maps.md`) è la strada.
