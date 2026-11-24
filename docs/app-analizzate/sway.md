# Sway (Be-Mobile) – scheda da fonti pubbliche

- Editore: Be-Mobile NV (Belgio); pacchetto `bike.sway` (Google Play), iOS «Sway Cycling»
  (id6451053939); per ciclisti
- Data: 2026-11-24. **Fonti pubbliche, non l'APK**.

## Dati dei semafori (punti 2 e 12)

| Cosa | Trovato | Fonte |
|---|---|---|
| Cosa mostra | tempo al verde in tempo reale ai semafori intelligenti | [Google Play](https://play.google.com/store/apps/details?id=bike.sway&hl=en), [App Store](https://apps.apple.com/be/app/sway-cycling/id6451053939) |
| Verso il semaforo | dalla 1.2.0 (giugno 2024) impara i percorsi abituali e **annuncia l'arrivo** del ciclista ai semafori intelligenti | App Store, cronologia versioni |
| Rete | Fiandre: circa 230 incroci con semafori intelligenti (2025); la Regione fornisce un SDK per condividere la posizione con gli iVRI; con Flitsmeister e Karta GPS è tra le poche app collegate, Google Maps e Waze no | [vlaanderen.be](https://www.vlaanderen.be/mobiliteit-en-openbare-werken/te-voet-fiets-bromfiets/mobilidata), [VRT](https://www.vrt.be/vrtnws/nl/2025/07/23/al-200-000-weggebruikers-hebben-app-die-verkeerslichten-sneller/) |
| Protocollo, età del dato | da verificare (APK) | – |

## Posizione in background (punto 17)

| Cosa | Trovato | Fonte |
|---|---|---|
| Uso | su iOS dichiara di poter usare la posizione anche ad app chiusa; dati di posizione, uso e diagnostica «non collegati all'identità»; dalla 1.1.1 avvisa quando il permesso di posizione è spento | App Store |
| Permessi Android | da verificare (APK) | – |

## Annunci a voce, Android Auto (punti 27, 33)

Da verificare (APK); app per bici.

## Cosa ne prende DriveNow

- Punto 12: il flusso va nei due sensi: l'app riceve il tempo al verde e manda l'arrivo
  previsto, così il semaforo può anticipare il verde (priorità condizionale).
- Punto 17: un avviso esplicito quando manca il permesso di posizione.
