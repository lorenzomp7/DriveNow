# Priotalker (Yunex Traffic) – scheda da fonti pubbliche

- Editore: Yunex Traffic; pacchetto `com.yunextraffic.priotalker` (Google Play, aggiornata il
  30 luglio 2025); per ora solo Android
- Data: 2026-11-24. **Fonti pubbliche, non l'APK**.

## Che cos'è

Un'app per **provare e collaudare** gli iVRI olandesi (impianti semaforici intelligenti), nata
nel partenariato Talking Traffic; usata nei collaudi in strada (iSAT) per controllare la
comunicazione tra impianto e utente. Gli account li gestisce NDW (dal 2025), su richiesta del
gestore della strada, con diritti di priorità per al massimo 3 mesi.
Fonti: [Google Play](https://play.google.com/store/apps/details?id=com.yunextraffic.priotalker),
[Yunex NL](https://nl.yunextraffic.com/nieuws/stagiairs-bij-yunex-traffic-aan-de-slag-met-uitdagende-projecten/),
[NDW](https://docs.ndw.nu/handleidingen/priotalker/), [CROW](https://www.crow.nl/Onderwerpen/landelijke-mobiliteitsstandaarden/landelijke-ivri-standaarden/protocollen-formulieren-stappenplannen-en-avg/),
[DTV](https://dtv.nl/producten-en-diensten/fabrieksafname-fat-en-inbedrijfstelling-sat-verkeersregelinstallaties/).

## Dati dei semafori (punti 2 e 12)

| Cosa | Trovato | Fonte |
|---|---|---|
| Da dove | piattaforma nazionale olandese UDAP (Urban Data Access Platform), con certificato iVRI del ministero | [LinkedIn Yunex](https://nl.linkedin.com/posts/yunextraffic_v2x-teamyunextraffic-certificate-activity-6985617298422185984-pIDN) |
| Cosa mostra | limiti di velocità statici e dinamici, configurazione delle corsie, divieti di sorpasso, stato dei semafori e **previsione della fase successiva** | Google Play |
| Verso il semaforo | richiesta di priorità agli iVRI che la gestiscono, nel ruolo di mezzo di soccorso, bus o camion | Google Play |
| Formato | da verificare (APK); gli iVRI usano i messaggi SPaT/MAP delle norme europee | – |

## Annunci a voce, posizione in background, Android Auto (punti 27, 17, 33)

Da verificare (APK). È uno strumento di collaudo, non un'app per il pubblico.

## Cosa ne prende DriveNow

- Punto 12: in Olanda i dati SPaT/MAP di ogni iVRI passano da una piattaforma unica (UDAP):
  un solo collegamento per tutte le città, con certificati e account.
- Punto 2: le previsioni arrivano per fase («fase successiva»), non come un ciclo fisso.
