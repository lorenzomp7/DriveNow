# Consumi: accelerare, frenare, veleggiare

Due domande che stanno dietro a DriveNow, con i conti. I numeri sono stime
per un'auto a benzina di 1.300 kg (la stessa massa che il simulatore usa per
l'energia nei freni), non misure.

## Consuma di più accelerare o perdere energia?

Accelerare costa carburante, ma quell'energia non si perde: resta nella
velocità dell'auto. Si perde quando si frena, perché i freni la trasformano
in calore. Lo spreco quindi non è accelerare, è **accelerare e poi frenare**.

I conti, a 50 km/h (13,9 m/s):

- energia della velocità: ½ · 1.300 kg · (13,9 m/s)² ≈ **125 kJ**;
- il motore ne trasforma in movimento circa il 25%, quindi servono circa
  500 kJ di benzina, cioè circa **15 ml** (32 MJ al litro);
- a 50 km/h costanti un'auto consuma circa 5 l/100 km, 50 ml al km: quei
  15 ml bastano per circa **300 m**.

Ogni fermata seguita da una ripartenza da 50 km/h costa quindi più o meno
come fare 300 m in più. In città è la perdita principale: la resistenza
dell'aria a 50 km/h è piccola. Nella città demo del simulatore chi guida
senza DriveNow butta nei freni in media 94 kJ a viaggio, chi lo segue 21 kJ.

Tenere una velocità costante è quindi giusto, **ma solo se poi non si deve
frenare**. Se tenendo i 50 km/h si arriva al rosso, è la scelta peggiore: per
questo DriveNow non consiglia di tenere la velocità, ma la velocità con cui si
arriva al semaforo quando è verde.

Due precisazioni:

- **Come accelerare.** In un'auto a benzina conviene accelerare in modo
  deciso ma non brusco, cambiando marcia presto: il motore rende di più a giri
  bassi e carico medio-alto. Accelerare piano piano allunga il tempo passato
  in marce basse.
- **Ibride ed elettriche.** Recuperano in frenata una parte dell'energia, ma
  ne perdono comunque circa il 30–40%. Il ragionamento vale lo stesso, solo
  pesa meno.

## Semaforo: rallentare piano o tenere la velocità e fermarsi?

**Arrivare piano quando scatta il verde è nettamente meglio che tenere la
velocità e fermarsi.**

| | Tenere 50 km/h, fermarsi, ripartire | Rallentare presto, arrivare a 20 km/h col verde |
|---|---|---|
| Energia persa | 125 kJ nei freni | nessuna nei freni: la velocità persa ha fatto strada senza carburante |
| Attesa | motore al minimo, consuma | nessuna |
| Ripartenza | da 0 a 50 km/h: 125 kJ | da 20 a 50 km/h: circa 105 kJ |

Il guadagno principale non è la ripartenza un po' più leggera: è non aver
frenato. Il caso migliore è arrivare alla linea proprio quando scatta il
verde, alla velocità più alta possibile: è la fascia che calcola DriveNow.

### E la frizione?

Conviene il contrario di quello che si fa spesso:

| | Frizione premuta (o folle) | In marcia, piede alzato |
|---|---|---|
| Carburante | il motore resta al minimo: circa 0,6–1 l/h | **zero**: i motori a iniezione chiudono la benzina |
| Quanto rallenta l'auto | poco, 0,2–0,35 m/s²: scorre a lungo | di più, circa 0,7 m/s² (freno motore) |

Regola pratica:

1. **alza il piede presto e resta in marcia**: non consumi nulla;
2. premi la frizione solo alla fine, sotto i 15–20 km/h prima che il motore
   si spenga, o per fermarti;
3. la folle conviene solo per lunghi tratti di scorrimento, e toglie il freno
   motore: mai in discesa.

DriveNow assume proprio i 0,7 m/s² di chi alza il piede in marcia. Chi
veleggia in folle rallenta di meno: nel simulatore è uno dei profili d'auto
(`--vehicle-mix`, vedi "Auto che rallentano in modo diverso" nel README), e il
consiglio funziona anche così.
