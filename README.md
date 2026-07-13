# Apex — il tuo diario Garmin + piano che si aggiorna

Ogni sera GitHub scarica i dati Garmin, li fa valutare a Claude e aggiorna
un'app che tieni sulla home del telefono: calendario con lo storico, resoconto
del giorno + "domani", e una scheda "Piano" che evolve in base ai risultati.
(Facoltativo: puoi ricevere anche una notifica WhatsApp/email.)

---

## Setup (una volta sola, ~30 min al PC)

### 1. Crea il repository
- github.com → **New repository** → nome a piacere → **Public** *(vedi nota Privacy in fondo)* → Create.
- **Add file → Upload files** → trascina dentro tutta la cartella `garmin-coach`.

### 2. Chiave API di Claude
- **console.anthropic.com** → Settings → API Keys → crea una chiave (`sk-ant-...`).
- Serve un po' di credito. Costa pochi centesimi al giorno (una chiamata).

### 3. (Opzionale) WhatsApp — dal telefono, 2 min
- Su **callmebot.com/blog/free-api-whatsapp-messages/** leggi il numero del bot
  (cambia ogni tanto, per questo non lo scrivo qui) e salvalo nei contatti.
- Da WhatsApp mandagli: **I allow callmebot to send me messages**
- Ti risponde con la tua **APIKEY**. Tienila da parte.

### 4. (Opzionale) Email — con Gmail
- Verifica in 2 passaggi attiva → **myaccount.google.com/apppasswords** →
  crea una "password per app" (16 caratteri).

### 5. Metti i segreti su GitHub
Repo → **Settings → Secrets and variables → Actions → New repository secret**.

Obbligatori:

| Nome                | Valore                              |
|---------------------|-------------------------------------|
| `GARMIN_EMAIL`      | la tua email Garmin Connect         |
| `GARMIN_PASSWORD`   | la password Garmin Connect          |
| `ANTHROPIC_API_KEY` | la chiave `sk-ant-...`               |

Solo se vuoi WhatsApp: `WHATSAPP_PHONE` (es. `+393401234567`), `WHATSAPP_APIKEY`.
Solo se vuoi email: `SMTP_HOST` = `smtp.gmail.com`, `SMTP_PORT` = `587`,
`SMTP_USER` (tua Gmail), `SMTP_PASS` (password per app), `EMAIL_TO`.

> Metti solo i canali che vuoi. Quelli senza segreti vengono saltati.
> L'app funziona comunque: i messaggi sono un extra.

### 6. Accendi l'app (GitHub Pages)
Repo → **Settings → Pages** → *Source:* **Deploy from a branch** →
*Branch:* **main**, cartella **/docs** → **Save**.
Dopo ~1 min compare l'indirizzo (tipo `https://tuonome.github.io/nome-repo/`).

### 7. Mettila sulla home del telefono
- Apri quell'indirizzo nel browser del telefono.
- **iPhone:** tasto Condividi → *Aggiungi a Home*.
  **Android (Chrome):** menù ⋮ → *Installa app / Aggiungi a schermata Home*.
- Ora hai l'icona **Apex**. Si apre come un'app.

### 8. Prova subito
- Repo → **Actions** → "Report Garmin giornaliero" → **Run workflow**.
- Dopo 1-2 min riapri l'app: il giorno di oggi compare nel calendario (pallino colorato). Toccalo.
- Da lì gira da solo ogni sera alle 23.

### 9. Imposta la tua scheda di partenza
Apri `scheda.md` nel repo e scrivi obiettivo e settimana tipo.
Da lì in poi il piano si aggiorna da solo e lo vedi nella scheda **Piano** dell'app.

---

## Come leggere l'app
- **Diario:** in alto lo stato di oggi (anello prontezza + "domani"). Sotto il
  calendario: tocca ‹ › per cambiare mese, tocca un giorno col pallino per il resoconto.
  Verde = pronto a spingere · Ambra = moderato · Rosso = scarico/recupero.
- **Piano:** due colonne giorno per giorno — **Il mio** (che imposti tu) e
  **Coach** (la proposta di Claude). In azzurro i giorni dove il coach propone
  qualcosa di diverso. In alto il "carico proposto" per la settimana dopo.

## Modificare il piano dall'app (facoltativo)
Vuoi scrivere/aggiornare il tuo piano direttamente dall'app invece che dal file?
Serve un piccolo token GitHub (resta solo sul tuo telefono, non nel sito).

1. Vai su **github.com/settings/tokens** → *Fine-grained tokens* → **Generate new token**.
2. *Repository access* → **Only select repositories** → scegli questo repo.
3. *Permissions* → *Repository permissions* → **Contents: Read and write**. Genera e copia il token.
4. Nell'app, tocca l'**ingranaggio** in alto → incolla token, owner (il tuo nome utente)
   e nome repo → **Salva**.
5. Ora nella scheda **Piano** trovi **Modifica il mio piano**: cambi i giorni e fai **Salva**.
   Alla prossima analisi notturna il coach terrà conto del tuo piano aggiornato.

> Il token dà accesso in scrittura solo a questo repo. Se lo perdi o cambi telefono,
> puoi revocarlo su GitHub e crearne uno nuovo. Senza token l'app resta in sola lettura.

## Privacy (leggila)
Con GitHub gratis il repo dev'essere **pubblico** per pubblicare l'app. E anche
con un piano a pagamento, il **sito pubblicato è comunque raggiungibile da chi ha
il link**. Quindi i tuoi dati stanno a un indirizzo pubblico ma non indicizzato:
nessuno lo trova se non lo condividi. Per dati di allenamento di solito va bene.
Se vuoi blindarlo dietro login gratuito, si può con **Cloudflare Access** (passo
in più, chiedi pure). Nota: le password NON sono mai nel sito, restano dentro i
Secrets di GitHub.

## Se qualcosa non va
- **App vuota:** il primo giorno vero arriva dopo il primo "Run workflow" o dopo
  le 23. Prima vedi solo i dati demo.
- **Login Garmin fallito:** rifai il login nell'app Garmin dal telefono e riprova.
- **Modifiche non visibili:** l'app aggiorna i dati da sola; se serve, chiudi e
  riapri. Gli errori li vedi in **Actions**, cliccando l'esecuzione fallita.

## Cambiare l'orario
In `.github/workflows/daily.yml`, `cron: "0 21 * * *"` è in UTC
(= 23:00 ora italiana d'estate). Cambia il `21` per spostarlo.
