#!/usr/bin/env python3
"""
Due modalita' (variabile d'ambiente MODE):

- MODE=daily  -> ogni giorno: scarica Garmin, scrive metriche+diario nell'app.
                 Nessuna chiamata a Claude (gratis). Nota "domani" a regole.
- MODE=weekly -> la domenica sera: Claude analizza la settimana e il tuo piano,
                 e propone il piano della settimana dopo (1 sola chiamata).
                 Se imposti PARTNER_DATA_URL, vede anche i dati del partner.

Pensato per girare su GitHub Actions.
"""

import os
import sys
import json
from datetime import date, timedelta
from email.mime.text import MIMEText
import smtplib
import urllib.parse

import requests
from garminconnect import Garmin
import anthropic

MODE = os.environ.get("MODE", "daily").strip().lower()

GARMIN_EMAIL    = os.environ["GARMIN_EMAIL"]
GARMIN_PASSWORD = os.environ["GARMIN_PASSWORD"]
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")     # serve solo in weekly
PARTNER_DATA_URL = os.environ.get("PARTNER_DATA_URL")       # opzionale (es. https://lei.github.io/repo/data)

WHATSAPP_PHONE  = os.environ.get("WHATSAPP_PHONE")
WHATSAPP_APIKEY = os.environ.get("WHATSAPP_APIKEY")
SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
EMAIL_TO  = os.environ.get("EMAIL_TO")

MODEL = "claude-sonnet-5"
DATA_DIR = os.path.join("docs", "data")
GIORNI = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]

# Prompt del coach: cambia SOLO questa parte tra bici e corsa.
COACH_INTRO = (
    "Sei il coach personale di mountain bike, specializzato in ENDURO e DOWNHILL. "
    "Conta piu' il carico/intensita' e la tenuta in discesa che i km. "
    "Interessano i tempi in discesa sui segmenti Strava e il recupero."
)


# ---------- Garmin ----------
def safe(fn, *a, default=None):
    try:
        return fn(*a)
    except Exception as e:
        print(f"  ! {getattr(fn,'__name__',fn)} non disponibile: {e}", file=sys.stderr)
        return default


def get_in(d, *keys, default=None):
    for k in keys:
        if isinstance(d, list):
            d = d[k] if isinstance(k, int) and len(d) > k else default
        elif isinstance(d, dict):
            d = d.get(k, default)
        else:
            return default
        if d is None:
            return default
    return d


def compatta_attivita(att):
    out = []
    for a in att or []:
        out.append({
            "nome": a.get("activityName"),
            "tipo": (a.get("activityType") or {}).get("typeKey"),
            "data": a.get("startTimeLocal"),
            "km": round((a.get("distance") or 0) / 1000, 2),
            "min": round((a.get("duration") or 0) / 60, 1),
            "dislivello_m": a.get("elevationGain"),
            "fc_media": a.get("averageHR"),
            "fc_max": a.get("maxHR"),
            "TE_aer": a.get("aerobicTrainingEffect"),
            "TE_ana": a.get("anaerobicTrainingEffect"),
        })
    return out


def raccogli_dati():
    g = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    g.login()
    oggi = date.today(); ieri = oggi - timedelta(days=1); sette = oggi - timedelta(days=7)
    return {
        "data": oggi.isoformat(),
        "riepilogo_giornata": safe(g.get_user_summary, oggi.isoformat()),
        "training_readiness": safe(g.get_training_readiness, oggi.isoformat()),
        "hrv":    safe(g.get_hrv_data, ieri.isoformat()),
        "sonno":  safe(g.get_sleep_data, ieri.isoformat()),
        "vo2max": safe(g.get_max_metrics, oggi.isoformat()),
        "attivita": compatta_attivita(safe(g.get_activities_by_date, sette.isoformat(), oggi.isoformat())),
    }


def estrai_metriche(d):
    tr = d.get("training_readiness")
    prontezza = get_in(tr, 0, "score") if isinstance(tr, list) else get_in(tr, "score")
    hrv_ms = get_in(d, "hrv", "hrvSummary", "lastNightAvg")
    fc_rip = get_in(d, "riepilogo_giornata", "restingHeartRate")
    sonno_s = get_in(d, "sonno", "dailySleepDTO", "sleepTimeSeconds")
    sonno_h = round(sonno_s / 3600, 1) if sonno_s else None
    vo2 = (get_in(d, "vo2max", 0, "generic", "vo2MaxValue")
           or get_in(d, "vo2max", 0, "cycling", "vo2MaxValue"))
    att = d.get("attivita") or []
    carico = round(sum((a.get("km") or 0) for a in att), 1) if att else None
    ultima = None
    if att:
        a = att[0]; testa = a.get("nome") or a.get("tipo") or "Attivita'"; coda = []
        if a.get("km"): coda.append(f"{a['km']} km")
        if a.get("dislivello_m"): coda.append(f"{int(a['dislivello_m'])} m D+")
        ultima = f"{testa} – {', '.join(coda)}" if coda else testa
    m = {"prontezza": prontezza, "hrv": f"{int(hrv_ms)}ms" if hrv_ms else None,
         "fc_riposo": fc_rip, "sonno_h": sonno_h, "vo2max": vo2,
         "carico_7gg_km": carico, "ultima_attivita": ultima}
    return {k: v for k, v in m.items() if v is not None}


def colore_effort(p):
    if p is None: return "gray"
    if p >= 70: return "green"
    if p >= 40: return "amber"
    return "red"


# ---------- Nota giornaliera (a regole, gratis) ----------
def nota_giornaliera(m):
    p = m.get("prontezza")
    if p is None:
        return "Nessun punteggio di prontezza oggi.", "Ascolta le sensazioni.", []
    if p >= 70:
        domani = "Giornata verde: puoi spingere, se in programma."
    elif p >= 40:
        domani = "Prontezza media: qualita' solo se ti senti bene, altrimenti fondo facile."
    else:
        domani = "Prontezza bassa: scarico o riposo, niente intensita'."
    parti = [f"Prontezza {p}"]
    if m.get("hrv"): parti.append(f"HRV {m['hrv']}")
    if m.get("fc_riposo"): parti.append(f"FC riposo {m['fc_riposo']}")
    if m.get("sonno_h"): parti.append(f"sonno {m['sonno_h']}h")
    riepilogo = ", ".join(parti) + "."
    return domani, riepilogo, []


# ---------- Scrittura diario ----------
def scrivi_giorno(m, giorno, domani, riepilogo, punti):
    os.makedirs(DATA_DIR, exist_ok=True)
    day = {"data": giorno, "domani": domani, "riepilogo": riepilogo, "punti": punti, "metriche": m}
    json.dump(day, open(os.path.join(DATA_DIR, f"{giorno}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    idx_path = os.path.join(DATA_DIR, "index.json"); idx = {"giorni": {}}
    if os.path.exists(idx_path):
        try: idx = json.load(open(idx_path, encoding="utf-8"))
        except Exception: pass
    idx.setdefault("giorni", {})
    idx["giorni"][giorno] = {"color": colore_effort(m.get("prontezza")), "prontezza": m.get("prontezza")}
    idx["ultimo_aggiornamento"] = giorno
    json.dump(idx, open(idx_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"Diario aggiornato ({giorno}).")


def leggi_mio_piano():
    p = os.path.join(DATA_DIR, "mio_piano.json")
    if os.path.exists(p):
        try: return json.load(open(p, encoding="utf-8"))
        except Exception: pass
    testo = open("scheda.md", encoding="utf-8").read() if os.path.exists("scheda.md") else ""
    return {"obiettivo": testo, "giorni": {}}


# ---------- Partner (opzionale) ----------
def leggi_partner():
    if not PARTNER_DATA_URL:
        return None
    base = PARTNER_DATA_URL.rstrip("/")
    out = {}
    try:
        out["piano"] = requests.get(f"{base}/mio_piano.json", timeout=20).json()
    except Exception as e:
        print(f"  ! partner mio_piano: {e}", file=sys.stderr)
    try:
        idx = requests.get(f"{base}/index.json", timeout=20).json()
        giorni = sorted((idx.get("giorni") or {}).keys())
        if giorni:
            ultimo = giorni[-1]
            out["ultimo_giorno"] = ultimo
            try:
                out["ultimo_report"] = requests.get(f"{base}/{ultimo}.json", timeout=20).json()
            except Exception:
                pass
    except Exception as e:
        print(f"  ! partner index: {e}", file=sys.stderr)
    return out or None


# ---------- Coach settimanale (Claude) ----------
def coach_settimana(m, dati, mio, partner):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    partner_txt = ""
    if partner:
        partner_txt = ("\nPARTNER (altro sport, per coordinare riposo e uscite di coppia nel weekend): "
                       + json.dumps(partner, ensure_ascii=False, default=str))
    mensile = (mio.get("tipo") == "mensile")
    obiettivo = (mio.get("obiettivo") or "").strip() or "(nessun obiettivo indicato)"
    note_atleta = (mio.get("note") or "").strip()
    if mensile:
        forma = ('- "piano": {{ "settimane": array di ESATTAMENTE 4 oggetti (S1..S4), '
                 'ognuno con le chiavi {GIORNI} (stringa breve per giorno), '
                 '"note": 1-2 frasi sui cambiamenti collegati all\'obiettivo, '
                 '"carico_prossimo": 1 frase sull\'andamento del mese }}').format(GIORNI=GIORNI)
        contesto = ("Il MIO piano e' MENSILE (4 settimane, campo 'settimane'). "
                    "Ragiona in PERIODIZZAZIONE sul mese: progressione del carico e scarico al momento giusto "
                    "verso l'obiettivo. Aggiorna tutte e 4 le settimane.")
    else:
        forma = ('- "piano": {{ "giorni": oggetto con ESATTAMENTE le chiavi {GIORNI} (stringa breve per giorno), '
                 '"note": 1-2 frasi sui cambiamenti collegati all\'obiettivo, '
                 '"carico_prossimo": 1 frase (aumenta/mantieni/scarico) }}').format(GIORNI=GIORNI)
        contesto = "Il MIO piano e' SETTIMANALE (campo 'giorni'): proponi il piano della SETTIMANA SUCCESSIVA."
    prompt = f"""{COACH_INTRO}

Il mio OBIETTIVO guida ogni scelta: {obiettivo}

E' domenica sera. Procedi cosi':
1) Confronta cosa avevo IN PROGRAMMA (MIO_PIANO) con cosa ho DAVVERO fatto secondo Garmin
   (ATTIVITA_7GG + METRICHE): cosa e' stato rispettato, saltato, o fatto con piu'/meno intensita'.
   Tieni conto anche delle NOTE_ATLETA (deviazioni che ho annotato: sostituzioni, salti, stanchezza).
2) Valuta forma e recupero (prontezza, HRV, carico, training effect).
3) Parti dal MIO piano e modificalo per avvicinarmi all'OBIETTIVO, rispettando il recupero.
   {contesto}

Rispondi SOLO con JSON valido (niente testo fuori, niente ```), campi:
- "riepilogo_settimana": 2-3 frasi: pianificato vs reale + stato di forma.
{forma}

Cambia solo dove i dati e l'obiettivo lo giustificano. Conciso: faccio fatica a leggere testi lunghi.

METRICHE_OGGI: {json.dumps(m, ensure_ascii=False)}
ATTIVITA_7GG: {json.dumps(dati.get("attivita"), ensure_ascii=False, default=str)}
NOTE_ATLETA: {note_atleta or '(nessuna)'}
MIO_PIANO: {json.dumps(mio, ensure_ascii=False)}{partner_txt}
"""
    msg = client.messages.create(model=MODEL, max_tokens=2500,
                                 messages=[{"role": "user", "content": prompt}])
    testo = "".join(b.text for b in msg.content if b.type == "text").strip()
    try:
        rep = json.loads(testo[testo.find("{"): testo.rfind("}") + 1])
        rep["_mensile"] = mensile
        return rep
    except Exception as e:
        print(f"  ! JSON Claude non valido ({e}).", file=sys.stderr)
        fallback = {"riepilogo_settimana": testo[:400], "_mensile": mensile,
                    "piano": {"note": "", "carico_prossimo": ""}}
        if mensile:
            fallback["piano"]["settimane"] = mio.get("settimane", [])
        else:
            fallback["piano"]["giorni"] = mio.get("giorni", {})
        return fallback


def scrivi_piano(rep, giorno):
    os.makedirs(DATA_DIR, exist_ok=True)
    piano = rep.get("piano", {}) or {}
    mensile = rep.get("_mensile", False)
    plan = {"aggiornato": giorno,
            "tipo": "mensile" if mensile else "settimanale",
            "note": piano.get("note", ""),
            "carico_prossimo": piano.get("carico_prossimo", ""),
            "riepilogo_settimana": rep.get("riepilogo_settimana", "")}
    if mensile:
        plan["settimane"] = piano.get("settimane", [])
    else:
        plan["giorni"] = piano.get("giorni", {})
    json.dump(plan, open(os.path.join(DATA_DIR, "plan.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("Piano del coach aggiornato.")


# ---------- Messaggi ----------
def invia_whatsapp(t):
    url = ("https://api.callmebot.com/whatsapp.php"
           f"?phone={urllib.parse.quote(WHATSAPP_PHONE)}&apikey={urllib.parse.quote(WHATSAPP_APIKEY)}"
           f"&text={urllib.parse.quote(t[:3500])}")
    r = requests.get(url, timeout=30)
    if r.status_code >= 400: raise RuntimeError(f"stato {r.status_code}")
    print("WhatsApp inviato.")


def invia_email(t, giorno):
    e = MIMEText(t, "plain", "utf-8"); e["Subject"] = f"🚵 Coach settimanale – {giorno}"
    e["From"] = SMTP_USER; e["To"] = EMAIL_TO
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls(); s.login(SMTP_USER, SMTP_PASS); s.send_message(e)
    print("Email inviata.")


def invia_messaggi(rep, giorno):
    p = rep.get("piano", {}) or {}
    t = f"🚵 Coach settimana ({giorno})\n\n{rep.get('riepilogo_settimana','')}"
    if p.get("carico_prossimo"): t += f"\n\nCarico prossimo: {p['carico_prossimo']}"
    if p.get("note"): t += f"\n{p['note']}"
    if WHATSAPP_PHONE and WHATSAPP_APIKEY:
        try: invia_whatsapp(t)
        except Exception as e: print(f"  ! WhatsApp: {e}", file=sys.stderr)
    if SMTP_HOST and SMTP_USER and SMTP_PASS and EMAIL_TO:
        try: invia_email(t, giorno)
        except Exception as e: print(f"  ! Email: {e}", file=sys.stderr)


# ---------- Main ----------
def main():
    print(f"MODE = {MODE}")
    print("Scarico dati Garmin...")
    dati = raccogli_dati(); m = estrai_metriche(dati)
    print("  metriche:", m)

    if MODE == "weekly":
        if not ANTHROPIC_API_KEY:
            sys.exit("MODE=weekly ma manca ANTHROPIC_API_KEY.")
        mio = leggi_mio_piano()
        partner = leggi_partner()
        print("Coach settimanale (Claude)..." + (" con partner" if partner else ""))
        rep = coach_settimana(m, dati, mio, partner)
        scrivi_piano(rep, dati["data"])
        invia_messaggi(rep, dati["data"])
    else:
        domani, riepilogo, punti = nota_giornaliera(m)
        scrivi_giorno(m, dati["data"], domani, riepilogo, punti)
    print("Fatto.")


if __name__ == "__main__":
    main()
