#!/usr/bin/env python3
"""
Ogni sera: scarica i dati Garmin, li fa valutare a Claude,
scrive i file per l'app (docs/data/) e, se configurato, manda WhatsApp/email.

L'app mostra il "Piano" a due colonne:
- il TUO piano (docs/data/mio_piano.json, che modifichi dall'app)
- la proposta del COACH (docs/data/plan.json, riscritta ogni notte da Claude)
Pensato per girare da solo su GitHub Actions.
"""

import os
import sys
import json
import smtplib
import urllib.parse
from datetime import date, timedelta
from email.mime.text import MIMEText

import requests
from garminconnect import Garmin
import anthropic

# --- Segreti obbligatori ---
GARMIN_EMAIL    = os.environ["GARMIN_EMAIL"]
GARMIN_PASSWORD = os.environ["GARMIN_PASSWORD"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]

# --- Canali opzionali ---
WHATSAPP_PHONE  = os.environ.get("WHATSAPP_PHONE")
WHATSAPP_APIKEY = os.environ.get("WHATSAPP_APIKEY")
SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
EMAIL_TO  = os.environ.get("EMAIL_TO")

MODEL = "claude-sonnet-5"          # analisi più profonde: "claude-opus-4-8"
DATA_DIR = os.path.join("docs", "data")
GIORNI = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]


# ---------- Garmin ----------
def safe(fn, *args, default=None):
    try:
        return fn(*args)
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


def compatta_attivita(attivita):
    out = []
    for a in attivita or []:
        out.append({
            "nome": a.get("activityName"),
            "tipo": (a.get("activityType") or {}).get("typeKey"),
            "data": a.get("startTimeLocal"),
            "distanza_km": round((a.get("distance") or 0) / 1000, 2),
            "durata_min": round((a.get("duration") or 0) / 60, 1),
            "dislivello_m": a.get("elevationGain"),
            "fc_media": a.get("averageHR"),
            "fc_max": a.get("maxHR"),
            "TE_aerobico": a.get("aerobicTrainingEffect"),
            "TE_anaerobico": a.get("anaerobicTrainingEffect"),
        })
    return out


def raccogli_dati():
    g = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    g.login()
    oggi = date.today()
    ieri = oggi - timedelta(days=1)
    sette = oggi - timedelta(days=7)
    return {
        "data": oggi.isoformat(),
        "riepilogo_giornata": safe(g.get_user_summary, oggi.isoformat()),
        "training_status":    safe(g.get_training_status, oggi.isoformat()),
        "training_readiness": safe(g.get_training_readiness, oggi.isoformat()),
        "hrv":                safe(g.get_hrv_data, ieri.isoformat()),
        "sonno":              safe(g.get_sleep_data, ieri.isoformat()),
        "vo2max":             safe(g.get_max_metrics, oggi.isoformat()),
        "attivita": compatta_attivita(
            safe(g.get_activities_by_date, sette.isoformat(), oggi.isoformat())
        ),
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
    carico = round(sum((a.get("distanza_km") or 0) for a in att), 1) if att else None
    ultima = None
    if att:
        a = att[0]
        testa = a.get("nome") or a.get("tipo") or "Attività"
        coda = []
        if a.get("distanza_km"): coda.append(f"{a['distanza_km']} km")
        if a.get("dislivello_m"): coda.append(f"{int(a['dislivello_m'])} m D+")
        ultima = f"{testa} – {', '.join(coda)}" if coda else testa
    m = {
        "prontezza": prontezza,
        "hrv": f"{int(hrv_ms)}ms" if hrv_ms else None,
        "fc_riposo": fc_rip,
        "sonno_h": sonno_h,
        "vo2max": vo2,
        "carico_7gg_km": carico,
        "ultima_attivita": ultima,
    }
    return {k: v for k, v in m.items() if v is not None}


def colore_effort(p):
    if p is None: return "gray"
    if p >= 70: return "green"
    if p >= 40: return "amber"
    return "red"


# ---------- Il mio piano (input) ----------
def leggi_mio_piano():
    p = os.path.join(DATA_DIR, "mio_piano.json")
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            pass
    testo = ""
    if os.path.exists("scheda.md"):
        testo = open("scheda.md", encoding="utf-8").read()
    return {"obiettivo": testo, "giorni": {}}


# ---------- Claude ----------
def valuta_con_claude(metriche, dati, mio):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt = f"""Sei il mio coach personale di mountain bike, specializzato in ENDURO e DOWNHILL.
Mi interessano soprattutto i tempi in discesa sui segmenti Strava, la tenuta fisica nelle discese lunghe e tecniche, la forza/esplosività e la gestione del recupero (le discese stancano molto anche se i km sono pochi). Il volume in km conta meno del carico e dell'intensità.

Ti do: le mie metriche Garmin di oggi, le attività degli ultimi 7 giorni, e IL MIO PIANO settimanale (giorno per giorno).
Analizza l'ultima settimana e proponi come aggiustare il piano e il carico della settimana successiva.

Rispondi SOLO con un oggetto JSON valido (niente testo fuori, niente ```), con questi campi:
- "domani": stringa breve, cosa fare domani (spingere/scarico/riposo) con 1 dettaglio pratico.
- "riepilogo": 2-3 frasi sullo stato di forma/recupero, italiano semplice.
- "punti": array di massimo 4 stringhe brevi sui trend.
- "piano": oggetto con:
    - "giorni": oggetto con ESATTAMENTE le chiavi {GIORNI} e per ognuna una stringa breve (l'allenamento consigliato per quel giorno).
    - "note": 1-2 frasi che spiegano cosa hai cambiato rispetto al mio piano e perché.
    - "carico_prossimo": 1 frase sul carico della settimana successiva (aumenta/mantieni/scarico).

Parti dal MIO piano e cambialo solo dove i dati lo giustificano. Scrivi conciso: faccio fatica a leggere testi lunghi.

METRICHE: {json.dumps(metriche, ensure_ascii=False)}
ATTIVITA_7GG: {json.dumps(dati.get("attivita"), ensure_ascii=False, default=str)}
MIO_PIANO: {json.dumps(mio, ensure_ascii=False)}
"""
    msg = client.messages.create(
        model=MODEL, max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    testo = "".join(b.text for b in msg.content if b.type == "text").strip()
    try:
        return json.loads(testo[testo.find("{"): testo.rfind("}") + 1])
    except Exception as e:
        print(f"  ! JSON di Claude non valido ({e}), uso fallback.", file=sys.stderr)
        return {"domani": "—", "riepilogo": testo[:500], "punti": [],
                "piano": {"giorni": mio.get("giorni", {}), "note": "", "carico_prossimo": ""}}


# ---------- Scrittura file per l'app ----------
def scrivi_dati(rep, metriche, giorno):
    os.makedirs(DATA_DIR, exist_ok=True)
    colore = colore_effort(metriche.get("prontezza"))

    day = {
        "data": giorno,
        "domani": rep.get("domani", ""),
        "riepilogo": rep.get("riepilogo", ""),
        "punti": rep.get("punti", []),
        "metriche": metriche,
    }
    json.dump(day, open(os.path.join(DATA_DIR, f"{giorno}.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)

    idx_path = os.path.join(DATA_DIR, "index.json")
    idx = {"giorni": {}}
    if os.path.exists(idx_path):
        try: idx = json.load(open(idx_path, encoding="utf-8"))
        except Exception: pass
    idx.setdefault("giorni", {})
    idx["giorni"][giorno] = {"color": colore, "prontezza": metriche.get("prontezza")}
    idx["ultimo_aggiornamento"] = giorno
    json.dump(idx, open(idx_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # Proposta del coach (NON tocca mio_piano.json)
    piano = rep.get("piano", {}) or {}
    plan = {
        "aggiornato": giorno,
        "giorni": piano.get("giorni", {}),
        "note": piano.get("note", ""),
        "carico_prossimo": piano.get("carico_prossimo", ""),
    }
    json.dump(plan, open(os.path.join(DATA_DIR, "plan.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"Dati scritti in {DATA_DIR}/ (pallino: {colore}).")


# ---------- Messaggi opzionali ----------
def testo_messaggio(rep, giorno):
    righe = [f"🚵 {giorno}", f"DOMANI: {rep.get('domani','—')}", "", rep.get("riepilogo", "")]
    for p in rep.get("punti", []):
        righe.append(f"• {p}")
    carico = get_in(rep, "piano", "carico_prossimo")
    if carico:
        righe += ["", f"Carico prossimo: {carico}"]
    return "\n".join(righe).strip()


def invia_whatsapp(testo):
    url = ("https://api.callmebot.com/whatsapp.php"
           f"?phone={urllib.parse.quote(WHATSAPP_PHONE)}"
           f"&apikey={urllib.parse.quote(WHATSAPP_APIKEY)}"
           f"&text={urllib.parse.quote(testo[:3500])}")
    r = requests.get(url, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"stato {r.status_code}: {r.text}")
    print("WhatsApp inviato.")


def invia_email(testo, giorno):
    e = MIMEText(testo, "plain", "utf-8")
    e["Subject"] = f"🚵 Report Garmin – {giorno}"
    e["From"] = SMTP_USER; e["To"] = EMAIL_TO
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls(); s.login(SMTP_USER, SMTP_PASS); s.send_message(e)
    print("Email inviata.")


def invia_messaggi(rep, giorno):
    testo = testo_messaggio(rep, giorno)
    if WHATSAPP_PHONE and WHATSAPP_APIKEY:
        try: invia_whatsapp(testo)
        except Exception as e: print(f"  ! WhatsApp fallito: {e}", file=sys.stderr)
    if SMTP_HOST and SMTP_USER and SMTP_PASS and EMAIL_TO:
        try: invia_email(testo, giorno)
        except Exception as e: print(f"  ! Email fallita: {e}", file=sys.stderr)


# ---------- Main ----------
def main():
    print("1) Scarico dati Garmin...")
    dati = raccogli_dati()
    metriche = estrai_metriche(dati)
    print("   metriche:", metriche)
    print("2) Leggo il mio piano...")
    mio = leggi_mio_piano()
    print("3) Valutazione di Claude...")
    rep = valuta_con_claude(metriche, dati, mio)
    print("4) Scrivo i dati per l'app...")
    scrivi_dati(rep, metriche, dati["data"])
    print("5) Messaggi (se configurati)...")
    invia_messaggi(rep, dati["data"])
    print("Fatto.")


if __name__ == "__main__":
    main()
