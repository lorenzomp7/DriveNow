# Procedure di sviluppo per DriveNow

DriveNow include sette procedure di [agent-skills](https://github.com/addyosmani/agent-skills):
specifiche, pianificazione, implementazione incrementale, test, revisione,
debugging e rilascio. Sono file di istruzioni per gli agenti che lavorano sulla
repo: non cambiano il comportamento dell’app e non richiedono chiavi API.

`AGENTS.md` indica quando leggere ciascuna procedura, i comandi di verifica e
i vincoli specifici di DriveNow. I client che riconoscono `.agents/skills/`
possono scoprire direttamente le procedure; gli altri agenti possono seguirne
i percorsi tramite `AGENTS.md`. Non vengono installati comandi slash di Claude
né skill personali nell’account ChatGPT.

Le copie sono integrali e includono i riferimenti condivisi, così i link
relativi `../../references/` restano validi. La licenza MIT è conservata in
`.agents/AGENT_SKILLS_LICENSE`. La versione upstream e le impronte dei file
sono registrate in `.agents/agent-skills.lock.json`; gli aggiornamenti sono
espliciti e revisionabili, senza download automatici durante l’avvio.

Esempi di utilizzo:

- Per una nuova funzione, l’agente consulta specifiche e pianificazione quando
  servono, implementa una parte verificabile e la controlla prima di proseguire.
- Per un errore, riproduce il problema, cerca la causa e aggiunge una verifica
  di regressione pertinente.
- Prima di dichiarare il lavoro completo, rivede il diff e riporta i controlli
  realmente eseguiti, distinguendoli da quelli soltanto configurati.

Le procedure si applicano allo stack Python/JavaScript esistente. Gli esempi
JavaScript nei riferimenti non impongono React, TypeScript o nuovi framework.
Le istruzioni dell’utente determinano ambito e autorizzazioni del lavoro.
