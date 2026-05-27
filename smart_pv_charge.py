"""
Ueberschussladen – SMA Sunny Hybrid + go-e Gemini Flex + BYD HVS
=================================================================
Platzierung:  /config/pyscript/smart_pv_charge.py
Version:      v4.2
pyscript:     >= v1.7.0
Firmware:     go-e Gemini Flex >= 59.4

ARCHITEKTUR – PASSIVER WERTE-LIEFERANT:
  Der go-e verwaltet sich selbst (ECO-Modus, Phasenwechsel,
  Phasenumschaltverzögerung, Zielwert Netz — alles in der go-e App).
  Dieses Skript liefert aufbereitete pGrid-Werte damit der go-e
  den echten PV-Überschuss sieht — und greift beim SMA AC-Limit ein.

  Das Skript setzt KEIN frc, KEIN lmo, KEIN force_state.
  Zielwert Netz (pgt) wird vom Skript via HA-Helfer (Schieberegler) gesetzt.

KERNFORMEL (immer):
  pGrid_send = p_grid_real + bat_disch_w - bat_chg_w

  + bat_disch_w → BYD entlädt: Zähler zeigt weniger Bezug als real,
                  go-e würde auf Kosten der BYD laden ohne es zu wissen.
  - bat_chg_w  → BYD lädt DC: Zähler sieht es nicht,
                  go-e muss korrigierten Überschuss sehen.

  Beispiel: PV=4000W, BYD entlädt 1000W, Charger=4500W
    Zähler:     4000 + 1000 - 4500 = -500W (Einspeisung)
    pGrid_send: -500 + 1000 - 0 = +500W → go-e sieht echten Bedarf

SMA AC-LIMIT:
  SMA Sunny Hybrid liefert max SMA_MAX_AC_W AC (Standard: 9800W bei 10kWp).
  Überschuss darüber geht direkt DC in die BYD (unsichtbar für Zähler).
  Wenn go-e + Haus das AC-Limit überschreiten → Netzbezug trotz PV-Überschuss.

  Der go-e hält intern pgt Abstand (Zielwert Netz, per Schieberegler, Standard -200W).
  Schwelle im Skript bleibt SMA_MAX_AC_W, go-e macht die letzten 200W selbst.

  haus_w       = max(100W, pv_w + bat_disch_w - bat_chg_w - charger_w + p_grid_real)
  go_e_max_w   = SMA_MAX_AC_W - haus_w
  sma_am_limit = charger_w >= go_e_max_w

  Wenn Limit aktiv:
    go_e_max_sicher = max(go_e_max_w, phasen_min_w)
    pGrid_send = charger_w - go_e_max_sicher + bat_chg_w

  phasen_min_w: fester Wert 1000W (1P) / 3000W (3P) als Schutz
  Phasenzahl:   aus go-e Current-Sensoren (L1/L2/L3 > 1A)

ANSTECK-SPERRZEIT:
  Innerhalb von ANSTECK_SPERRZEIT_S (60s) nach Anstecken:
    - max_amp pauschal auf MAX_AMP_3P (10A) begrenzt
    - psm bleibt auf dem beim Anstecken gesetzten Wert (1 oder 2)
  Nach Ablauf:
    - max_amp Freigabe auf MAX_AMP (16A)
    - psm=0 (Auto) → go-e entscheidet selbst mit App-Haltezeit (10min)
  NUR IM ECO-MODUS. Im Basic-Modus: psm wird NIEMALS vom Skript gesetzt.

PHASENWAHL BEIM ANSTECKEN (nur im ECO-Modus):
  Skript berechnet beim Anstecken den 5-Minuten-Durchschnitt
  von p_grid_real (Ringpuffer, 60 Werte à 5s) und vergleicht mit dem
  fahrzeugspezifischen Schwellenwert.

  Logik:
    avg_grid_5min <= schwelle_3p → 3P (psm=2): genug Überschuss für 3P
    avg_grid_5min >  schwelle_3p → 1P (psm=1): zu wenig, sanft starten

  Schwellenwerte (inkl. 200W pgt-Puffer):
    MG4:    schwelle_3p = -3800W  (6A × 3 × 230V ≈ 3600W + 200W)
    Twingo: schwelle_3p = -4000W  (8A × 3 × 230V ≈ 3800W + 200W)

  Nach ANSTECK_SPERRZEIT_S → psm=0: go-e übernimmt mit App-Haltezeit.

  Im Basic-Modus: psm wird weder beim Anstecken noch nach Sperrzeit
  gesetzt. Der Nutzer steuert psm manuell — das Skript respektiert das.

FAHRZEUGPROFILE:
  input_select.wallbox_fahrzeug steuert welches Profil aktiv ist.
  Jedes Profil enthält:
    mca        → Mindeststrom in Ampere (HTTP API v2)
    schwelle_3p → Überschuss-Schwelle für 3P-Wahl beim Anstecken (W, negativ)

ZIELWERT NETZ (pgt):
  input_number.wallbox_zielwert_netz (Schieberegler, -500W bis -50W, Schritt 50W).
  Steuert den API-Parameter pgt (PV Grid Target) direkt am go-e.
  Standard: -200W. Nur bei echtem Wechsel gesendet.

RINGPUFFER (p_grid_real):
  60 Werte à 5s = 5 Minuten gleitender Durchschnitt.
  Wird in jedem Zyklus aktualisiert, unabhängig vom Ladezustand.
  Beim Anstecken: Durchschnitt der vorhandenen Werte (min. 1 Wert).

SIGN-KONVENTION (go-e API v2):
  pGrid  < 0 → Einspeisung / Ueberschuss   pGrid > 0 → Netzbezug
  pAkku  < 0 → BYD laedt (Senke)           pAkku > 0 → BYD entlaedt (Quelle)
  pPv    > 0 → PV produziert
  psm    0   → Auto   1 → 1P erzwingen   2 → 3P erzwingen

SENSOREN (SMA Sunny Hybrid):
  SENSOR_GRID_ABSORBED: Netzbezug in W (>=0)
  SENSOR_GRID_SUPPLIED: Netzeinspeisung in W (>=0)
  p_grid_real = absorbed - supplied  (positiv=Bezug, negativ=Einspeisung)
  SENSOR_BAT_CHARGE:    BYD-Ladeleistung in W (>=0)
  SENSOR_BAT_DISCHARGE: BYD-Entladeleistung in W (>=0)

BEKANNTE go-e FIRMWARE-EIGENHEITEN:
  Status "Fallback (guenstiger Strompreis)":
    Bedeutet NICHT Awattar/Strompreis-Fallback.
    Bedeutet: zu wenig PV-Ueberschuss, go-e wartet auf mehr Leistung.

VORAUSSETZUNGEN (einmalig in go-e App):
  lmo = 4 (ECO-Modus)               <- muss manuell gesetzt sein
  fup = true                         <- PV-Ueberschuss-Modus aktiv
  acp = true                         <- Cloud-Daten akzeptieren
  awe = false                        <- kein Awattar-Fallback
  psm = 0 (Auto)                     <- Grundzustand
  Preisgrenze = -99ct                <- verhindert Awattar-Fallback
  Phasenumschaltverzögerung = 10min  <- verhindert Flackern
  go-e Controller = deaktiviert      <- kein Konflikt mit Script
  force_state = Neutral              <- NIEMALS aendern
  mca (Mindeststrom)                 <- wird vom Skript per Fahrzeugprofil gesetzt
  pgt (Zielwert Netz)                <- wird vom Skript per Schieberegler gesetzt
=================================================================
"""

import urllib.parse
import time

# ══════════════════════════════════════════════════════════════════
# KONFIGURATION – HIER ANPASSEN
# ══════════════════════════════════════════════════════════════════

# IP-Adresse der go-e Wallbox im lokalen Netz
GOE_IP               = "192.168.178.98"

# ── SMA-Wechselrichter-Limit ──────────────────────────────────────
# Maximale AC-Ausgangsleistung des Wechselrichters in Watt.
# Richtwert: ~98% der Nennleistung (Leitungsverluste etc.)
#   10 kWp Anlage → 9800W  (Standard)
#    7 kWp Anlage → 6860W
#    5 kWp Anlage → 4900W
# Wert anpassen auf die eigene Anlage!
SMA_MAX_AC_W         = 9800

# ── Ladeströme ────────────────────────────────────────────────────
MAX_AMP              = 16      # Maximaler Ladestrom nach Ansteck-Sperrzeit (A)
MAX_AMP_3P           = 10      # Maximaler Ladestrom während Ansteck-Sperrzeit (A)

# ── Timing ────────────────────────────────────────────────────────
IDS_INTERVAL_S       = 5       # Sendeintervall pGrid → go-e (Sekunden)
ANSTECK_SPERRZEIT_S  = 60      # Sperrzeit nach Anstecken (Sekunden)
PUFFER_GROESSE       = 60      # Ringpuffer-Größe (60 × 5s = 5 Minuten)

# ── Phasenerkennung ───────────────────────────────────────────────
PHASE_ACTIVE_THRESHOLD_A = 1.0   # Stromstärke ab der eine Phase als aktiv gilt (A)
PHASEN_MIN_W_1P      = 1000      # Mindestleistung 1-phasig (W) für SMA-Limiter-Schutz
PHASEN_MIN_W_3P      = 3000      # Mindestleistung 3-phasig (W) für SMA-Limiter-Schutz

# ── Plausibilitätsgrenzen (Sensorwerte werden auf diese Maximalwerte begrenzt) ──
PLAUS_PV_MAX         = 15000   # Maximale PV-Leistung (W) – größer als eigene Anlage wählen
PLAUS_BYD_MAX        = 7000    # Maximale BYD-Lade-/Entladeleistung (W)
PLAUS_CHARGER_MAX    = 11000   # Maximale Wallbox-Leistung (W)
PLAUS_GRID_MAX       = 9500    # Maximale Netzleistung (W)

# ── Zielwert Netz Fallback ────────────────────────────────────────
PGT_FALLBACK_W       = -200    # Zielwert Netz falls Schieberegler nicht verfügbar (W)

# ══════════════════════════════════════════════════════════════════
# ENTITÄTEN – MÜSSEN ZUR HA-KONFIGURATION PASSEN
# ══════════════════════════════════════════════════════════════════
# Entitäts-IDs aus der configuration.yaml (helpers.yaml).
# Die Seriennummer im SMA-Sensor (sn_XXXXXXXXX) und die
# go-e Seriennummer (XXXXXX) müssen angepasst werden.

# SMA Sunny Hybrid Sensoren
# Die eigene SMA-Seriennummer (10-stellig) statt XXXXXXXXXX eintragen.
# Zu finden in HA unter: Einstellungen → Geräte & Dienste → SMA → Gerät öffnen
SENSOR_PV_POWER      = "sensor.sn_XXXXXXXXXX_pv_power"
SENSOR_GRID_ABSORBED = "sensor.sn_XXXXXXXXXX_metering_power_absorbed"
SENSOR_GRID_SUPPLIED = "sensor.sn_XXXXXXXXXX_metering_power_supplied"
SENSOR_BAT_CHARGE    = "sensor.sn_XXXXXXXXXX_battery_power_charge_total"
SENSOR_BAT_DISCHARGE = "sensor.sn_XXXXXXXXXX_battery_power_discharge_total"

# go-e Wallbox Sensoren (via MQTT)
# Die eigene go-e Seriennummer (6-stellig) statt XXXXXX eintragen.
# Zu finden in HA unter: Einstellungen → Geräte & Dienste → go-e → Gerät öffnen
SENSOR_CHARGER_POWER = "sensor.go_echarger_XXXXXX_power_total"
SENSOR_CAR_STATE     = "sensor.go_echarger_XXXXXX_car_state"
SENSOR_CURRENT_L1    = "sensor.go_echarger_XXXXXX_current_l1"
SENSOR_CURRENT_L2    = "sensor.go_echarger_XXXXXX_current_l2"
SENSOR_CURRENT_L3    = "sensor.go_echarger_XXXXXX_current_l3"

# go-e Wallbox Steuerung (via MQTT)
NUMBER_MAX_AMP       = "number.go_echarger_XXXXXX_set_max_ampere_limit"
SELECT_LOGIC_MODE    = "select.go_echarger_XXXXXX_logic_mode"
# Mögliche Werte: "Eco" = ECO-Modus (Skript aktiv), "Default" = Basic, "NextTrip"

# HA-Helfer (werden in der configuration.yaml / helpers.yaml angelegt)
HELPER_FAHRZEUG      = "input_select.wallbox_fahrzeug"
HELPER_ZIELWERT      = "input_number.wallbox_zielwert_netz"

# ══════════════════════════════════════════════════════════════════
# FAHRZEUGPROFILE – EIGENE FAHRZEUGE EINTRAGEN
# ══════════════════════════════════════════════════════════════════
# mca        → Mindeststrom in Ampere (Fahrzeug-Minimum, aus dem Handbuch)
# schwelle_3p → 5-min-Durchschnitt p_grid_real muss <= dieser Wert sein
#               damit beim Anstecken 3P gewählt wird (inkl. 200W pgt-Puffer)
#
# Formel für eigene Fahrzeuge:
#   schwelle_3p = -(mca × 3 × 230) - 200
#   Beispiel 6A: -(6 × 3 × 230) - 200 = -4340W  → abrunden auf -4300W
#
# Hinweis: Fahrzeugname muss exakt mit dem input_select in HA übereinstimmen.
FAHRZEUG_PROFILE = {
    "MG4":    {"mca": 6, "schwelle_3p": -3800},
    "Twingo": {"mca": 8, "schwelle_3p": -4000},
}
# Fallback wenn kein Fahrzeug gewählt oder unbekanntes Fahrzeug
FAHRZEUG_FALLBACK    = {"mca": 8, "schwelle_3p": -4000}

# ══════════════════════════════════════════════════════════════════
# GLOBALER ZUSTAND – NICHT ÄNDERN
# ══════════════════════════════════════════════════════════════════

_max_amp_gesetzt            = MAX_AMP
_min_amp_gesetzt            = -1
_pgt_gesetzt                = 0
_psm_gesetzt                = -1
_ansteck_zeitpunkt          = 0.0
_sperrzeit_ablauf_behandelt = False
_grid_puffer                = []

# ══════════════════════════════════════════════════════════════════
# HILFSFUNKTIONEN
# ══════════════════════════════════════════════════════════════════

def get_float(entity_id, default=0.0):
    try:
        val = state.get(entity_id)
        if val in (None, "unknown", "unavailable"):
            return default
        return float(val)
    except (TypeError, ValueError):
        log.warning(f"[Wallbox] Kann {entity_id} nicht lesen → {default}")
        return default

def get_str(entity_id, default="unknown"):
    try:
        return str(state.get(entity_id))
    except Exception:
        return default

def clamp(val, lo, hi):
    if val < lo: return lo
    if val > hi: return hi
    return val

def detect_active_phases(charger_w):
    """Phasenzahl aus go-e Current-Sensoren. Nur für SMA-Limiter-Schutz."""
    if charger_w < 200:
        return 1, "kein Laden → Fallback 1P"
    i_l1 = get_float(SENSOR_CURRENT_L1, default=-1.0)
    i_l2 = get_float(SENSOR_CURRENT_L2, default=-1.0)
    i_l3 = get_float(SENSOR_CURRENT_L3, default=-1.0)
    if i_l1 < 0 or i_l2 < 0 or i_l3 < 0:
        return 1, f"Sensor unavailable (L1={i_l1} L2={i_l2} L3={i_l3}) → Fallback 1P"
    active = 0
    for i in [i_l1, i_l2, i_l3]:
        if i > PHASE_ACTIVE_THRESHOLD_A:
            active += 1
    if active == 0:
        return 1, "Uebergangszustand → Fallback 1P"
    return active, f"L1={i_l1:.1f}A L2={i_l2:.1f}A L3={i_l3:.1f}A → {active}P"

def berechne_avg_grid():
    """
    5-Minuten-Durchschnitt von p_grid_real aus dem Ringpuffer.
    Gibt (avg, anzahl_werte) zurück. Fallback 0.0 wenn Puffer leer.
    """
    if not _grid_puffer:
        return 0.0, 0
    return sum(_grid_puffer) / len(_grid_puffer), len(_grid_puffer)

def set_max_amp(amp):
    """
    Maximalstrom setzen. Während Sperrzeit: pauschal MAX_AMP_3P.
    Nach Sperrzeit: volle Freigabe auf amp.
    """
    global _max_amp_gesetzt
    seit_anstecken = time.time() - _ansteck_zeitpunkt
    in_sperrzeit   = seit_anstecken < ANSTECK_SPERRZEIT_S
    ziel = MAX_AMP_3P if in_sperrzeit else amp
    if _max_amp_gesetzt == ziel:
        return
    try:
        service.call("number", "set_value",
            entity_id=NUMBER_MAX_AMP,
            value=ziel)
        _max_amp_gesetzt = ziel
        verbleibend = max(0, ANSTECK_SPERRZEIT_S - seit_anstecken)
        info = f" [Sperrzeit noch {verbleibend:.0f}s → max {MAX_AMP_3P}A]" if in_sperrzeit else ""
        log.info(f"[Wallbox] set_max_amp → {ziel}A{info}")
    except Exception as e:
        log.warning(f"[Wallbox] set_max_amp Fehler: {e}")

def set_min_amp(amp):
    """Mindeststrom (mca) via HTTP API v2."""
    try:
        _do_http_get(f"http://{GOE_IP}/api/set?mca={amp}")
        log.info(f"[Wallbox] set_min_amp → {amp}A (mca gesetzt)")
    except Exception as e:
        log.warning(f"[Wallbox] set_min_amp Fehler: {e}")

def set_pgt(watt):
    """Zielwert Netz (pgt) via HTTP API v2."""
    try:
        _do_http_get(f"http://{GOE_IP}/api/set?pgt={int(watt)}")
        log.info(f"[Wallbox] set_pgt → {int(watt)}W")
    except Exception as e:
        log.warning(f"[Wallbox] set_pgt Fehler: {e}")

def set_psm(modus):
    """
    Phasenmodus (psm) via HTTP API v2.
    0 = Auto, 1 = 1P erzwingen, 2 = 3P erzwingen.
    Nur bei echtem Wechsel gesendet.
    ACHTUNG: Nur aus Eco-Modus-Pfaden aufrufen — nie im Basic-Modus.
    """
    global _psm_gesetzt
    if _psm_gesetzt == modus:
        return
    try:
        _do_http_get(f"http://{GOE_IP}/api/set?psm={modus}")
        _psm_gesetzt = modus
        namen = {0: "Auto", 1: "1P erzwingen", 2: "3P erzwingen"}
        log.info(f"[Wallbox] set_psm → {modus} ({namen.get(modus, '?')})")
    except Exception as e:
        log.warning(f"[Wallbox] set_psm Fehler: {e}")

@pyscript_executor
def _do_http_get(url):
    import urllib.request
    req = urllib.request.Request(url)
    req.add_header("Connection", "close")
    with urllib.request.urlopen(req, timeout=3) as resp:
        return resp.read()

def safe_pv_data(p_grid_send, p_pv, p_akku=0):
    ids_val = '{"pGrid":' + f"{p_grid_send:.0f}" + ',"pPv":' + f"{p_pv:.0f}" + ',"pAkku":' + f"{p_akku:.0f}" + '}'
    url = f"http://{GOE_IP}/api/set?ids={urllib.parse.quote(ids_val)}"
    try:
        _do_http_get(url)
    except Exception as e:
        log.warning(f"[Wallbox] HTTP-Fehler beim Senden: {e}")

# ══════════════════════════════════════════════════════════════════
# HAUPTSCHLEIFE
# ══════════════════════════════════════════════════════════════════

@time_trigger(f"period(now, {IDS_INTERVAL_S}s)")
def smart_charge_loop(**kwargs):
    global _max_amp_gesetzt, _min_amp_gesetzt, _pgt_gesetzt
    global _grid_puffer, _sperrzeit_ablauf_behandelt

    # ── 0) Sendebedingung ────────────────────────────────────────
    car_state  = get_str(SENSOR_CAR_STATE)
    logic_mode = get_str(SELECT_LOGIC_MODE)
    senden     = car_state in ("Charging", "WaitCar", "Complete")

    # ── 0b) Fahrzeugprofil ───────────────────────────────────────
    fahrzeug    = get_str(HELPER_FAHRZEUG)
    profil      = FAHRZEUG_PROFILE.get(fahrzeug, FAHRZEUG_FALLBACK)
    min_amp_neu = profil["mca"]

    # ── 0c) Mindeststrom nur bei Wechsel senden ──────────────────
    if _min_amp_gesetzt != min_amp_neu:
        set_min_amp(min_amp_neu)
        _min_amp_gesetzt = min_amp_neu

    # ── 0d) Zielwert Netz (pgt) → nur bei Wechsel ───────────────
    try:
        pgt_neu = int(float(get_float(HELPER_ZIELWERT, default=float(PGT_FALLBACK_W))))
    except (TypeError, ValueError):
        pgt_neu = PGT_FALLBACK_W
    pgt_neu = min(pgt_neu, -50)
    if _pgt_gesetzt != pgt_neu:
        set_pgt(pgt_neu)
        _pgt_gesetzt = pgt_neu

    # ── 1) Sensoren lesen ────────────────────────────────────────
    pv_w        = clamp(get_float(SENSOR_PV_POWER),      0.0, PLAUS_PV_MAX)
    grid_abs_w  = clamp(get_float(SENSOR_GRID_ABSORBED), 0.0, PLAUS_GRID_MAX)
    grid_sup_w  = clamp(get_float(SENSOR_GRID_SUPPLIED), 0.0, PLAUS_GRID_MAX)
    bat_chg_w   = clamp(get_float(SENSOR_BAT_CHARGE),    0.0, PLAUS_BYD_MAX)
    bat_disch_w = clamp(get_float(SENSOR_BAT_DISCHARGE), 0.0, PLAUS_BYD_MAX)

    if bat_chg_w > 0 and bat_disch_w > 0:
        if bat_chg_w >= bat_disch_w:
            bat_disch_w = 0.0
        else:
            bat_chg_w = 0.0

    charger_w  = clamp(get_float(SENSOR_CHARGER_POWER), 0.0, PLAUS_CHARGER_MAX)

    # ── 2) Grundwerte ────────────────────────────────────────────
    p_grid_real = grid_abs_w - grid_sup_w

    # ── 2b) Ringpuffer aktualisieren (immer, unabhängig vom Ladezustand)
    _grid_puffer.append(p_grid_real)
    if len(_grid_puffer) > PUFFER_GROESSE:
        _grid_puffer.pop(0)

    # ── 3) Phasenerkennung (nur fuer SMA-Limiter-Schutz) ────────
    active_phases, phase_info = detect_active_phases(charger_w)
    phasen_min_w = PHASEN_MIN_W_1P if active_phases == 1 else PHASEN_MIN_W_3P

    # ── 4) Kernformel ────────────────────────────────────────────
    p_grid_send = p_grid_real + bat_disch_w - bat_chg_w

    # ── 5) SMA-Limiter ───────────────────────────────────────────
    haus_w       = max(100.0, pv_w + bat_disch_w - bat_chg_w - charger_w + p_grid_real)
    go_e_max_w   = max(0.0, SMA_MAX_AC_W - haus_w)
    sma_am_limit = charger_w >= go_e_max_w

    if sma_am_limit:
        go_e_max_sicher = max(go_e_max_w, float(phasen_min_w))
        p_grid_send     = charger_w - go_e_max_sicher + bat_chg_w

    # ── 5b) Sperrzeit-Ablauf: psm → Auto (einmalig, NUR im Eco-Modus) ──
    seit_anstecken = time.time() - _ansteck_zeitpunkt
    in_sperrzeit   = seit_anstecken < ANSTECK_SPERRZEIT_S

    if (not in_sperrzeit
            and not _sperrzeit_ablauf_behandelt
            and _ansteck_zeitpunkt > 0):
        if logic_mode == "Eco":
            set_psm(0)
            log.info("[Wallbox] Sperrzeit abgelaufen → psm=0 (Auto), go-e übernimmt Phasenwahl")
        else:
            log.info(
                f"[Wallbox] Sperrzeit abgelaufen → psm NICHT zurückgesetzt "
                f"[Basic: {logic_mode}], Nutzer behält manuelle Phasenwahl"
            )
        _sperrzeit_ablauf_behandelt = True

    # ── 6) Moduswahl ─────────────────────────────────────────────
    modus_info = ""

    if logic_mode != "Eco":
        if _max_amp_gesetzt != MAX_AMP:
            _max_amp_gesetzt = 0
            set_max_amp(MAX_AMP)
            log.info("[Wallbox] Basic-Modus → max_amp freigegeben")
        modus_info = f" [Basic: {logic_mode}]"
    else:
        set_max_amp(MAX_AMP)

    # ── 7) Senden ────────────────────────────────────────────────
    if senden:
        safe_pv_data(p_grid_send, pv_w, 0)

    # ── 8) Log ───────────────────────────────────────────────────
    avg_grid, puffer_n = berechne_avg_grid()
    sperrzeit_log = f" [Sperrzeit {seit_anstecken:.0f}s/{ANSTECK_SPERRZEIT_S}s]" if in_sperrzeit else ""

    log.info(
        f"[Wallbox] V4.2 | "
        f"send={p_grid_send:+.0f}W echt={p_grid_real:+.0f}W avg={avg_grid:+.0f}W/{puffer_n} "
        f"byd+{bat_chg_w:.0f}/-{bat_disch_w:.0f}W pv={pv_w:.0f}W | "
        f"car={charger_w:.0f}W {active_phases}P max={MAX_AMP_3P if in_sperrzeit else MAX_AMP}A "
        f"haus={haus_w:.0f}W{' [SMA-LIMIT]' if sma_am_limit else ''} | "
        f"{fahrzeug} pgt={pgt_neu}W psm={_psm_gesetzt} | "
        f"{car_state}"
        + ("" if senden else " [kein Send]")
        + modus_info
        + sperrzeit_log
    )

# ══════════════════════════════════════════════════════════════════
# TRIGGER: Statuszustandsaenderungen
# ══════════════════════════════════════════════════════════════════

@state_trigger(f"{SENSOR_CAR_STATE}")
def on_car_state_change(**kwargs):
    global _max_amp_gesetzt, _ansteck_zeitpunkt
    global _sperrzeit_ablauf_behandelt, _psm_gesetzt

    val        = kwargs.get("value", "")
    old_val    = kwargs.get("old_value", "")
    logic_mode = get_str(SELECT_LOGIC_MODE)

    if val in ("Charging", "WaitCar"):
        # Nur bei echtem Anstecken reagieren (vorher Idle/unknown).
        # Wechsel Charging↔WaitCar↔Complete während der Ladung ignorieren.
        if old_val in ("Charging", "WaitCar", "Complete"):
            log.info(f"[Wallbox] Zustandswechsel {old_val}→{val} (intern, kein Reset)")
            return

        _ansteck_zeitpunkt          = time.time()
        _sperrzeit_ablauf_behandelt = False
        _psm_gesetzt                = -1
        _max_amp_gesetzt            = 0

        if logic_mode == "Eco":
            fahrzeug    = get_str(HELPER_FAHRZEUG)
            profil      = FAHRZEUG_PROFILE.get(fahrzeug, FAHRZEUG_FALLBACK)
            schwelle_3p = profil["schwelle_3p"]
            avg_grid, puffer_n = berechne_avg_grid()

            if avg_grid <= schwelle_3p:
                psm_wahl  = 2
                psm_grund = f"3P (avg5m={avg_grid:+.0f}W <= schwelle={schwelle_3p}W, {puffer_n} Werte)"
            else:
                psm_wahl  = 1
                psm_grund = f"1P (avg5m={avg_grid:+.0f}W > schwelle={schwelle_3p}W, {puffer_n} Werte)"

            log.info(
                f"[Wallbox] Auto angesteckt ({val}) | "
                f"Fahrzeug={fahrzeug} | "
                f"Phasenwahl: {psm_grund} | "
                f"Sperrzeit {ANSTECK_SPERRZEIT_S}s, max {MAX_AMP_3P}A"
            )
            set_psm(psm_wahl)
        else:
            log.info(
                f"[Wallbox] Auto angesteckt ({val}) | "
                f"[Basic: {logic_mode}] psm nicht gesetzt, manuelle Phasenwahl bleibt | "
                f"Sperrzeit {ANSTECK_SPERRZEIT_S}s, max {MAX_AMP_3P}A"
            )

        set_max_amp(MAX_AMP)

    else:
        log.info(f"[Wallbox] Auto abgesteckt / fertig ({val})")

@state_trigger(f"{HELPER_FAHRZEUG}")
def on_fahrzeug_change(**kwargs):
    """Sofortige Reaktion auf Fahrzeugwechsel im Dashboard."""
    global _min_amp_gesetzt
    fahrzeug    = kwargs.get("value", "")
    profil      = FAHRZEUG_PROFILE.get(fahrzeug, FAHRZEUG_FALLBACK)
    min_amp_neu = profil["mca"]
    log.info(f"[Wallbox] Fahrzeugwechsel → {fahrzeug} → mca={min_amp_neu}A")
    _min_amp_gesetzt = -1
    set_min_amp(min_amp_neu)

@state_trigger(f"{HELPER_ZIELWERT}")
def on_zielwert_change(**kwargs):
    """Sofortige Reaktion auf Schieberegler-Änderung."""
    global _pgt_gesetzt
    try:
        pgt_neu = int(float(kwargs.get("value", PGT_FALLBACK_W)))
    except (TypeError, ValueError):
        pgt_neu = PGT_FALLBACK_W
    pgt_neu = min(pgt_neu, -50)
    log.info(f"[Wallbox] Zielwert Netz geändert → pgt={pgt_neu}W")
    _pgt_gesetzt = 0
    set_pgt(pgt_neu)
