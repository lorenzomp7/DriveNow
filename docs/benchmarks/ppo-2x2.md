Rete `2_2_intersections.net.xml`, domanda 216.0 veicoli/h per ingresso per 1000.0 s, simulazione fino a 1250.0 s, riscaldamento 200.0 s (contano i viaggi conclusi dopo), passo 0.2 s, semi 1, 2, 3, quota DriveNow 0 % (nessun consiglio) o 100 %. Agente: PPO del repository MagMueller, pesi sha256 6a234a23e975.

| Semafori | Regole | Consiglio | Viaggi | Tempo (s) | Fermate | Energia freni (kJ) | Δ tempo | Δ fermate | Δ energia | Verde promesso falso (s) |
|---|---|---|---|---|---|---|---|---|---|---|
| ciclo fisso | – | nessuno | 418.33 | 93.57 ± 0.97 | 1.37 ± 0.03 | 149.13 ± 3.04 |  |  |  | 0 |
| ciclo fisso | – | piano noto | 419.33 | 95.63 ± 1.5 | 0.13 ± 0.03 | 16.97 ± 1.96 | +2.2 % | -90.5 % | -88.6 % | 0 |
| PPO | come addestrato | nessuno | 420 | 106.3 ± 3.44 | 2.22 ± 0.08 | 181.93 ± 1.01 |  |  |  | 0 |
| PPO | come addestrato | solo certe | 422 | 106.63 ± 1.86 | 2.19 ± 0.08 | 127.67 ± 2.91 | +0.3 % | -1.2 % | -29.8 % | 0 |
| PPO | come addestrato | certe + probabili | 420 | 105.03 ± 1.12 | 2.13 ± 0.07 | 135.7 ± 3.22 | -1.2 % | -3.9 % | -25.4 % | 0 |
| PPO | verde 5-60 s | nessuno | 417.33 | 85.57 ± 2.38 | 1.32 ± 0.08 | 156.67 ± 7.46 |  |  |  | 0 |
| PPO | verde 5-60 s | solo certe | 418.67 | 93.57 ± 1.1 | 1.61 ± 0.03 | 108.5 ± 2.46 | +9.4 % | +22.3 % | -30.7 % | 0 |
| PPO | verde 5-60 s | certe + probabili | 418 | 86.47 ± 2.29 | 1.34 ± 0.08 | 138.17 ± 5.91 | +1.1 % | +1.8 % | -11.8 % | 0 |

Media ± deviazione standard tra i semi; Δ rispetto agli stessi semafori senza consiglio.
