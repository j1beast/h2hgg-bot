import os
import requests
import json
import sqlite3
import statistics
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import asyncio
import time

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
BETSAPI_TOKEN = "255743-DXkD4nrqNqXhJq"
LEAGUE_ID = "25067"
SPORT_ID = "18"
BASE_URL = "https://api.b365api.com"
DB_PATH = "/app/data/cache.db"
USUARIOS_PERMITIDOS = [7339330267, 1021947497, 409760550, 1316315194, 1478076850, 7515654372]
CANAL_ID = -1003990501738
def es_permitido(update):
    return update.effective_user.id in USUARIOS_PERMITIDOS
    
# ─────────────────────────────────────────────
# BASE DE DATOS
# ─────────────────────────────────────────────

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS partidos (
        id TEXT PRIMARY KEY,
        home_name TEXT,
        away_name TEXT,
        home_jugador TEXT,
        away_jugador TEXT,
        home_franquicia TEXT,
        away_franquicia TEXT,
        score_home INTEGER,
        score_away INTEGER,
        fecha TEXT,
        timestamp INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS meta (
        clave TEXT PRIMARY KEY,
        valor TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS predicciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        jugador_a TEXT,
        jugador_b TEXT,
        franq_a TEXT,
        franq_b TEXT,
        ganador_predicho TEXT,
        cuota_ganador REAL,
        linea_total REAL,
        cuota_over REAL,
        cuota_under REAL,
        prediccion_ou TEXT,
        fecha_prediccion TEXT,
        resultado_real TEXT,
        acierto_ganador INTEGER,
        acierto_ou INTEGER,
        procesado INTEGER DEFAULT 0
    )''')
    for col, tipo in [
        ("prediccion_ou", "TEXT"),
        ("prob_h2h", "REAL"), ("prob_equipo", "REAL"), ("prob_h2h_eq", "REAL"),
        ("prob_forma", "REAL"), ("prob_h2h_rec", "REAL"),
        ("cuota_betsson_a", "REAL"), ("cuota_betsson_b", "REAL"),
        ("linea_betsson_ou", "REAL"), ("cuota_betsson_over", "REAL"),
        ("cuota_betsson_under", "REAL"),
        ("es_valor", "INTEGER"),
        ("enviado_canal", "INTEGER"),
        ("pts_real_a", "INTEGER"),
        ("pts_real_b", "INTEGER"),
        ("ratio_def_a", "REAL"), ("ratio_def_b", "REAL"),
        ("margen_avg_a", "REAL"), ("margen_avg_b", "REAL"),
        ("ou_h2h_total", "REAL"), ("ou_general", "REAL"),
        ("ou_franq", "REAL"), ("ou_reciente", "REAL"),
        ("ou_h2h_eq", "REAL"),
        ("ou_defensa_a", "REAL"), ("ou_defensa_b", "REAL"),
        ("prob_matchup", "REAL"),
        ("prob_defensa", "REAL"),
        ("prob_api", "REAL"),
        ("ou_historial", "REAL"),
        ("ou_tendencia", "REAL"),
        ("ou_ritmo", "REAL"),
        ("es_valor_ganador", "INTEGER"),
        ("es_valor_ou", "INTEGER"),
        ("ou_contraataque", "REAL"),
        ("ou_deficit_def", "REAL"),
        ("ou_consistencia", "REAL"),
    ]:
        try:
            c.execute(f"ALTER TABLE predicciones ADD COLUMN {col} {tipo}")
        except:
            pass
    c.execute('''CREATE TABLE IF NOT EXISTS betsson_cookies (
        id INTEGER PRIMARY KEY,
        cookies TEXT,
        timestamp INTEGER
    )''')
    conn.commit()
    conn.close()

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def guardar_partido(ev):
    home = ev.get("home", {}).get("name", "")
    away = ev.get("away", {}).get("name", "")
    ss = ev.get("ss", "")
    ev_id = str(ev.get("id", ""))
    if not ss or "-" not in ss or not ev_id:
        return
    try:
        score_h, score_a = map(int, ss.split("-"))
    except:
        return
    if score_h == 0 and score_a == 0:
        return
    home_jugador = extraer_nombre_jugador(home)
    away_jugador = extraer_nombre_jugador(away)
    home_franq = extraer_franquicia(home)
    away_franq = extraer_franquicia(away)
    t = ev.get("time", 0)
    fecha = datetime.utcfromtimestamp(int(t)).strftime("%Y-%m-%d") if t else ""
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT OR IGNORE INTO partidos
        (id, home_name, away_name, home_jugador, away_jugador, home_franquicia, away_franquicia, score_home, score_away, fecha, timestamp)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
        (ev_id, home, away, home_jugador, away_jugador, home_franq, away_franq, score_h, score_a, fecha, int(t) if t else 0))
    conn.commit()
    conn.close()

def total_partidos_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM partidos")
    total = c.fetchone()[0]
    conn.close()
    return total

def get_meta(clave):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT valor FROM meta WHERE clave=?", (clave,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def set_meta(clave, valor):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO meta (clave, valor) VALUES (?,?)", (clave, valor))
    conn.commit()
    conn.close()

# ─────────────────────────────────────────────
# API BETSAPI
# ─────────────────────────────────────────────

def get_upcoming():
    try:
        r = requests.get(f"{BASE_URL}/v1/events/upcoming?sport_id={SPORT_ID}&league_id={LEAGUE_ID}&token={BETSAPI_TOKEN}", timeout=20)
        return r.json().get("results", [])
    except Exception as e:
        print(f"Error get_upcoming: {e}")
        return []

def get_ended(page=1, day=None):
    try:
        url = f"{BASE_URL}/v3/events/ended?sport_id={SPORT_ID}&league_id={LEAGUE_ID}&token={BETSAPI_TOKEN}&page={page}"
        if day:
            url += f"&day={day}"
        r = requests.get(url, timeout=20)
        return r.json().get("results", [])
    except Exception as e:
        print(f"Error get_ended: {e}")
        return []

  
def get_upcoming_h2hggl():
    try:
        local_now = datetime.utcnow() + timedelta(hours=1)
        fecha = local_now.strftime("%Y-%m-%dT00:00:00+01:00")
        resp = requests.get(
            "https://api-h2h.hudstats.com/v1/schedule/nba",
            params={"date": fecha},
            headers={"Origin": "https://h2hggl.com"},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            return [g for g in data if not g.get("isCancelled") and g.get("matchStatus") is None]
        return []
    except Exception as e:
        print(f"Error get_upcoming_h2hggl: {e}")
        return []  

# ─────────────────────────────────────────────
# CARGA INICIAL Y ACTUALIZACION DIARIA
# ─────────────────────────────────────────────

def cargar_datos_iniciales(meses=11):
    print("Cargando datos históricos por fechas...")
    total = 0
    hoy = datetime.utcnow()
    fecha_inicio = hoy - timedelta(days=meses*30)
    fecha_actual = hoy
    while fecha_actual >= fecha_inicio:
        day_str = fecha_actual.strftime("%Y%m%d")
        for p in range(1, 21):
            try:
                resultados = get_ended(p, day=day_str)
                if not resultados:
                    break
                for ev in resultados:
                    guardar_partido(ev)
                    total += 1
            except:
                continue
        fecha_actual -= timedelta(days=1)
        time.sleep(0.5)
        if total % 500 == 0 and total > 0:
            print(f"Progreso: {total} partidos guardados...")
    set_meta("ultima_carga", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
    print(f"Carga completada: {total} partidos totales")

def actualizar_datos_hoy():
    hoy = datetime.utcnow().strftime("%Y%m%d")
    ayer = (datetime.utcnow() - timedelta(days=1)).strftime("%Y%m%d")
    total = 0
    for day in [ayer, hoy]:
        for p in range(1, 10):
            resultados = get_ended(p, day=day)
            if not resultados:
                break
            for ev in resultados:
                guardar_partido(ev)
                total += 1
    set_meta("ultima_actualizacion", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
    print(f"Actualización completada: {total} partidos nuevos")
    return total

async def tarea_actualizacion_diaria():
    while True:
        try:
            actualizar_datos_hoy()
            print(f"Actualización completada: {datetime.utcnow().strftime('%H:%M')}")
        except Exception as e:
            print(f"Error en actualización: {e}")
        await asyncio.sleep(900)  # 15 minutos

def guardar_prediccion(jugador_a, franq_a, jugador_b, franq_b, analisis, betsson=None):
    conn = get_db()
    c = conn.cursor()
    hoy = datetime.utcnow().strftime("%Y-%m-%d")
    c.execute('''SELECT id, cuota_betsson_a FROM predicciones 
                 WHERE ((jugador_a=? AND jugador_b=?) OR (jugador_a=? AND jugador_b=?))
                 AND fecha_prediccion LIKE ?
                 AND (procesado = 0 OR (procesado = 1 AND datetime(fecha_prediccion) >= datetime('now', '-2 hours')))''',
              (jugador_a, jugador_b, jugador_b, jugador_a, f"{hoy}%"))
    existing = c.fetchone()
    if existing:
        # Si ya existe pero sin cuota Betsson, actualizar cuotas
        if existing[1] is None and betsson:
            cb_a = betsson.get("cuota_a")
            cb_b = betsson.get("cuota_b")
            linea_bs = betsson.get("linea_ou")
            over_bs = betsson.get("cuota_over")
            under_bs = betsson.get("cuota_under")
            c.execute('''UPDATE predicciones SET cuota_betsson_a=?, cuota_betsson_b=?,
                         linea_betsson_ou=?, cuota_betsson_over=?, cuota_betsson_under=?
                         WHERE id=?''',
                      (cb_a, cb_b, linea_bs, over_bs, under_bs, existing[0]))
            conn.commit()
        conn.close()
        return
    if betsson and betsson.get("linea_ou") and analisis.get("linea_total"):
        prediccion_ou = "Over" if float(analisis["linea_total"]) > float(betsson["linea_ou"]) else "Under"
    else:
        prediccion_ou = "Over" if (analisis.get("over_total") or 99) < (analisis.get("under_total") or 99) else "Under"
    prob_a = analisis.get("prob_a") or 0.5
    prob_b = analisis.get("prob_b") or 0.5
    ganador = jugador_a if prob_a > prob_b else jugador_b
    cuota_ganador = analisis.get("cuota_a", 1.01) if prob_a > prob_b else analisis.get("cuota_b", 1.01)

    cb_a = cb_b = linea_bs = over_bs = under_bs = None
    if betsson:
        cb_a = betsson.get("cuota_a")
        cb_b = betsson.get("cuota_b")
        linea_bs = betsson.get("linea_ou")
        over_bs = betsson.get("cuota_over")
        under_bs = betsson.get("cuota_under")
    es_valor = 0
    
    try:
        c.execute('''INSERT INTO predicciones
            (jugador_a, jugador_b, franq_a, franq_b, ganador_predicho, cuota_ganador,
            linea_total, cuota_over, cuota_under, prediccion_ou, fecha_prediccion, procesado,
            prob_h2h, prob_equipo, prob_h2h_eq, prob_forma, prob_h2h_rec,
            cuota_betsson_a, cuota_betsson_b, linea_betsson_ou, cuota_betsson_over, cuota_betsson_under, es_valor, ratio_def_a, ratio_def_b, margen_avg_a, margen_avg_b, ou_h2h_total, ou_general, ou_franq, ou_reciente, ou_h2h_eq, ou_defensa_a, ou_defensa_b, prob_matchup, prob_defensa, prob_api, ou_historial, ou_tendencia, ou_ritmo, ou_contraataque, ou_deficit_def, ou_consistencia)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (jugador_a, jugador_b, franq_a, franq_b, ganador, cuota_ganador,
             analisis.get("linea_total"), analisis.get("over_total"), analisis.get("under_total"),
             prediccion_ou, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), 0,
             analisis.get("prob_h2h"), analisis.get("prob_equipo"), analisis.get("prob_h2h_eq"),
             analisis.get("prob_forma"), analisis.get("prob_h2h_rec"),
             cb_a, cb_b, linea_bs, over_bs, under_bs, es_valor,
             analisis.get("ratio_def_a"), analisis.get("ratio_def_b"),
             analisis.get("margen_avg_a"), analisis.get("margen_avg_b"),
             analisis.get("ou_h2h_total"), analisis.get("ou_general"),
             analisis.get("ou_franq"), analisis.get("ou_reciente"),
             analisis.get("ou_h2h_eq"), analisis.get("ou_defensa_a"),
             analisis.get("ou_defensa_b"),
             analisis.get("prob_matchup"),
             analisis.get("prob_defensa"),
             analisis.get("prob_api"),
             analisis.get("ou_historial"),
             analisis.get("ou_tendencia"),
             analisis.get("ou_ritmo"),
             analisis.get("ou_contraataque"),
             analisis.get("ou_deficit_def"),
             analisis.get("ou_consistencia")))
        conn.commit()
    except Exception as e:
        print(f"[ERROR INSERT prediccion] {e}")
    conn.close()

def verificar_predicciones():
    try:
        resp = requests.get("https://api-h2h.hudstats.com/v1/schedule/past/nba?limit=50", timeout=10,
                            headers={"Origin": "https://h2hggl.com"})
        resultados_api = resp.json() if resp.status_code == 200 else []
    except:
        resultados_api = []

    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT id, jugador_a, jugador_b, ganador_predicho,
                 linea_betsson_ou, prediccion_ou, ganador_predicho,
                 cuota_betsson_a, cuota_betsson_b, fecha_prediccion
                 FROM predicciones WHERE procesado = 0
                 AND datetime(fecha_prediccion) <= datetime('now', '-15 minutes')''')
    pendientes = c.fetchall()
    print(f"[VERIFY] {len(pendientes)} pendientes")

    for row in pendientes:
        try:
            pred_id, jugador_a, jugador_b, ganador_predicho, linea_betsson_ou, prediccion_ou, _, cb_a, cb_b, fecha_pred = row
            fecha_pred_dt = datetime.strptime(fecha_pred, "%Y-%m-%d %H:%M:%S")
            desde_dt = fecha_pred_dt - timedelta(minutes=30)

            # Buscar en API de la liga (sin lag)
            resultado_api = None
            for r in resultados_api:
                if r.get("matchStatus") != "MATCH_ENDED":
                    continue
                pa = r.get("participantAName", "").upper()
                pb = r.get("participantBName", "").upper()
                ja = jugador_a.upper()
                jb = jugador_b.upper()
                if (pa == ja and pb == jb) or (pa == jb and pb == ja):
                    try:
                        start = datetime.strptime(r["startDate"], "%Y-%m-%dT%H:%M:%SZ")
                        if start >= desde_dt:
                            resultado_api = r
                            break
                    except:
                        pass

            if resultado_api:
                if resultado_api["participantAName"].upper() == jugador_a.upper():
                    pts_a = resultado_api["teamAScore"]
                    pts_b = resultado_api["teamBScore"]
                else:
                    pts_a = resultado_api["teamBScore"]
                    pts_b = resultado_api["teamAScore"]
                ganador_real = jugador_a if pts_a > pts_b else jugador_b
                acierto_ganador = 1 if ganador_real == ganador_predicho else 0
                total_real = pts_a + pts_b
                if linea_betsson_ou is None:
                    acierto_ou = None
                else:
                    try:
                        linea = float(linea_betsson_ou)
                        acierto_ou = 1 if (total_real > linea if prediccion_ou == "Over" else total_real < linea) else 0
                    except:
                        acierto_ou = None
                c.execute('''UPDATE predicciones SET resultado_real=?, acierto_ganador=?, acierto_ou=?, procesado=1,
                             pts_real_a=?, pts_real_b=? WHERE id=?''',
                          (ganador_real, acierto_ganador, acierto_ou, pts_a, pts_b, pred_id))
                print(f"[OK] {jugador_a} vs {jugador_b}: procesado (liga)")
                continue

            # Fallback: historial BetsAPI
            partidos_h2h = buscar_historial_db(jugador_a, jugador_b)
            if not partidos_h2h:
                print(f"[SKIP] {jugador_a} vs {jugador_b}: sin H2H")
                continue
            desde_str = desde_dt.strftime("%Y-%m-%d")
            partidos_recientes = [p for p in partidos_h2h if p.get("fecha") and p["fecha"] >= desde_str]
            if not partidos_recientes:
                print(f"[SKIP] {jugador_a} vs {jugador_b}: sin partidos desde {desde_str} (H2H total={len(partidos_h2h)}, ultimo={partidos_h2h[0].get('fecha','?')})")
                continue
            ultimo = partidos_recientes[0]
            ganador_real = jugador_a if ultimo["gano_a"] else jugador_b
            acierto_ganador = 1 if ganador_real == ganador_predicho else 0
            total_real = ultimo["pts_a"] + ultimo["pts_b"]
            if linea_betsson_ou is None:
                acierto_ou = None
            else:
                try:
                    linea = float(linea_betsson_ou)
                    acierto_ou = 1 if (total_real > linea if prediccion_ou == "Over" else total_real < linea) else 0
                except:
                    acierto_ou = None
            c.execute('''UPDATE predicciones SET resultado_real=?, acierto_ganador=?, acierto_ou=?, procesado=1,
                         pts_real_a=?, pts_real_b=? WHERE id=?''',
                      (ganador_real, acierto_ganador, acierto_ou, ultimo["pts_a"], ultimo["pts_b"], pred_id))
            print(f"[OK] {jugador_a} vs {jugador_b}: procesado")
        except Exception as e:
            print(f"Error verificando predicción {pred_id}: {e}")
            continue

    # Expirar predicciones con más de 4 horas sin procesar
    desde_expiracion = (datetime.utcnow() - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''UPDATE predicciones SET procesado=2
                 WHERE procesado=0 AND fecha_prediccion <= ?''', (desde_expiracion,))
    if c.rowcount > 0:
        print(f"[EXPIRADAS] {c.rowcount} predicciones expiradas")
    conn.commit()
    conn.close()

async def tarea_predicciones_automaticas(app_ref):
    while True:
        try:
            proximos_liga = get_upcoming_h2hggl()
            cuotas_betsson = await get_cuotas_betsson()
            # Actualizar cuotas Betsson en predicciones que no las tienen
            for key, val in cuotas_betsson.items():
                partes = key.split("_vs_")
                if len(partes) != 2:
                    continue
                ja, jb = partes[0], partes[1]
                conn_u = get_db()
                conn_u.execute('''UPDATE predicciones SET 
                                 cuota_betsson_a=?, cuota_betsson_b=?,
                                 linea_betsson_ou=?, cuota_betsson_over=?, cuota_betsson_under=?
                                 WHERE cuota_betsson_a IS NULL
                                 AND ((jugador_a=? AND jugador_b=?) OR (jugador_a=? AND jugador_b=?))
                                 AND procesado=0''',
                              (val.get("cuota_a"), val.get("cuota_b"),
                               val.get("linea_ou"), val.get("cuota_over"), val.get("cuota_under"),
                               ja, jb, jb, ja))
                conn_u.commit()
                conn_u.close()
            partidos_enviados = set()
            for partido in proximos_liga:
                jugador_a = partido["participantAName"].upper()
                jugador_b = partido["participantBName"].upper()
                franq_a = partido.get("teamAName", jugador_a)
                franq_b = partido.get("teamBName", jugador_b)
                try:
                    hora_utc = datetime.strptime(partido["startDate"], "%Y-%m-%dT%H:%M:%SZ").strftime("%H:%M UTC")
                except:
                    hora_utc = "?? UTC"
                key_norm = "_vs_".join(sorted([jugador_a, jugador_b]))
                if key_norm in partidos_enviados:
                    continue
                partidos_enviados.add(key_norm)
                key_ab = f"{jugador_a}_vs_{jugador_b}"
                key_ba = f"{jugador_b}_vs_{jugador_a}"
                betsson_raw = cuotas_betsson.get(key_ab) or cuotas_betsson.get(key_ba)
                betsson_pred = None
                if betsson_raw:
                    invertido = key_ba in cuotas_betsson and key_ab not in cuotas_betsson
                    if invertido:
                        betsson_pred = {
                            "cuota_a": betsson_raw["cuota_b"], "cuota_b": betsson_raw["cuota_a"],
                            "cuota_over": betsson_raw.get("cuota_over"), "cuota_under": betsson_raw.get("cuota_under"),
                            "linea_ou": betsson_raw.get("linea_ou"),
                            "hora_utc": betsson_raw.get("hora_utc", hora_utc)
                        }
                    else:
                        betsson_pred = dict(betsson_raw)
                    hora_utc = betsson_pred.get("hora_utc", hora_utc)
                partidos_a = buscar_partidos_jugador_db(jugador_a)
                partidos_b = buscar_partidos_jugador_db(jugador_b)
                partidos_h2h = buscar_historial_db(jugador_a, jugador_b)
                if partidos_a and partidos_b:
                    analisis = analizar_partido(jugador_a, franq_a, jugador_b, franq_b, partidos_h2h, partidos_a, partidos_b)
                    guardar_prediccion(jugador_a, franq_a, jugador_b, franq_b, analisis, betsson=betsson_pred)
                    if betsson_pred:
                        # Detectar valor
                        bot_a = analisis.get("cuota_a", 0)
                        bot_b = analisis.get("cuota_b", 0)
                        cb_a = betsson_pred["cuota_a"]
                        cb_b = betsson_pred["cuota_b"]
                        linea_bot = analisis.get("linea_total")
                        bs_linea = betsson_pred.get("linea_ou")
                        hay_valor_ganador = (cb_a > 0 and bot_a > 0 and cb_a / bot_a >= 1.20 and cb_a <= 2.20) or (cb_b > 0 and bot_b > 0 and cb_b / bot_b >= 1.20 and cb_b <= 2.20)
                        hay_valor_ou = False
                        if linea_bot and bs_linea:
                            try:
                                hay_valor_ou = abs(float(linea_bot) - float(bs_linea)) >= 8
                            except:
                                pass
                        if not hay_valor_ganador and not hay_valor_ou:
                            continue
                            
                        if not hay_valor_ganador and not hay_valor_ou:
                            continue
                            # No enviar si ya se envió antes
                        conn_c = get_db()
                        ya_enviado = conn_c.execute('''SELECT enviado_canal FROM predicciones
                                                      WHERE ((jugador_a=? AND jugador_b=?) OR (jugador_a=? AND jugador_b=?))
                                                      AND datetime(fecha_prediccion) >= datetime('now', '-36 hours')
                                                      AND enviado_canal=1''',
                                                   (jugador_a, jugador_b, jugador_b, jugador_a)).fetchone()
                        conn_c.close()
                        if ya_enviado:
                            continue
                        # Construir mensaje de valor
                        msg = ""
                        # Valor ganador
                        if hay_valor_ganador:
                            if cb_a > bot_a:
                                pct = round((cb_a / bot_a - 1) * 100, 1)
                                msg += f"🎯 *VALUE BET - GANADOR*\n"
                                msg += f"{franq_a} ({jugador_a}) vs {franq_b} ({jugador_b}) — {hora_utc}\n"
                                msg += f"Betsson: {jugador_a} gana → `{cb_a}`\n"
                                msg += f"Bot: `{bot_a}` (+{pct}% diferencia)\n"
                            else:
                                pct = round((cb_b / bot_b - 1) * 100, 1)
                                msg += f"🎯 *VALUE BET - GANADOR*\n"
                                msg += f"{franq_a} ({jugador_a}) vs {franq_b} ({jugador_b}) — {hora_utc}\n"
                                msg += f"Betsson: {jugador_b} gana → `{cb_b}`\n"
                                msg += f"Bot: `{bot_b}` (+{pct}% diferencia)\n"
                        # Valor O/U
                        bs_over = betsson_pred.get("cuota_over")
                        bs_under = betsson_pred.get("cuota_under")
                        if hay_valor_ou and bs_linea and linea_bot:
                            try:
                                diff_pts = round(float(linea_bot) - float(bs_linea), 1)
                                if float(linea_bot) > float(bs_linea):
                                    tipo_ou = "OVER"
                                    diff_str = f"+{diff_pts} pts"
                                else:
                                    tipo_ou = "UNDER"
                                    diff_str = f"{diff_pts} pts"
                                if msg:
                                    msg += f"\n"
                                msg += f"📊 *VALUE BET - OVER/UNDER*\n"
                                msg += f"{franq_a} ({jugador_a}) vs {franq_b} ({jugador_b}) — {hora_utc}\n"
                                msg += f"Betsson: {tipo_ou} `{bs_linea}` → `{bs_over if tipo_ou == 'OVER' else bs_under}`\n"
                                msg += f"Línea bot: {linea_bot} pts ({diff_str})\n"
                            except:
                                pass
                        conn_v = get_db()
                        conn_v.execute('''UPDATE predicciones SET es_valor=1,
                                         es_valor_ganador=?, es_valor_ou=?
                                         WHERE jugador_a=? AND jugador_b=? AND fecha_prediccion LIKE ?''',
                                      (1 if hay_valor_ganador else 0,
                                       1 if hay_valor_ou else 0,
                                       jugador_a, jugador_b, f"{datetime.utcnow().strftime('%Y-%m-%d')}%"))
                        conn_v.commit()
                        conn_v.close()
                        try:
                            await app_ref.bot.send_message(chat_id=CANAL_ID, text=msg, parse_mode="Markdown")
                            conn_e = get_db()
                            conn_e.execute('''UPDATE predicciones SET enviado_canal=1
                                             WHERE ((jugador_a=? AND jugador_b=?) OR (jugador_a=? AND jugador_b=?))
                                             AND datetime(fecha_prediccion) >= datetime('now', '-36 hours')''',
                                          (jugador_a, jugador_b, jugador_b, jugador_a))
                            conn_e.commit()
                            conn_e.close()
                        except Exception as e:
                            print(f"Error enviando al canal: {e}")
            verificar_predicciones()
        except Exception as e:
            import traceback
            print(f"Error en predicciones automáticas: {e}")
            print(traceback.format_exc())
        await asyncio.sleep(300)  # 5 minutos
        
# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def extraer_nombre_jugador(nombre_equipo):
    if "(" in nombre_equipo and ")" in nombre_equipo:
        return nombre_equipo.split("(")[-1].replace(")", "").strip()
    return nombre_equipo.strip()

def extraer_franquicia(nombre_equipo):
    if "(" in nombre_equipo:
        return nombre_equipo.split("(")[0].strip()
    return nombre_equipo.strip()

async def get_cuotas_coolbet():
    try:
        print("Iniciando scraping Coolbet...")
        from playwright.async_api import async_playwright
        print("Playwright importado OK")
        cuotas = {}
        async with async_playwright() as p:
            print("Playwright context OK")
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
            )
            print("Browser lanzado OK")
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
                locale="es-ES",
                timezone_id="Europe/Madrid",
                viewport={"width": 1280, "height": 800},
                extra_http_headers={
                    "Accept-Language": "es-ES,es;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                }
            )
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page = await context.new_page()
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
                Object.defineProperty(navigator, 'languages', {get: () => ['es-ES', 'es']});
                window.chrome = {runtime: {}};
            """)

            print("Cargando página Betsson...")
            respuestas = []
            ws_mensajes = []
            
            page.on("websocket", lambda ws: ws.on("framereceived", lambda payload: ws_mensajes.append(payload)))
            
            async def capturar_respuesta(response):
                if response.status == 200 and ("route-data" in response.url or "liveEvents" in response.url or "events?cee" in response.url):
                    try:
                        data = await response.json()
                        print(f"URL: {response.url[:120]}")
                        print(f"CONTENIDO: {str(data)[:500]}")
                        respuestas.append({"url": response.url, "data": data})
                    except:
                        pass
            page.on("response", capturar_respuesta)
            await page.goto("https://www.betsson.es/apuestas-deportivas/baloncesto/ebasketball/liga-h2h-gg-de-baloncesto-electronico-4-x-5-minu?tab=liveAndUpcoming", wait_until="domcontentloaded", timeout=20000)
            print("Página cargada, esperando datos...")
            await page.wait_for_timeout(15000)
            print(f"Respuestas HTTP: {len(respuestas)}")
            print(f"Mensajes WebSocket: {len(ws_mensajes)}")
            if ws_mensajes:
                print(f"WS ejemplo: {str(ws_mensajes[0])[:300]}")
            await browser.close()
            
        print(f"Respuestas capturadas: {len(respuestas)}")
        for data in respuestas:
            fixtures = data.get("fixtures") or data.get("events") or data.get("data") or []
            if isinstance(fixtures, list):
                for fixture in fixtures:
                        try:
                            home = fixture.get("home", {}).get("name", "") or fixture.get("homeName", "")
                            away = fixture.get("away", {}).get("name", "") or fixture.get("awayName", "")
                            if not home or not away:
                                continue
                            home_j = extraer_nombre_jugador(home).upper()
                            away_j = extraer_nombre_jugador(away).upper()
                            markets = fixture.get("markets") or fixture.get("odds") or []
                            for market in markets:
                                outcomes = market.get("outcomes") or market.get("selections") or []
                                if len(outcomes) >= 2:
                                    cuota_home = outcomes[0].get("odds") or outcomes[0].get("price")
                                    cuota_away = outcomes[1].get("odds") or outcomes[1].get("price")
                                    if cuota_home and cuota_away:
                                        start_time = event.get("startDate", "")
                                        try:
                                            hora_utc_bs = datetime.strptime(start_time, "%Y-%m-%dT%H:%M:%SZ").strftime("%H:%M UTC")
                                        except:
                                            hora_utc_bs = "?? UTC"
                                        cuotas[f"{home_j}_vs_{away_j}"] = {
                                            "cuota_a": cuota_home,
                                            "cuota_b": cuota_away,
                                            "cuota_over": cuota_over,
                                            "cuota_under": cuota_under,
                                            "linea_ou": linea_ou,
                                            "home": home_j,
                                            "away": away_j,
                                            "hora_utc": hora_utc_bs
                                        }
                        except:
                            continue
        return cuotas
    except Exception as e:
        import traceback
        print(f"Error scraping Coolbet: {e}")
        print(traceback.format_exc())
        return {}
        
def calcular_peso_fecha(fecha_str):
    if not fecha_str:
        return 0.5
    try:
        fecha = datetime.strptime(fecha_str, "%Y-%m-%d")
        dias = (datetime.utcnow() - fecha).days
        if dias <= 30:
            return 1.0
        elif dias <= 90:
            return 0.7
        elif dias <= 180:
            return 0.4
        else:
            return 0.2
    except:
        return 0.5
        
def prob_to_odds(prob):
    if prob <= 0 or prob >= 1:
        return 1.01
    margen = 1.111
    return round(1 / (prob * margen), 2)

def calcular_std(valores):
    if len(valores) < 2:
        return 0
    return round(statistics.stdev(valores), 1)

_pesos_cache = {}
_pesos_cache_ts = 0
_stats_liga_cache = {}
_stats_liga_cache_ts = 0

def cargar_pesos():
    global _pesos_cache, _pesos_cache_ts
    ahora = time.time()
    if _pesos_cache and (ahora - _pesos_cache_ts) < 3600:
        return _pesos_cache
    pesos_json = get_meta("pesos_optimizados")
    if pesos_json:
        try:
            _pesos_cache = json.loads(pesos_json)
            _pesos_cache_ts = ahora
            return _pesos_cache
        except:
            pass
    _pesos_cache = {'h2h': 0.18, 'equipo': 0.16, 'forma': 0.15, 'h2h_rec': 0.11, 'matchup': 0.12, 'defensa': 0.18, 'api': 0.10}
    _pesos_cache_ts = ahora
    return _pesos_cache

def calcular_pesos_optimos():
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT jugador_a, resultado_real,
                 prob_h2h, prob_equipo, prob_forma, prob_h2h_rec, prob_matchup, prob_defensa, prob_api
                 FROM predicciones 
                 WHERE procesado=1 
                 AND acierto_ganador IS NOT NULL
                 AND resultado_real IS NOT NULL
                 AND prob_h2h IS NOT NULL''')
    rows = c.fetchall()
    conn.close()
    if len(rows) < 30:
        return None, "Necesitas al menos 30 predicciones procesadas", {}
    factores_data = {'h2h': [], 'equipo': [], 'forma': [], 'h2h_rec': [], 'matchup': [], 'defensa': [], 'api': []}
    for jugador_a, resultado_real, prob_h2h, prob_equipo, prob_forma, prob_h2h_rec, prob_matchup, prob_defensa, prob_api in rows:
        if resultado_real is None:
            continue
        ganó_a = (resultado_real == jugador_a)
        for nombre, prob in [('h2h', prob_h2h), ('equipo', prob_equipo), ('forma', prob_forma),
                              ('h2h_rec', prob_h2h_rec), ('matchup', prob_matchup),
                              ('defensa', prob_defensa), ('api', prob_api)]:
            if prob is None:
                continue
            if prob is None:
                continue
            factores_data[nombre].append(int((prob > 0.5) == ganó_a))
    accuracies = {}
    n_muestras = {}
    for nombre, resultados in factores_data.items():
        n = len(resultados)
        n_muestras[nombre] = n
        accuracies[nombre] = sum(resultados) / n if n >= 5 else 0.5
    edges = {k: max(0.0, v - 0.5) for k, v in accuracies.items()}
    total_edge = sum(edges.values())
    min_w = 0.05
    n_factores = len(edges)
    if total_edge == 0:
        w_base = 1.0 / n_factores
        pesos = {k: w_base for k in edges}
    else:
        extra = 1.0 - (min_w * n_factores)
        pesos = {k: min_w + (edges[k] / total_edge) * extra for k in edges}
    total = sum(pesos.values())
    pesos = {k: round(v / total, 4) for k, v in pesos.items()}
    return pesos, accuracies, n_muestras

def calcular_pesos_optimos_ou():
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT ou_h2h_total, ou_reciente,
                 ou_tendencia, ou_contraataque, ou_deficit_def, ou_consistencia, linea_betsson_ou, pts_real_a, pts_real_b
                 FROM predicciones
                 WHERE procesado=1 AND linea_betsson_ou IS NOT NULL
                 AND pts_real_a IS NOT NULL AND ou_h2h_total IS NOT NULL''')
    rows = c.fetchall()
    conn.close()
    if len(rows) < 30:
        return None, "Necesitas al menos 30 predicciones procesadas", {}
    factores_data = {'h2h': [], 'reciente': [], 'tendencia': [], 'contraataque': [], 'deficit_def': []}
    for ou_h2h, ou_rec, ou_tend, ou_contra, ou_def, ou_cons, linea_bs, pts_a, pts_b in rows:
        total_real = pts_a + pts_b
        real_over = total_real > linea_bs
        ou_def = None
        for nombre, val in [('h2h', ou_h2h), ('reciente', ou_rec), ('tendencia', ou_tend),
                             ('contraataque', ou_contra), ('deficit_def', ou_def)]:
            if val is None:
                continue
            pred_over = val > linea_bs
            factores_data[nombre].append(int(pred_over == real_over))
    accuracies = {}
    n_muestras = {}
    for nombre, resultados in factores_data.items():
        n = len(resultados)
        n_muestras[nombre] = n
        accuracies[nombre] = sum(resultados) / n if n >= 10 else 0.5
    edges = {k: max(0.0, v - 0.5) for k, v in accuracies.items()}
    total_edge = sum(edges.values())
    if total_edge == 0:
        n_factores = len(edges)
        pesos = {k: 1.0 / n_factores for k in edges}
    else:
        pesos = {k: edges[k] / total_edge for k in edges}
    total = sum(pesos.values())
    pesos = {k: round(v / total, 4) for k, v in pesos.items()}
    return pesos, accuracies, n_muestras

def calcular_linea_api(api_a, api_b):
    if not api_a or not api_b:
        return None
    pts_a = api_a.get("avgPoints")
    pts_b = api_b.get("avgPoints")
    if not pts_a or not pts_b:
        return None
    base = pts_a + pts_b
    stats_liga = get_stats_liga()
    jugadores = list(stats_liga.values()) if stats_liga else []
    def bl(key, default):
        vals = [p.get(key) for p in jugadores if p.get(key)]
        return round(sum(vals) / len(vals), 2) if vals else default
    bl_pos   = bl("avgTimeOfPossession", 9.0)
    bl_fb    = bl("avgFastBreakPoints", 9.9)
    bl_to    = bl("avgTurnovers", 5.0)
    bl_fga   = bl("avgFieldGoalsAttempted", 40.0)
    bl_3pa   = bl("avg3PointersAttempted", 13.0)
    bl_3pp   = bl("threePointersPercent", 42.0)
    bl_paint = bl("avgPointsInThePaint", 34.0)
    bl_fg    = bl("avgFieldGoalsPercent", 48.0)
    bl_orb   = bl("avgOffensiveRebounds", 5.0)
    vals_contra = []
    for p in jugadores:
        mp_p = p.get("matchesPlayed") or 0
        pa = p.get("pointsAgainst")
        if pa and mp_p > 0:
            vals_contra.append(pa / mp_p)
    bl_contra = sum(vals_contra) / len(vals_contra) if vals_contra else 54.0
    mp_a = api_a.get("matchesPlayed") or 1
    mp_b = api_b.get("matchesPlayed") or 1
    pos_a   = api_a.get("avgTimeOfPossession") or bl_pos
    pos_b   = api_b.get("avgTimeOfPossession") or bl_pos
    fb_a    = api_a.get("avgFastBreakPoints") or bl_fb
    fb_b    = api_b.get("avgFastBreakPoints") or bl_fb
    to_a    = api_a.get("avgTurnovers") or bl_to
    to_b    = api_b.get("avgTurnovers") or bl_to
    fga_a   = api_a.get("avgFieldGoalsAttempted") or bl_fga
    fga_b   = api_b.get("avgFieldGoalsAttempted") or bl_fga
    t3a_a   = api_a.get("avg3PointersAttempted") or bl_3pa
    t3a_b   = api_b.get("avg3PointersAttempted") or bl_3pa
    t3p_a   = api_a.get("threePointersPercent") or bl_3pp
    t3p_b   = api_b.get("threePointersPercent") or bl_3pp
    paint_a = api_a.get("avgPointsInThePaint") or bl_paint
    paint_b = api_b.get("avgPointsInThePaint") or bl_paint
    fg_a    = api_a.get("avgFieldGoalsPercent") or bl_fg
    fg_b    = api_b.get("avgFieldGoalsPercent") or bl_fg
    orb_a   = api_a.get("avgOffensiveRebounds") or bl_orb
    orb_b   = api_b.get("avgOffensiveRebounds") or bl_orb
    contra_a = (api_a.get("pointsAgainst") or (bl_contra * mp_a)) / mp_a
    contra_b = (api_b.get("pointsAgainst") or (bl_contra * mp_b)) / mp_b
    ajuste = 0.0
    # 1. POSESIÓN + DEFENSA
    pos_media    = (pos_a + pos_b) / 2
    contra_media = (contra_a + contra_b) / 2
    es_rapido_a = pos_a < bl_pos * 0.88
    es_lento_a  = pos_a > bl_pos * 1.12
    es_rapido_b = pos_b < bl_pos * 0.88
    es_lento_b  = pos_b > bl_pos * 1.12
    if (es_lento_a or es_lento_b) and contra_media < bl_contra * 0.90:
        ajuste -= 3.0  # dominante + defensivo = partido lento con pocos puntos
    elif (es_lento_a or es_lento_b) and contra_media > bl_contra * 1.10:
        ajuste -= 0.5  # dominante pero mal defensor = efecto leve
    elif es_rapido_a and es_rapido_b:
        ajuste += 2.0  # ambos rápidos = más posesiones = más puntos
    elif (es_rapido_a and es_lento_b) or (es_lento_a and es_rapido_b):
        pass           # estilos opuestos = se neutralizan
    else:
        ajuste += (bl_pos - pos_media) * 1.5
    # 2. INTENTOS DE TIRO
    ajuste += ((fga_a + fga_b) / 2 - bl_fga) * 0.3
    # 3. TRIPLES
    ajuste += ((t3a_a - bl_3pa) * (t3p_a / 100) + (t3a_b - bl_3pa) * (t3p_b / 100)) * 0.5
    # 4. PINTURA
    ajuste += ((paint_a + paint_b) / 2 - bl_paint) * 0.25
    # 5. CONTRAATAQUE — lineal + interacción si ambos corren mucho
    ajuste += ((fb_a + fb_b) / 2 - bl_fb) * 0.7
    if fb_a > bl_fb * 1.25 and fb_b > bl_fb * 1.25:
        ajuste += 2.0
    # 6. PÉRDIDAS — lineal + interacción si ambos pierden mucho
    ajuste += ((to_a + to_b) / 2 - bl_to) * 0.5
    if to_a > bl_to * 1.25 and to_b > bl_to * 1.25:
        ajuste += 1.5
    # 7. EFICIENCIA DE TIRO
    if fg_a > bl_fg * 1.05 and fg_b > bl_fg * 1.05:
        ajuste += 2.5   # ambos eficientes = más puntos por posesión
    elif fg_a < bl_fg * 0.95 and fg_b < bl_fg * 0.95:
        ajuste -= 2.5   # ambos ineficientes = posesiones desperdiciadas
    # 8. REBOTES OFENSIVOS
    if orb_a > bl_orb * 1.20 and orb_b > bl_orb * 1.20:
        ajuste += 1.5   # ambos buscan segundas oportunidades
    ajuste = max(-15, min(15, ajuste))
    return round(base + ajuste + 1.5, 1)

def calcular_prob_api(api_a, api_b):
    if not api_a or not api_b:
        return None
    scores = []

    fg_a = api_a.get("avgFieldGoalsPercent")
    fg_b = api_b.get("avgFieldGoalsPercent")
    if fg_a and fg_b and (fg_a + fg_b) > 0:
        scores.append(fg_a / (fg_a + fg_b))

    ast_a = api_a.get("avgAssists") or 0
    to_a = api_a.get("avgTurnovers") or 1
    ast_b = api_b.get("avgAssists") or 0
    to_b = api_b.get("avgTurnovers") or 1
    ratio_a = ast_a / max(to_a, 0.1)
    ratio_b = ast_b / max(to_b, 0.1)
    if (ratio_a + ratio_b) > 0:
        scores.append(ratio_a / (ratio_a + ratio_b))

    tp_a = api_a.get("threePointersPercent")
    tp_b = api_b.get("threePointersPercent")
    if tp_a and tp_b and (tp_a + tp_b) > 0:
        scores.append(tp_a / (tp_a + tp_b))

    wp_a = api_a.get("matchesWinPct")
    wp_b = api_b.get("matchesWinPct")
    if wp_a and wp_b and (wp_a + wp_b) > 0:
        scores.append(wp_a / (wp_a + wp_b))

    mp_a = api_a.get("matchesPlayed") or 1
    mp_b = api_b.get("matchesPlayed") or 1
    pts_a = api_a.get("avgPoints")
    pts_b = api_b.get("avgPoints")
    contra_a = round(api_a["pointsAgainst"] / mp_a, 1) if api_a.get("pointsAgainst") and mp_a > 0 else None
    contra_b = round(api_b["pointsAgainst"] / mp_b, 1) if api_b.get("pointsAgainst") and mp_b > 0 else None
    if pts_a and pts_b and contra_a and contra_b and pts_a > 0 and pts_b > 0:
        dominio_a = (pts_a - contra_a) / pts_a
        dominio_b = (pts_b - contra_b) / pts_b
        dom_sum = (dominio_a + 1) + (dominio_b + 1)
        if dom_sum > 0:
            scores.append((dominio_a + 1) / dom_sum)

    if not scores:
        return None
    return round(sum(scores) / len(scores), 4)
    
def get_stats_liga():
    global _stats_liga_cache, _stats_liga_cache_ts
    ahora = time.time()
    if _stats_liga_cache and (ahora - _stats_liga_cache_ts) < 3600:
        return _stats_liga_cache
    try:
        resp = requests.get(
            "https://api-h2h.hudstats.com/v1/participant/nba",
            headers={"Origin": "https://h2hggl.com"},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            _stats_liga_cache = {p["participantName"].upper(): p for p in data if "participantName" in p}
            _stats_liga_cache_ts = ahora
            print(f"[STATS] Cache actualizado: {len(_stats_liga_cache)} jugadores")
    except Exception as e:
        print(f"[STATS] Error cargando stats: {e}")
    return _stats_liga_cache

# ─────────────────────────────────────────────
# CONSULTAS A LA BASE DE DATOS
# ─────────────────────────────────────────────

def buscar_historial_db(jugador_a, jugador_b):
    conn = get_db()
    c = conn.cursor()
    ja = jugador_a.upper()
    jb = jugador_b.upper()
    c.execute('''SELECT home_jugador, away_jugador, home_franquicia, away_franquicia,
                 score_home, score_away, fecha, timestamp
                 FROM partidos
                 WHERE (UPPER(home_jugador)=? AND UPPER(away_jugador)=?)
                    OR (UPPER(home_jugador)=? AND UPPER(away_jugador)=?)
                 ORDER BY timestamp DESC''', (ja, jb, jb, ja))
    rows = c.fetchall()
    conn.close()
    partidos_h2h = []
    for row in rows:
        home_j, away_j, home_f, away_f, sc_h, sc_a, fecha, ts = row
        if home_j.upper() == ja:
            partidos_h2h.append({"pts_a": sc_h, "pts_b": sc_a, "gano_a": sc_h > sc_a, "franq_a": home_f, "franq_b": away_f, "fecha": fecha})
        else:
            partidos_h2h.append({"pts_a": sc_a, "pts_b": sc_h, "gano_a": sc_a > sc_h, "franq_a": away_f, "franq_b": home_f, "fecha": fecha})
    return partidos_h2h

def buscar_partidos_jugador_db(jugador):
    conn = get_db()
    c = conn.cursor()
    j = jugador.upper()
    c.execute('''SELECT home_jugador, away_jugador, home_franquicia, away_franquicia,
                 score_home, score_away, fecha, timestamp
                 FROM partidos
                 WHERE UPPER(home_jugador)=? OR UPPER(away_jugador)=?
                 ORDER BY timestamp DESC''', (j, j))
    rows = c.fetchall()
    conn.close()
    partidos = []
    for row in rows:
        home_j, away_j, home_f, away_f, sc_h, sc_a, fecha, ts = row
        if home_j.upper() == j:
            partidos.append({"pts_favor": sc_h, "pts_contra": sc_a, "gano": sc_h > sc_a, "franquicia": home_f, "fecha": fecha})
        else:
            partidos.append({"pts_favor": sc_a, "pts_contra": sc_h, "gano": sc_a > sc_h, "franquicia": away_f, "fecha": fecha})
    return partidos

def buscar_matchup_franquicias(franq_a, franq_b):
    conn = get_db()
    c = conn.cursor()
    fa = franq_a.strip().upper()
    fb = franq_b.strip().upper()

    def buscar(query_a, query_b, modo="exact"):
        if modo == "exact":
            c.execute('''SELECT COUNT(*),
                         SUM(CASE WHEN UPPER(home_franquicia)=? AND score_home > score_away THEN 1
                                  WHEN UPPER(away_franquicia)=? AND score_away > score_home THEN 1
                                  ELSE 0 END)
                         FROM partidos
                         WHERE (UPPER(home_franquicia)=? AND UPPER(away_franquicia)=?)
                            OR (UPPER(home_franquicia)=? AND UPPER(away_franquicia)=?)''',
                      (query_a, query_a, query_a, query_b, query_b, query_a))
        else:
            c.execute('''SELECT COUNT(*),
                         SUM(CASE WHEN UPPER(home_franquicia) LIKE ? AND score_home > score_away THEN 1
                                  WHEN UPPER(away_franquicia) LIKE ? AND score_away > score_home THEN 1
                                  ELSE 0 END)
                         FROM partidos
                         WHERE (UPPER(home_franquicia) LIKE ? AND UPPER(away_franquicia) LIKE ?)
                            OR (UPPER(home_franquicia) LIKE ? AND UPPER(away_franquicia) LIKE ?)''',
                      (f"%{query_a}%", f"%{query_a}%", f"%{query_a}%", f"%{query_b}%", f"%{query_b}%", f"%{query_a}%"))
        row = c.fetchone()
        return row[0] or 0, row[1] or 0

    # 1. Coincidencia exacta
    total, victorias_a = buscar(fa, fb, "exact")

    # 2. Si no hay, coincidencia parcial con primera palabra (ej: "CHARLOTTE")
    if total == 0:
        fa_key = fa.split()[0]
        fb_key = fb.split()[0]
        total, victorias_a = buscar(fa_key, fb_key, "like")

    conn.close()
    if total == 0:
        return 0.5
    return victorias_a / total

# ─────────────────────────────────────────────
# ANALISIS
# ─────────────────────────────────────────────

def calcular_confianza(analisis, partidos_a, partidos_b):
    puntos = 0
    total_factores = 5

    # H2H total
    h2h = analisis.get("h2h_total", 0)
    if h2h > 20:
        puntos += 3
    elif h2h >= 5:
        puntos += 2
    else:
        puntos += 1

    # H2H mismos equipos
    h2h_eq = analisis.get("h2h_equipos", 0)
    if h2h_eq > 5:
        puntos += 3
    elif h2h_eq >= 2:
        puntos += 2
    else:
        puntos += 1

    # Partidos con equipo actual
    franq_a = analisis.get("partidos_a_franq") or 0
    franq_b = analisis.get("partidos_b_franq") or 0
    avg_franq = (franq_a + franq_b) / 2
    if avg_franq > 15:
        puntos += 3
    elif avg_franq >= 5:
        puntos += 2
    else:
        puntos += 1

    # Total partidos jugador
    total_a = len(partidos_a)
    total_b = len(partidos_b)
    avg_total = (total_a + total_b) / 2
    if avg_total > 400:
        puntos += 3
    elif avg_total >= 70:
        puntos += 2
    else:
        puntos += 1

    # Consistencia
    std_a = analisis.get("std_pts_a") or 15
    std_b = analisis.get("std_pts_b") or 15
    avg_std = (std_a + std_b) / 2
    if avg_std < 8:
        puntos += 3
    elif avg_std <= 15:
        puntos += 2
    else:
        puntos += 1

    # Calcular nivel
    max_puntos = 15
    porcentaje = puntos / max_puntos

    if porcentaje >= 0.85:
        return "🟢 Alta"
    elif porcentaje >= 0.45:
        return "🟡 Media"
    else:
        return "🔴 Baja"
        
def analizar_partido(jugador_a, franq_a, jugador_b, franq_b, partidos_h2h, partidos_a, partidos_b):
    resultado = {}
    # H2H histórico general (25%)
    if partidos_h2h:
        peso_total = sum(calcular_peso_fecha(p.get("fecha")) for p in partidos_h2h)
        wins_a = sum(calcular_peso_fecha(p.get("fecha")) for p in partidos_h2h if p["gano_a"])
        total_h2h = len(partidos_h2h)
        if total_h2h < 5:
            prob_h2h = 0.5 + (wins_a / peso_total - 0.5) * 0.3 if peso_total > 0 else 0.5
        else:
            prob_h2h = wins_a / peso_total if peso_total > 0 else 0.5
        pts_a_h2h = [p["pts_a"] for p in partidos_h2h]
        pts_b_h2h = [p["pts_b"] for p in partidos_h2h]
        resultado["h2h_total"] = total_h2h
        resultado["h2h_wins_a_real"] = sum(1 for p in partidos_h2h if p["gano_a"])
        resultado["h2h_avg_a"] = round(sum(pts_a_h2h) / len(pts_a_h2h), 1)
        resultado["h2h_avg_b"] = round(sum(pts_b_h2h) / len(pts_b_h2h), 1)
    else:
        prob_h2h = 0.5
        resultado["h2h_total"] = 0
        resultado["h2h_wins_a"] = 0

    # H2H con equipos actuales (20%)
    h2h_equipos = [p for p in partidos_h2h if p.get("franq_a", "").upper() == franq_a.upper() and p.get("franq_b", "").upper() == franq_b.upper()]
    if h2h_equipos:
        wins_eq = sum(1 for p in h2h_equipos if p["gano_a"])
        prob_h2h_eq = wins_eq / len(h2h_equipos)
        resultado["h2h_equipos"] = len(h2h_equipos)
        resultado["h2h_wins_eq_a"] = wins_eq
    else:
        prob_h2h_eq = 0.5
        resultado["h2h_equipos"] = 0
        resultado["h2h_wins_eq_a"] = 0

    # Matchup de franquicias
    mq_fa = partidos_a[0]["franquicia"] if partidos_a else franq_a
    mq_fb = partidos_b[0]["franquicia"] if partidos_b else franq_b
    prob_matchup = buscar_matchup_franquicias(mq_fa, mq_fb)
    resultado["matchup_total"] = prob_matchup
    resultado["prob_matchup"] = round(prob_matchup, 4)
    
    # Rendimiento con equipo actual (25%)
    partidos_a_franq = [p for p in partidos_a if p.get("franquicia", "").upper() == franq_a.upper()]
    partidos_b_franq = [p for p in partidos_b if p.get("franquicia", "").upper() == franq_b.upper()]
    if partidos_a_franq and partidos_b_franq:
        peso_a_franq = sum(calcular_peso_fecha(p.get("fecha")) for p in partidos_a_franq)
        peso_b_franq = sum(calcular_peso_fecha(p.get("fecha")) for p in partidos_b_franq)
        win_rate_a = sum(calcular_peso_fecha(p.get("fecha")) for p in partidos_a_franq if p["gano"]) / peso_a_franq if peso_a_franq > 0 else 0.5
        win_rate_b = sum(calcular_peso_fecha(p.get("fecha")) for p in partidos_b_franq if p["gano"]) / peso_b_franq if peso_b_franq > 0 else 0.5
        prob_equipo = win_rate_a / (win_rate_a + win_rate_b) if (win_rate_a + win_rate_b) > 0 else 0.5
        resultado["winrate_a_franq"] = round(win_rate_a * 100, 1)
        resultado["winrate_b_franq"] = round(win_rate_b * 100, 1)
        resultado["partidos_a_franq"] = len(partidos_a_franq)
        resultado["partidos_b_franq"] = len(partidos_b_franq)
    else:
        prob_equipo = 0.5
        resultado["winrate_a_franq"] = None
        resultado["winrate_b_franq"] = None

        # Estadísticas defensivas
    todos_contra_a = [p["pts_contra"] for p in partidos_a]
    todos_contra_b = [p["pts_contra"] for p in partidos_b]
    contra_franq_a = [p["pts_contra"] for p in partidos_a_franq] if partidos_a_franq else []
    contra_franq_b = [p["pts_contra"] for p in partidos_b_franq] if partidos_b_franq else []
    avg_pts_a_temp = round(sum(p["pts_favor"] for p in partidos_a) / len(partidos_a), 1) if partidos_a else 60
    avg_pts_b_temp = round(sum(p["pts_favor"] for p in partidos_b) / len(partidos_b), 1) if partidos_b else 60
    avg_contra_a = round(sum(todos_contra_a) / len(todos_contra_a), 1) if todos_contra_a else None
    avg_contra_b = round(sum(todos_contra_b) / len(todos_contra_b), 1) if todos_contra_b else None
    avg_contra_a_franq = round(sum(contra_franq_a) / len(contra_franq_a), 1) if contra_franq_a else avg_contra_a
    avg_contra_b_franq = round(sum(contra_franq_b) / len(contra_franq_b), 1) if contra_franq_b else avg_contra_b

    # Stats API como fallback
    stats_liga = get_stats_liga()
    api_a = stats_liga.get(jugador_a.upper(), {})
    api_b = stats_liga.get(jugador_b.upper(), {})
    mp_a = api_a.get("matchesPlayed") or 0
    mp_b = api_b.get("matchesPlayed") or 0
    api_contra_a = round(api_a["pointsAgainst"] / mp_a, 1) if mp_a > 0 and api_a.get("pointsAgainst") else None
    api_contra_b = round(api_b["pointsAgainst"] / mp_b, 1) if mp_b > 0 and api_b.get("pointsAgainst") else None
    api_pts_a = api_a.get("avgPoints")
    api_pts_b = api_b.get("avgPoints")
    if avg_contra_a is None and api_contra_a:
        avg_contra_a = api_contra_a
    if avg_contra_b is None and api_contra_b:
        avg_contra_b = api_contra_b
    if avg_contra_a_franq is None and api_contra_a:
        avg_contra_a_franq = api_contra_a
    if avg_contra_b_franq is None and api_contra_b:
        avg_contra_b_franq = api_contra_b

    prob_api = calcular_prob_api(api_a, api_b)
    prob_api_val = prob_api if prob_api is not None else 0.5

    if partidos_a_franq:
        margenes_a = [p["pts_favor"] - p["pts_contra"] for p in partidos_a_franq]
    elif partidos_a:
        margenes_a = [p["pts_favor"] - p["pts_contra"] for p in partidos_a]
    else:
        margenes_a = [0]
    if partidos_b_franq:
        margenes_b = [p["pts_favor"] - p["pts_contra"] for p in partidos_b_franq]
    elif partidos_b:
        margenes_b = [p["pts_favor"] - p["pts_contra"] for p in partidos_b]
    else:
        margenes_b = [0]
    margen_avg_a = round(sum(margenes_a) / len(margenes_a), 1)
    margen_avg_b = round(sum(margenes_b) / len(margenes_b), 1)
    resultado["avg_contra_a"] = avg_contra_a
    resultado["avg_contra_b"] = avg_contra_b
    resultado["margen_avg_a"] = margen_avg_a
    resultado["margen_avg_b"] = margen_avg_b
    resultado["ou_defensa_a"] = avg_contra_a_franq
    resultado["ou_defensa_b"] = avg_contra_b_franq
    if avg_contra_a_franq and avg_contra_b_franq:
        ratio_a = avg_contra_a_franq / max(avg_pts_a_temp, 1)
        ratio_b = avg_contra_b_franq / max(avg_pts_b_temp, 1)
        prob_ratio = ratio_b / (ratio_a + ratio_b) if (ratio_a + ratio_b) > 0 else 0.5
        margen_diff = margen_avg_a - margen_avg_b
        prob_margen = 0.5 + min(max(margen_diff / 30, -0.25), 0.25)
        prob_defensa = round(prob_ratio * 0.6 + prob_margen * 0.4, 4)
        prob_defensa = max(0.2, min(0.8, prob_defensa))
        resultado["ratio_def_a"] = round(ratio_a, 3)
        resultado["ratio_def_b"] = round(ratio_b, 3)
    else:
        prob_defensa = 0.5
        resultado["ratio_def_a"] = None
        resultado["ratio_def_b"] = None
    resultado["prob_defensa"] = round(prob_defensa, 4)

    # Forma reciente (20%)
    recientes_a = partidos_a[:15]
    recientes_b = partidos_b[:15]
    if recientes_a and recientes_b:
        peso_a = sum(calcular_peso_fecha(p.get("fecha")) for p in recientes_a)
        peso_b = sum(calcular_peso_fecha(p.get("fecha")) for p in recientes_b)
        forma_a = sum(calcular_peso_fecha(p.get("fecha")) for p in recientes_a if p["gano"]) / peso_a if peso_a > 0 else 0.5
        forma_b = sum(calcular_peso_fecha(p.get("fecha")) for p in recientes_b if p["gano"]) / peso_b if peso_b > 0 else 0.5
        prob_forma = forma_a / (forma_a + forma_b) if (forma_a + forma_b) > 0 else 0.5
        resultado["forma_a"] = round(forma_a * 100, 1)
        resultado["forma_b"] = round(forma_b * 100, 1)
        resultado["racha_a"] = " ".join(["W" if p["gano"] else "L" for p in recientes_a[:10]])
        resultado["racha_b"] = " ".join(["W" if p["gano"] else "L" for p in recientes_b[:10]])
    else:
        prob_forma = 0.5
        resultado["forma_a"] = None
        resultado["forma_b"] = None

    # Tendencia reciente H2H (10%)
    h2h_reciente = partidos_h2h[:10]
    if h2h_reciente:
        peso_rec = sum(calcular_peso_fecha(p.get("fecha")) for p in h2h_reciente)
        wins_rec = sum(calcular_peso_fecha(p.get("fecha")) for p in h2h_reciente if p["gano_a"])
        if len(h2h_reciente) < 5:
            prob_h2h_rec = 0.5 + (wins_rec / peso_rec - 0.5) * 0.3 if peso_rec > 0 else 0.5
        else:
            prob_h2h_rec = wins_rec / peso_rec if peso_rec > 0 else 0.5
    else:
        prob_h2h_rec = 0.5

           # Probabilidad final ponderada
    pesos = cargar_pesos()
    w_h2h = pesos.get('h2h', 0.18)
    w_equipo = pesos.get('equipo', 0.16)
    w_forma = pesos.get('forma', 0.15)
    w_h2h_rec = pesos.get('h2h_rec', 0.11)
    w_matchup = pesos.get('matchup', 0.12)
    w_defensa = pesos.get('defensa', 0.18)
    w_api = pesos.get('api', 0.10)

    pocos_partidos_franq = (resultado.get("partidos_a_franq") or 0) < 5 or (resultado.get("partidos_b_franq") or 0) < 5
    if pocos_partidos_franq:
        reduccion = w_equipo * 0.65
        total_otros = w_h2h + w_forma + w_h2h_rec + w_matchup + w_defensa
        if total_otros > 0:
            w_h2h_f = w_h2h + reduccion * w_h2h / total_otros
            w_forma_f = w_forma + reduccion * w_forma / total_otros
            w_h2h_rec_f = w_h2h_rec + reduccion * w_h2h_rec / total_otros
            w_matchup_f = w_matchup + reduccion * w_matchup / total_otros
            w_defensa_f = w_defensa + reduccion * w_defensa / total_otros
            w_equipo_f = w_equipo * 0.35
        else:
            w_h2h_f, w_forma_f, w_h2h_rec_f, w_matchup_f, w_defensa_f, w_equipo_f = w_h2h, w_forma, w_h2h_rec, w_matchup, w_defensa, w_equipo
        prob_final_a = (prob_h2h * w_h2h_f) + (prob_equipo * w_equipo_f) + (prob_forma * w_forma_f) + (prob_h2h_rec * w_h2h_rec_f) + (prob_matchup * w_matchup_f) + (prob_defensa * w_defensa_f) + (prob_api_val * w_api)
    else:
        prob_final_a = (prob_h2h * w_h2h) + (prob_equipo * w_equipo) + (prob_forma * w_forma) + (prob_h2h_rec * w_h2h_rec) + (prob_matchup * w_matchup) + (prob_defensa * w_defensa) + (prob_api_val * w_api)
    prob_final_b = 1 - prob_final_a
    resultado["prob_a"] = round(prob_final_a, 4)
    resultado["prob_b"] = round(prob_final_b, 4)
    resultado["cuota_a"] = prob_to_odds(prob_final_a)
    resultado["cuota_b"] = prob_to_odds(prob_final_b)

    # Over/Under
    todos_pts_a = [p["pts_favor"] for p in partidos_a]
    todos_pts_b = [p["pts_favor"] for p in partidos_b]
    pts_totales_h2h = [p["pts_a"] + p["pts_b"] for p in partidos_h2h] if partidos_h2h else []

    recientes_pts_a = [p["pts_favor"] for p in partidos_a[:7]]
    recientes_pts_b = [p["pts_favor"] for p in partidos_b[:7]]

    pts_a_h2h_eq = [p["pts_a"] for p in h2h_equipos]
    pts_b_h2h_eq = [p["pts_b"] for p in h2h_equipos]

    if todos_pts_a:
        resultado["avg_pts_a"] = round(sum(todos_pts_a) / len(todos_pts_a), 1)
        resultado["std_pts_a"] = calcular_std(todos_pts_a)
    else:
        resultado["avg_pts_a"] = api_pts_a
        resultado["std_pts_a"] = 10 if api_pts_a else None

    if todos_pts_b:
        resultado["avg_pts_b"] = round(sum(todos_pts_b) / len(todos_pts_b), 1)
        resultado["std_pts_b"] = calcular_std(todos_pts_b)
    else:
        resultado["avg_pts_b"] = api_pts_b
        resultado["std_pts_b"] = 10 if api_pts_b else None

    if pts_totales_h2h:
        resultado["avg_total_h2h"] = round(sum(pts_totales_h2h) / len(pts_totales_h2h), 1)
    else:
        resultado["avg_total_h2h"] = None

    if resultado["avg_pts_a"] and resultado["avg_pts_b"]:
        avg_reciente_a = round(sum(recientes_pts_a) / len(recientes_pts_a), 1) if recientes_pts_a else resultado["avg_pts_a"]
        avg_reciente_b = round(sum(recientes_pts_b) / len(recientes_pts_b), 1) if recientes_pts_b else resultado["avg_pts_b"]

        avg_h2h_eq_a = round(sum(pts_a_h2h_eq) / len(pts_a_h2h_eq), 1) if pts_a_h2h_eq else resultado["avg_pts_a"]
        avg_h2h_eq_b = round(sum(pts_b_h2h_eq) / len(pts_b_h2h_eq), 1) if pts_b_h2h_eq else resultado["avg_pts_b"]

        adj_a = resultado["avg_pts_a"]
        adj_b = resultado["avg_pts_b"]
        if partidos_a_franq:
            pts_franq_a = [p["pts_favor"] for p in partidos_a_franq]
            adj_a = round(sum(pts_franq_a) / len(pts_franq_a), 1)
        if partidos_b_franq:
            pts_franq_b = [p["pts_favor"] for p in partidos_b_franq]
            adj_b = round(sum(pts_franq_b) / len(pts_franq_b), 1)

        std_a = resultado["std_pts_a"] or 5
        std_b = resultado["std_pts_b"] or 5
        consistencia_a = resultado["avg_pts_a"] * (1 - min(std_a / 100, 0.15))
        consistencia_b = resultado["avg_pts_b"] * (1 - min(std_b / 100, 0.15))

        avg_h2h_a = resultado.get("h2h_avg_a") or resultado["avg_pts_a"]
        avg_h2h_b = resultado.get("h2h_avg_b") or resultado["avg_pts_b"]
        avg_total_h2h = resultado["avg_total_h2h"] or (resultado["avg_pts_a"] + resultado["avg_pts_b"])

        linea_a = round(
            resultado["avg_pts_a"] * 0.25 +
            avg_h2h_a * 0.20 +
            consistencia_a * 0.10 +
            adj_a * 0.15 +
            avg_reciente_a * 0.20 +
            avg_h2h_eq_a * 0.10, 1)

        linea_b = round(
            resultado["avg_pts_b"] * 0.25 +
            avg_h2h_b * 0.20 +
            consistencia_b * 0.10 +
            adj_b * 0.15 +
            avg_reciente_b * 0.20 +
            avg_h2h_eq_b * 0.10, 1)

        if avg_contra_a_franq and avg_contra_b_franq:
            linea_def = round(((adj_a + avg_contra_b_franq) / 2) + ((adj_b + avg_contra_a_franq) / 2), 1)
        else:
            linea_def = round(adj_a + adj_b, 1)

        resultado["ou_h2h_total"] = avg_total_h2h if pts_totales_h2h else None
        resultado["ou_general"] = round(resultado["avg_pts_a"] + resultado["avg_pts_b"], 1)
        resultado["ou_franq"] = round(adj_a + adj_b, 1)
        resultado["ou_reciente"] = round(avg_reciente_a + avg_reciente_b, 1)
        resultado["ou_h2h_eq"] = round(avg_h2h_eq_a + avg_h2h_eq_b, 1) if pts_a_h2h_eq and pts_b_h2h_eq else None

        if todos_pts_a and resultado.get("avg_pts_a"):
            ultimos_a = todos_pts_a[:20]
            avg_ref_a = resultado["avg_pts_a"]
            over_pts_a = [p for p in ultimos_a if p > avg_ref_a]
            hist_a = sum(over_pts_a) / len(over_pts_a) if over_pts_a else avg_ref_a
        else:
            hist_a = resultado.get("avg_pts_a") or 0
        if todos_pts_b and resultado.get("avg_pts_b"):
            ultimos_b = todos_pts_b[:20]
            avg_ref_b = resultado["avg_pts_b"]
            over_pts_b = [p for p in ultimos_b if p > avg_ref_b]
            hist_b = sum(over_pts_b) / len(over_pts_b) if over_pts_b else avg_ref_b
        else:
            hist_b = resultado.get("avg_pts_b") or 0
        resultado["ou_historial"] = round(hist_a + hist_b, 4) if hist_a and hist_b else None
        avg_a = resultado.get("avg_pts_a") or 0
        avg_b = resultado.get("avg_pts_b") or 0
        if todos_pts_a and len(todos_pts_a) >= 10:
            tend_a = sum(todos_pts_a[:5]) / 5 - sum(todos_pts_a[:20]) / min(len(todos_pts_a), 20)
        else:
            tend_a = 0
        if todos_pts_b and len(todos_pts_b) >= 10:
            tend_b = sum(todos_pts_b[:5]) / 5 - sum(todos_pts_b[:20]) / min(len(todos_pts_b), 20)
        else:
            tend_b = 0
        resultado["ou_tendencia"] = round((avg_a + tend_a) + (avg_b + tend_b), 4) if avg_a and avg_b else None
        fb_a_api = api_a.get("avgFastBreakPoints")
        fb_b_api = api_b.get("avgFastBreakPoints")
        if fb_a_api and fb_b_api:
            resultado["ou_contraataque"] = round(fb_a_api + fb_b_api, 4)
        else:
            resultado["ou_contraataque"] = None

        mp_a_api = api_a.get("matchesPlayed") or 1
        mp_b_api = api_b.get("matchesPlayed") or 1
        contra_a_api = round(api_a["pointsAgainst"] / mp_a_api, 2) if api_a.get("pointsAgainst") else None
        contra_b_api = round(api_b["pointsAgainst"] / mp_b_api, 2) if api_b.get("pointsAgainst") else None
        print(f"[DEBUG deficit] contra_a={contra_a_api} contra_b={contra_b_api} keys_a={list(api_a.keys())[:5]}")
        if contra_a_api and contra_b_api:
            resultado["ou_deficit_def"] = round(contra_a_api + contra_b_api, 4)
        else:
            resultado["ou_deficit_def"] = None

        std_a_val = resultado.get("std_pts_a")
        std_b_val = resultado.get("std_pts_b")
        if std_a_val and std_b_val:
            resultado["ou_consistencia"] = round(std_a_val + std_b_val, 4)
        else:
            resultado["ou_consistencia"] = None
        fga_a = api_a.get("avgFieldGoalsAttempted") or 0
        fga_b = api_b.get("avgFieldGoalsAttempted") or 0
        to_a_api = api_a.get("avgTurnovers") or 0
        to_b_api = api_b.get("avgTurnovers") or 0
        orb_a = api_a.get("avgOffensiveRebounds") or 0
        orb_b = api_b.get("avgOffensiveRebounds") or 0
        fg_a_pct = (api_a.get("avgFieldGoalsPercent") or 0) / 100
        fg_b_pct = (api_b.get("avgFieldGoalsPercent") or 0) / 100
        if fga_a and fga_b and fg_a_pct and fg_b_pct:
            pos_a = fga_a + (to_a_api * 0.44) - orb_a
            pos_b = fga_b + (to_b_api * 0.44) - orb_b
            avg_pts_api_a = api_a.get("avgPoints")
            avg_pts_api_b = api_b.get("avgPoints")
            factor_a = avg_pts_api_a / (pos_a * fg_a_pct) if avg_pts_api_a and pos_a * fg_a_pct > 0 else 2.5
            factor_b = avg_pts_api_b / (pos_b * fg_b_pct) if avg_pts_api_b and pos_b * fg_b_pct > 0 else 2.5
            pts_est_a = pos_a * fg_a_pct * factor_a
            pts_est_b = pos_b * fg_b_pct * factor_b
            resultado["ou_ritmo"] = round(pts_est_a + pts_est_b, 4)
        else:
            resultado["ou_ritmo"] = None

        linea_api = calcular_linea_api(api_a, api_b)
        resultado["linea_api"] = linea_api
        pesos_ou = json.loads(get_meta("pesos_ou_optimizados") or "{}")
        w_h2h_ou = pesos_ou.get('h2h', 0.20)
        w_gen_ou = pesos_ou.get('general', 0.18)
        w_franq_ou = pesos_ou.get('franq', 0.15)
        w_rec_ou = pesos_ou.get('reciente', 0.18)
        w_def_ou = pesos_ou.get('defensa', 0.17)
        w_total = w_h2h_ou + w_gen_ou + w_franq_ou + w_rec_ou + w_def_ou
        if linea_api:
            w_api_ou = 0.12
            factor = 1.0 - w_api_ou
            linea_total = round(
                avg_total_h2h * (w_h2h_ou / w_total * factor) +
                (resultado["avg_pts_a"] + resultado["avg_pts_b"]) * (w_gen_ou / w_total * factor) +
                (adj_a + adj_b) * (w_franq_ou / w_total * factor) +
                (avg_reciente_a + avg_reciente_b) * (w_rec_ou / w_total * factor) +
                linea_def * (w_def_ou / w_total * factor) +
                linea_api * w_api_ou, 1)
        else:
            linea_total = round(
                avg_total_h2h * (w_h2h_ou / w_total) +
                (resultado["avg_pts_a"] + resultado["avg_pts_b"]) * (w_gen_ou / w_total) +
                (adj_a + adj_b) * (w_franq_ou / w_total) +
                (avg_reciente_a + avg_reciente_b) * (w_rec_ou / w_total) +
                linea_def * (w_def_ou / w_total), 1)

        confianza_over_a = 0.5 + (1 / (1 + std_a / 10)) * 0.20 if linea_a <= resultado["avg_pts_a"] else 0.5 - (1 / (1 + std_a / 10)) * 0.20
        confianza_a = max(0.40, min(0.75, confianza_over_a))
        confianza_over_b = 0.5 + (1 / (1 + std_b / 10)) * 0.20 if linea_b <= resultado["avg_pts_b"] else 0.5 - (1 / (1 + std_b / 10)) * 0.20
        confianza_b = max(0.40, min(0.75, confianza_over_b))
        avg_historico_total = resultado["avg_pts_a"] + resultado["avg_pts_b"]
        confianza_over_total = 0.5 + (1 / (1 + ((std_a + std_b) / 2) / 10)) * 0.18 if linea_total <= avg_historico_total else 0.5 - (1 / (1 + ((std_a + std_b) / 2) / 10)) * 0.18
        confianza_total = max(0.40, min(0.72, confianza_over_total))

        resultado["linea_a"] = linea_a
        resultado["linea_b"] = linea_b
        resultado["linea_total"] = linea_total
        resultado["over_a"] = prob_to_odds(confianza_a)
        resultado["under_a"] = prob_to_odds(1 - confianza_a)
        resultado["over_b"] = prob_to_odds(confianza_b)
        resultado["under_b"] = prob_to_odds(1 - confianza_b)
        resultado["over_total"] = prob_to_odds(confianza_total)
        resultado["under_total"] = prob_to_odds(1 - confianza_total)
        resultado["confianza"] = calcular_confianza(resultado, partidos_a, partidos_b)
        resultado["prob_h2h"] = round(prob_h2h, 4)
        resultado["prob_equipo"] = round(prob_equipo, 4)
        resultado["prob_h2h_eq"] = round(prob_h2h_eq, 4)
        resultado["prob_forma"] = round(prob_forma, 4)
        resultado["prob_h2h_rec"] = round(prob_h2h_rec, 4)
        resultado["prob_api"] = round(prob_api, 4) if prob_api is not None else None

    return resultado
# ─────────────────────────────────────────────
# FORMATO DE MENSAJES
# ─────────────────────────────────────────────

def formatear_analisis(jugador_a, franq_a, jugador_b, franq_b, analisis, betsson=None):
    msg = f"🏀 *{jugador_a} vs {jugador_b}*\n"
    msg += f"{franq_a} — {franq_b}\n\n"
    msg += f"━━━━━━━━━━━━━━━\n"
    msg += f"📈 *ANÁLISIS*\n"
    msg += f"━━━━━━━━━━━━━━━\n"

    total_h2h = analisis.get('h2h_total', 0)
    if total_h2h > 0:
        wins_a_real = analisis.get('h2h_wins_a_real', round(analisis.get('h2h_wins_a', 0)))
        wins_b_real = total_h2h - wins_a_real
        msg += f"*H2H:* {total_h2h} partidos → {jugador_a} {wins_a_real}W / {wins_b_real}L\n"
    else:
        msg += f"*H2H:* 0 partidos\n"

    h2h_equipos = analisis.get('h2h_equipos', 0)
    if h2h_equipos > 0:
        wins_eq_a = analisis.get('h2h_wins_eq_a', 0)
        wins_eq_b = h2h_equipos - wins_eq_a
        msg += f"*H2H mismos equipos:* {h2h_equipos} partidos → {wins_eq_a}-{wins_eq_b}\n"
    else:
        msg += f"*H2H mismos equipos:* 0 partidos\n"

    if analisis.get('matchup_total') is not None:
        matchup_pct = round(analisis['matchup_total'] * 100, 1)
        msg += f"*Matchup franquicias:* {franq_a} {matchup_pct}%\n"

    if analisis.get('racha_a') and analisis.get('racha_b'):
        racha_a = "-".join(analisis['racha_a'].split())
        racha_b = "-".join(analisis['racha_b'].split())
        msg += f"*Forma {jugador_a}:* {racha_a}\n"
        msg += f"*Forma {jugador_b}:* {racha_b}\n"
    elif analisis.get('forma_a') is not None:
        msg += f"*Forma {jugador_a}:* {analisis['forma_a']}%\n"
        msg += f"*Forma {jugador_b}:* {analisis['forma_b']}%\n"

    if analisis.get('winrate_a_franq') is not None:
        msg += f"*{jugador_a} con {franq_a}:* {analisis['winrate_a_franq']}% ({analisis['partidos_a_franq']} partidos)\n"
        msg += f"*{jugador_b} con {franq_b}:* {analisis['winrate_b_franq']}% ({analisis['partidos_b_franq']} partidos)\n"

    msg += f"\n━━━━━━━━━━━━━━━\n"
    msg += f"🎯 *GANADOR*\n"
    msg += f"━━━━━━━━━━━━━━━\n"
    espaciado = max(len(jugador_a), len(jugador_b)) + 2
    msg += f"{'':10}{jugador_a:<{espaciado}}{jugador_b}\n"
    msg += f"{'BOT:':10}{str(analisis['cuota_a']):<{espaciado}}{analisis['cuota_b']}\n"
    if betsson:
        cb_a = betsson.get('cuota_a')
        cb_b = betsson.get('cuota_b')
        if cb_a and cb_b:
            valor_a = " ✅" if cb_a > 0 and analisis['cuota_a'] > 0 and cb_a / analisis['cuota_a'] >= 1.25 and cb_a <= 2.50 else ""
            valor_b = " ✅" if cb_b > 0 and analisis['cuota_b'] > 0 and cb_b / analisis['cuota_b'] >= 1.25 and cb_b <= 2.50 else ""
            msg += f"{'BETSSON:':10}{str(cb_a) + valor_a:<{espaciado}}{cb_b}{valor_b}\n"

    if analisis.get('linea_total'):
        msg += f"\n━━━━━━━━━━━━━━━\n"
        msg += f"🔢 *TOTAL PUNTOS*\n"
        msg += f"━━━━━━━━━━━━━━━\n"
        msg += f"*BOT predice:* {analisis['linea_total']} pts\n"
        if betsson and betsson.get('linea_ou') and betsson.get('cuota_over'):
            bs_linea = betsson['linea_ou']
            bs_over = betsson['cuota_over']
            bs_under = betsson['cuota_under']
            linea_bot = analisis.get('linea_total')
            valor_ou = ""
            if linea_bot and bs_linea:
                try:
                    if abs(float(linea_bot) - float(bs_linea)) >= 8:
                        valor_ou = " ✅ VALOR OVER" if float(linea_bot) > float(bs_linea) else " ✅ VALOR UNDER"
                except:
                    pass
            msg += f"*BETSSON línea:* {bs_linea} pts\n"
            msg += f"Over `{bs_over}` / Under `{bs_under}`{valor_ou}\n"

    return msg

def generar_perfil_jugador(jugador, api, stats_liga):
    jugadores = list(stats_liga.values())
    def liga_avg(key):
        vals = [p.get(key) for p in jugadores if p.get(key) is not None]
        return sum(vals) / len(vals) if vals else None
    bl_pos   = liga_avg("avgTimeOfPossession") or 9.0
    bl_paint = liga_avg("avgPointsInThePaint") or 34.0
    bl_3pa   = liga_avg("avg3PointersAttempted") or 13.0
    bl_3pp   = liga_avg("threePointersPercent") or 42.0
    bl_fb    = liga_avg("avgFastBreakPoints") or 6.0
    bl_fg    = liga_avg("avgFieldGoalsPercent") or 48.0
    bl_pts   = liga_avg("avgPoints") or 55.0
    vals_contra = []
    for p in jugadores:
        mp_p = p.get("matchesPlayed") or 0
        pa = p.get("pointsAgainst")
        if pa and mp_p > 0:
            vals_contra.append(pa / mp_p)
    bl_contra = sum(vals_contra) / len(vals_contra) if vals_contra else None
    mp = api.get("matchesPlayed") or 1
    pts_contra = round(api["pointsAgainst"] / mp, 1) if api.get("pointsAgainst") and mp > 0 else None
    pos   = api.get("avgTimeOfPossession")
    paint = api.get("avgPointsInThePaint")
    t3a   = api.get("avg3PointersAttempted")
    t3p   = api.get("threePointersPercent")
    fb    = api.get("avgFastBreakPoints")
    ast   = api.get("avgAssists")
    to    = api.get("avgTurnovers")
    fg    = api.get("avgFieldGoalsPercent")
    pts   = api.get("avgPoints")
    wp    = api.get("matchesWinPct")
    blk   = api.get("avgBlocks")
    stl   = api.get("avgSteals")
    bl_triple_score = bl_3pa * bl_3pp / 100
    triple_score = (t3a * t3p / 100) if t3a and t3p else None
    ratio_astto = round(ast / to, 2) if ast and to and to > 0 else None
    # Clasificaciones
    es_rapido   = pos and pos < bl_pos * 0.88
    es_lento    = pos and pos > bl_pos * 1.12
    es_interior = paint and paint > bl_paint * 1.15
    es_tirador  = triple_score and triple_score > bl_triple_score * 1.20
    poco_triple = triple_score and triple_score < bl_triple_score * 0.70
    es_transicion = fb and fb > bl_fb * 1.25
    buen_distribuidor = ratio_astto and ratio_astto > 2.5
    muchas_perdidas   = ratio_astto and ratio_astto < 1.5
    buena_defensa = pts_contra and bl_contra and pts_contra < bl_contra * 0.90
    mala_defensa  = pts_contra and bl_contra and pts_contra > bl_contra * 1.10
    gran_anotador = pts and pts > bl_pts * 1.10
    poco_anotador = pts and pts < bl_pts * 0.90
    eficiente     = fg and (fg - bl_fg) > 3
    ineficiente   = fg and (fg - bl_fg) < -3
    # Tags rápidos
    tags = []
    if es_rapido: tags.append("⚡ Ritmo rápido")
    if es_lento:  tags.append("🐢 Ritmo lento")
    if es_interior: tags.append("🎨 Interior")
    if es_tirador:  tags.append("🎯 Tirador")
    if es_transicion: tags.append("🏃 Transición")
    if buena_defensa: tags.append("🛡️ Defensor")
    if buen_distribuidor: tags.append("🧠 Distribuidor")
    if gran_anotador: tags.append("💥 Anotador")
    msg = f"🏀 *{jugador}*\n"
    if tags:
        msg += " | ".join(tags) + "\n"
    msg += "\n"
    # Ataque
    msg += "⚔️ *Ataque*\n"
    if pos:
        if es_rapido:
            ritmo_txt = f"⚡ Rápido ({pos} seg posesión, liga {round(bl_pos,1)} seg)"
        elif es_lento:
            ritmo_txt = f"🐢 Lento ({pos} seg posesión, liga {round(bl_pos,1)} seg)"
        else:
            ritmo_txt = f"➡️ Medio ({pos} seg posesión, liga {round(bl_pos,1)} seg)"
        msg += f"• Posesión: {ritmo_txt}\n"
    if pts:
        if gran_anotador:
            msg += f"• Gran anotador: {round(pts,1)} pts/partido (liga {round(bl_pts,1)})\n"
        elif poco_anotador:
            msg += f"• Anotación baja: {round(pts,1)} pts/partido (liga {round(bl_pts,1)})\n"
        else:
            msg += f"• {round(pts,1)} pts/partido (en línea con la liga)\n"
    if paint:
        if es_interior:
            msg += f"• Domina en pintura: {round(paint,1)} pts (liga {round(bl_paint,1)})\n"
        elif paint < bl_paint * 0.85:
            msg += f"• Evita la zona, prefiere el exterior\n"
    if t3a and t3p:
        if es_tirador:
            msg += f"• Tirador de triple: {round(t3p,1)}% en {round(t3a,1)} intentos/partido\n"
        elif poco_triple:
            msg += f"• Casi no usa el triple ({round(t3a,1)} intentos, {round(t3p,1)}%)\n"
        else:
            msg += f"• Uso normal del triple ({round(t3p,1)}% / {round(t3a,1)} intentos)\n"
    if fb:
        if es_transicion:
            msg += f"• Muy activo en contraataque: {round(fb,1)} pts (liga {round(bl_fb,1)})\n"
        elif fb < bl_fb * 0.75:
            msg += f"• Poco juego en transición\n"
    if ast and to:
        if buen_distribuidor:
            msg += f"• Excelente con el balón: {round(ast,1)} ast y solo {round(to,1)} pérdidas\n"
        elif muchas_perdidas:
            msg += f"• Pierde mucho el balón: {round(ast,1)} ast pero {round(to,1)} pérdidas\n"
        else:
            msg += f"• Control de balón correcto: {round(ast,1)} ast / {round(to,1)} pérdidas\n"
    if fg:
        diff = round(fg - bl_fg, 1)
        if eficiente:
            msg += f"• Muy eficiente anotando: {round(fg,1)}% tiro (+{diff}% vs liga)\n"
        elif ineficiente:
            msg += f"• Poco eficiente: {round(fg,1)}% tiro ({diff}% vs liga)\n"
    # Defensa
    msg += "\n🛡️ *Defensa*\n"
    if pts_contra and bl_contra:
        if buena_defensa:
            msg += f"• Defensa sólida: recibe {pts_contra} pts de media (liga {round(bl_contra,1)})\n"
        elif mala_defensa:
            msg += f"• Defensa débil: recibe {pts_contra} pts de media (liga {round(bl_contra,1)})\n"
        else:
            msg += f"• Defensa normal: {pts_contra} pts recibidos (liga {round(bl_contra,1)})\n"
    if stl and stl > 4.0:
        msg += f"• Muy activo en robos: {round(stl,1)}/partido\n"
    elif stl:
        msg += f"• Robos: {round(stl,1)}/partido\n"
    if blk and blk > 1.5:
        msg += f"• Buen taponador: {round(blk,1)}/partido\n"
    # Rendimiento
    msg += "\n📊 *Rendimiento*\n"
    if wp:
        emoji_wp = "🟢" if wp > 55 else "🔴" if wp < 45 else "🟡"
        wp_txt = "por encima de la media" if wp > 55 else "por debajo de la media" if wp < 45 else "en la media"
        msg += f"• Win rate: {wp}% {emoji_wp} ({wp_txt})\n"
    # Resumen narrativo
    fortalezas = []
    debilidades = []
    if gran_anotador or eficiente: fortalezas.append("anotación")
    if es_tirador: fortalezas.append("triple")
    if buen_distribuidor: fortalezas.append("manejo del balón")
    if buena_defensa: fortalezas.append("defensa")
    if es_transicion: fortalezas.append("contraataque")
    if es_interior: fortalezas.append("juego interior")
    if ineficiente or poco_anotador: debilidades.append("eficiencia ofensiva")
    if muchas_perdidas: debilidades.append("pérdidas de balón")
    if mala_defensa: debilidades.append("defensa")
    if poco_triple and not es_interior: debilidades.append("amenaza exterior")
    msg += "\n💡 *Resumen:*\n"
    if fortalezas and debilidades:
        msg += f"Destaca en {', '.join(fortalezas)}. Su punto débil es {', '.join(debilidades)}."
    elif fortalezas:
        msg += f"Jugador sólido. Destaca en {', '.join(fortalezas)}. Sin debilidades claras."
    elif debilidades:
        msg += f"Jugador con margen de mejora en {', '.join(debilidades)}."
    else:
        msg += "Jugador equilibrado, sin características especialmente destacadas ni debilidades claras."
    return msg
    
# ─────────────────────────────────────────────
# COMANDOS TELEGRAM
# ─────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        await update.message.reply_text("No tienes acceso a este bot.")
        return
    total = total_partidos_db()
    ultima = get_meta("ultima_actualizacion") or get_meta("ultima_carga") or "Nunca"
    msg = (
        "🏀 *Bot H2H GG League*\n\n"
        f"📦 Partidos en base de datos: {total}\n"
        f"🕐 Última actualización: {ultima}\n\n"
        "Comandos disponibles:\n"
        "• `/pronostico JUGADORA vs JUGADORB` — análisis completo\n"
        "• `/h2h JUGADORA vs JUGADORB` — historial de enfrentamientos\n"
        "• `/stats JUGADOR` — estadísticas de un jugador\n"
        "• `/forma JUGADOR` — últimos 10 resultados\n"
        "• `/ranking` — top 20 jugadores por winrate\n"
        "• `/proximos` — próximos partidos\n"
        "• `/resultados` — últimos resultados\n"
        "• `/actualizar` — actualizar datos manualmente\n\n"
        "Ejemplo: `/pronostico MYTH vs MALICE`"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def proximos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        await update.message.reply_text("No tienes acceso a este bot.")
        return
    await update.message.reply_text("🔄 Consultando próximos partidos...")
    proximos_lista = get_upcoming_h2hggl()
    if not proximos_lista:
        await update.message.reply_text("No hay próximos partidos disponibles ahora mismo.")
        return
    cuotas = await get_cuotas_betsson()
    msg = "🏀 *Próximos partidos H2H GG League:*\n\n"
    for p in proximos_lista[:20]:
        ja = p["participantAName"].upper()
        jb = p["participantBName"].upper()
        franq_a = p.get("teamAName", "")
        franq_b = p.get("teamBName", "")
        try:
            hora = datetime.strptime(p["startDate"], "%Y-%m-%dT%H:%M:%SZ").strftime("%H:%M UTC")
        except:
            hora = "?? UTC"
        franq_txt = f" ({franq_a} vs {franq_b})" if franq_a and franq_b else ""
        has_cuota = f"{ja}_vs_{jb}" in cuotas or f"{jb}_vs_{ja}" in cuotas
        cuota_icon = " 💰" if has_cuota else ""
        msg += f"• {ja} vs {jb}{franq_txt} — {hora}{cuota_icon}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def resultados(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        await update.message.reply_text("No tienes acceso a este bot.")
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT home_name, away_name, score_home, score_away FROM partidos ORDER BY timestamp DESC LIMIT 8")
    rows = c.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("No hay resultados en la base de datos.")
        return
    msg = "🏀 *Últimos resultados H2H GG League:*\n\n"
    for row in rows:
        home, away, sc_h, sc_a = row
        msg += f"• {home} vs {away} — `{sc_h}-{sc_a}`\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        await update.message.reply_text("No tienes acceso a este bot.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /stats NOMBREJUGADOR\nEjemplo: /stats MYTH")
        return
    jugador = " ".join(context.args).upper()
    await update.message.reply_text(f"🔍 Buscando estadísticas de {jugador}...")

    partidos = buscar_partidos_jugador_db(jugador)
    stats_liga = get_stats_liga()
    api = stats_liga.get(jugador, {})

    if not partidos and not api:
        await update.message.reply_text(f"No encontré datos de {jugador}.")
        return

    msg = f"📊 *Estadísticas de {jugador}*\n\n"

    # Stats de la liga oficial (API)
    if api:
        mp = api.get("matchesPlayed") or 1
        avg_contra_api = round(api["pointsAgainst"] / mp, 1) if api.get("pointsAgainst") else None
        form_raw = api.get("matchForm", [])
        form_str = " ".join(["W" if r.lower() == "w" else "L" for r in form_raw[:10]]) if form_raw else "—"
        wins_form = sum(1 for r in form_raw[:10] if r.lower() == "w")

        msg += f"🌐 *Liga oficial ({mp} partidos totales)*\n"
        msg += f"• Victorias: {api.get('matchesWon', '?')} ({api.get('matchesWinPct', '?')}%)\n"
        msg += f"• Puntos: `{api.get('avgPoints', '?')}` avg"
        if avg_contra_api:
            msg += f" | Recibidos: `{avg_contra_api}` avg"
        msg += f"\n"
        if api.get("avgFieldGoalsPercent"):
            msg += f"• Tiro campo: {api['avgFieldGoalsPercent']}% ({api.get('avgFieldGoalsScored','?')} anotados)\n"
        if api.get("threePointersPercent"):
            msg += f"• Triples: {api['threePointersPercent']}% ({api.get('avg3PointersScored','?')} avg)\n"
        if api.get("freeThrowsPercent"):
            msg += f"• Libres: {api['freeThrowsPercent']}%\n"
        if api.get("avgAssists"):
            msg += f"• Asistencias: {api['avgAssists']} | Pérdidas: {api.get('avgTurnovers','?')}\n"
        if api.get("avgBlocks") or api.get("avgSteals"):
            msg += f"• Tapones: {api.get('avgBlocks','?')} | Robos: {api.get('avgSteals','?')}\n"
        if api.get("avgDefensiveRebounds") or api.get("avgOffensiveRebounds"):
            msg += f"• Reb DEF: {api.get('avgDefensiveRebounds','?')} | Reb OF: {api.get('avgOffensiveRebounds','?')}\n"
        if api.get("avgDunks"):
            msg += f"• Mates: {api['avgDunks']} avg\n"
        if api.get("avgBiggestLead"):
            msg += f"• Mayor ventaja media: {api['avgBiggestLead']} pts\n"
        msg += f"• Forma reciente: {form_str} ({wins_form}/10)\n"

    # Stats locales (DB)
    if partidos:
        total = len(partidos)
        victorias = sum(1 for p in partidos if p["gano"])
        avg_pts = round(sum(p["pts_favor"] for p in partidos) / total, 1)
        avg_contra = round(sum(p["pts_contra"] for p in partidos) / total, 1)
        std = calcular_std([p["pts_favor"] for p in partidos])
        recientes = partidos[:10]
        racha_str = " ".join(["W" if p["gano"] else "L" for p in recientes])
        msg += f"\n🗄️ *Base de datos local ({total} partidos)*\n"
        msg += f"• Victorias: {victorias} ({round(victorias/total*100,1)}%)\n"
        msg += f"• Puntos: `{avg_pts}` avg | Recibidos: `{avg_contra}` avg\n"
        msg += f"• Consistencia: ±{std} pts\n"
        msg += f"• Últimos 10: {racha_str}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")

async def h2h(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        await update.message.reply_text("No tienes acceso a este bot.")
        return
    texto = " ".join(context.args).upper()
    if "VS" not in texto:
        await update.message.reply_text("Uso: /h2h JUGADORA vs JUGADORB\nEjemplo: /h2h MYTH vs MALICE")
        return
    partes = texto.split("VS")
    jugador_a = partes[0].strip()
    jugador_b = partes[1].strip()
    await update.message.reply_text(f"🔍 Buscando historial {jugador_a} vs {jugador_b}...")
    partidos_h2h = buscar_historial_db(jugador_a, jugador_b)
    if not partidos_h2h:
        await update.message.reply_text(f"No encontré enfrentamientos entre {jugador_a} y {jugador_b}.")
        return
    wins_a = sum(1 for p in partidos_h2h if p["gano_a"])
    wins_b = len(partidos_h2h) - wins_a
    msg = f"🏀 *H2H {jugador_a} vs {jugador_b}*\n"
    msg += f"Total: {len(partidos_h2h)} partidos\n"
    msg += f"{jugador_a}: {wins_a}W/{wins_b}L\n"
    msg += f"{jugador_b}: {wins_b}W/{wins_a}L\n"
    avg_a = round(sum(p["pts_a"] for p in partidos_h2h) / len(partidos_h2h), 1)
    avg_b = round(sum(p["pts_b"] for p in partidos_h2h) / len(partidos_h2h), 1)
    avg_total = round(sum(p["pts_a"] + p["pts_b"] for p in partidos_h2h) / len(partidos_h2h), 1)
    msg += f"Promedio: {jugador_a} {avg_a} pts — {jugador_b} {avg_b} pts — Total {avg_total} pts\n\n"
    msg += f"📋 *Resultados:*\n"
    for i, p in enumerate(partidos_h2h, 1):
        ganador = jugador_a if p["gano_a"] else jugador_b
        fecha = p.get("fecha", "")
        msg += f"{i}. {jugador_a} ({p.get('franq_a','?')}) {p['pts_a']}—{p['pts_b']} {jugador_b} ({p.get('franq_b','?')}) ✅{ganador} {fecha}\n"
        if len(msg) > 3500:
            msg += "...(más partidos disponibles)\n"
            break
    await update.message.reply_text(msg, parse_mode="Markdown")

async def forma(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        await update.message.reply_text("No tienes acceso a este bot.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /forma JUGADOR\nEjemplo: /forma MYTH")
        return
    jugador = " ".join(context.args).upper()
    await update.message.reply_text(f"🔍 Buscando forma reciente de {jugador}...")
    partidos = buscar_partidos_jugador_db(jugador)
    if not partidos:
        await update.message.reply_text(f"No encontré partidos de {jugador}.")
        return
    recientes = partidos[:10]
    victorias = sum(1 for p in recientes if p["gano"])
    derrotas = len(recientes) - victorias
    avg_pts = round(sum(p["pts_favor"] for p in recientes) / len(recientes), 1)
    avg_total = round(sum(p["pts_favor"] + p["pts_contra"] for p in recientes) / len(recientes), 1)
    msg = f"📊 *Forma reciente de {jugador}*\n\n"
    msg += f"{victorias}W / {derrotas}L (últimos {len(recientes)})\n"
    msg += f"Promedio {jugador}: {avg_pts} pts\n"
    msg += f"Promedio total partido: {avg_total} pts\n\n"
    for i, p in enumerate(recientes, 1):
        icono = "✅" if p["gano"] else "❌"
        msg += f"{i}. {icono} {jugador} {p['pts_favor']} - {p['pts_contra']} ({p.get('fecha', '')})\n"
    await update.message.reply_text(msg, parse_mode="Markdown")
async def actualizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        await update.message.reply_text("No tienes acceso a este bot.")
        return
    await update.message.reply_text("🔄 Actualizando datos... esto puede tardar unos segundos.")
    total = actualizar_datos_hoy()
    total_db = total_partidos_db()
    await update.message.reply_text(f"✅ Actualización completada.\n• Partidos nuevos: {total}\n• Total en base de datos: {total_db}")

async def pronostico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        await update.message.reply_text("No tienes acceso a este bot.")
        return
    texto = " ".join(context.args).upper()
    if "VS" not in texto:
        await update.message.reply_text("Uso: /pronostico JUGADORA vs JUGADORB\nEjemplo: /pronostico MYTH vs MALICE")
        return
    partes = texto.split("VS")
    jugador_a = partes[0].strip()
    jugador_b = partes[1].strip()
    await update.message.reply_text(f"🔍 Analizando {jugador_a} vs {jugador_b}...")

    betsson_data = None
    franq_a = None
    franq_b = None

    # 1. Buscar franquicia en Betsson primero (tiene datos antes que BetsAPI)
    try:
        cuotas_betsson = await get_cuotas_betsson()
        key_ab = f"{jugador_a}_vs_{jugador_b}"
        key_ba = f"{jugador_b}_vs_{jugador_a}"
        raw = cuotas_betsson.get(key_ab) or cuotas_betsson.get(key_ba)
        if raw:
            invertido = key_ba in cuotas_betsson and key_ab not in cuotas_betsson
            if invertido:
                betsson_data = {
                    "cuota_a": raw["cuota_b"], "cuota_b": raw["cuota_a"],
                    "cuota_over": raw.get("cuota_over"), "cuota_under": raw.get("cuota_under"),
                    "linea_ou": raw.get("linea_ou"),
                    "franq_a": raw.get("franq_b"), "franq_b": raw.get("franq_a")
                }
            else:
                betsson_data = raw
            franq_a = betsson_data.get("franq_a")
            franq_b = betsson_data.get("franq_b")
    except:
        pass

    # 2. Si no está en Betsson, intentar BetsAPI
    if not franq_a:
        try:
            proximos_list = get_upcoming()
            for ev in proximos_list:
                home = ev.get("home", {}).get("name", "")
                away = ev.get("away", {}).get("name", "")
                nombre_home = extraer_nombre_jugador(home).upper()
                nombre_away = extraer_nombre_jugador(away).upper()
                if nombre_home == jugador_a and nombre_away == jugador_b:
                    franq_a = extraer_franquicia(home)
                    franq_b = extraer_franquicia(away)
                    break
                elif nombre_home == jugador_b and nombre_away == jugador_a:
                    franq_a = extraer_franquicia(away)
                    franq_b = extraer_franquicia(home)
                    break
        except:
            pass

    partidos_h2h = buscar_historial_db(jugador_a, jugador_b)
    partidos_a = buscar_partidos_jugador_db(jugador_a)
    partidos_b = buscar_partidos_jugador_db(jugador_b)

    # 3. Último recurso: último equipo conocido en DB
    if not franq_a:
        franq_a = partidos_a[0]["franquicia"] if partidos_a else "Equipo A"
    if not franq_b:
        franq_b = partidos_b[0]["franquicia"] if partidos_b else "Equipo B"

    analisis = analizar_partido(jugador_a, franq_a, jugador_b, franq_b, partidos_h2h, partidos_a, partidos_b)
    msg = formatear_analisis(jugador_a, franq_a, jugador_b, franq_b, analisis, betsson=betsson_data)
    await update.message.reply_text(msg, parse_mode="Markdown")

async def ranking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        await update.message.reply_text("No tienes acceso a este bot.")
        return
    await update.message.reply_text("🔍 Calculando ranking...")
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT home_jugador, COUNT(*) as total,
                 SUM(CASE WHEN score_home > score_away THEN 1 ELSE 0 END) as victorias
                 FROM partidos GROUP BY UPPER(home_jugador)
                 UNION ALL
                 SELECT away_jugador, COUNT(*) as total,
                 SUM(CASE WHEN score_away > score_home THEN 1 ELSE 0 END) as victorias
                 FROM partidos GROUP BY UPPER(away_jugador)''')
    rows = c.fetchall()
    conn.close()
    jugadores = {}
    for jugador, total, victorias in rows:
        j = jugador.upper()
        if j not in jugadores:
            jugadores[j] = {"total": 0, "victorias": 0}
        jugadores[j]["total"] += total
        jugadores[j]["victorias"] += victorias
    ranking_list = [
        (j, d["victorias"], d["total"], round(d["victorias"] / d["total"] * 100, 1))
        for j, d in jugadores.items()
        if d["total"] >= 50
    ]
    ranking_list.sort(key=lambda x: x[3], reverse=True)
    ranking_list = ranking_list[:20]
    msg = "🏆 *Ranking H2H GG League*\n\n"
    for i, (jugador, victorias, total, winrate) in enumerate(ranking_list, 1):
        msg += f"{i}. {jugador} — {winrate}%W ({total} partidos)\n"
    await update.message.reply_text(msg, parse_mode="Markdown")
    
async def rendimiento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        await update.message.reply_text("No tienes acceso a este bot.")
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM predicciones WHERE procesado = 1")
    total = c.fetchone()[0]
    if total == 0:
        await update.message.reply_text("No hay predicciones procesadas aún.")
        conn.close()
        return
    c.execute("SELECT SUM(acierto_ganador), SUM(acierto_ou) FROM predicciones WHERE procesado = 1")
    row = c.fetchone()
    aciertos_ganador = row[0] or 0
    aciertos_ou = row[1] or 0
    c.execute("SELECT acierto_ganador FROM predicciones WHERE procesado = 1 ORDER BY id DESC LIMIT 10")
    ultimos = c.fetchall()
    conn.close()
    racha = "-".join(["✅" if r[0] == 1 else "❌" for r in ultimos])
    msg = f"📊 *Rendimiento del bot*\n\n"
    msg += f"Total predicciones: {total}\n"
    msg += f"✅ Ganador acertado: {aciertos_ganador}/{total} → {round(aciertos_ganador/total*100, 1)}%\n"
    msg += f"✅ Over/Under acertado: {aciertos_ou}/{total} → {round(aciertos_ou/total*100, 1)}%\n\n"
    msg += f"Últimos 10: {racha}\n"
    conn2 = get_db()
    c2 = conn2.cursor()
    c2.execute('''SELECT DATE(fecha_prediccion) as dia, 
                 COUNT(*) as total,
                 SUM(acierto_ganador) as gan,
                 SUM(acierto_ou) as ou
                 FROM predicciones 
                 WHERE procesado = 1
                 GROUP BY dia 
                 ORDER BY dia DESC 
                 LIMIT 10''')
    dias = c2.fetchall()
    conn2.close()
    if dias:
        msg += f"\n📅 *Últimos 10 días:*\n"
        for dia, total, gan, ou in dias:
            gan = gan or 0
            ou = ou or 0
            msg += f"{dia}: {gan}/{total} ganador ({round(gan/total*100,1)}%) | {ou}/{total} O/U ({round(ou/total*100,1)}%)\n"
    # Stats de valor
    conn3 = get_db()
    c3 = conn3.cursor()
    c3.execute("SELECT COUNT(*), SUM(acierto_ganador), SUM(acierto_ou) FROM predicciones WHERE procesado=1 AND es_valor=1")
    rv = c3.fetchone()
    conn3.close()
    total_v = rv[0] or 0
    if total_v > 0:
        ag_v = rv[1] or 0
        aou_v = rv[2] or 0
        msg += f"\n🎯 *Predicciones con VALOR:*\n"
        msg += f"Total: {total_v}\n"
        msg += f"✅ Ganador: {ag_v}/{total_v} → {round(ag_v/total_v*100,1)}%\n"
        msg += f"✅ O/U: {aou_v}/{total_v} → {round(aou_v/total_v*100,1)}%\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def unidades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        await update.message.reply_text("No tienes acceso a este bot.")
        return
    conn = get_db()
    c = conn.cursor()
    reset_fecha = get_meta("reset_unidades") or "2000-01-01"
    c.execute('''SELECT ganador_predicho, resultado_real, acierto_ganador,
                 prediccion_ou, acierto_ou,
                 cuota_betsson_a, cuota_betsson_b,
                 cuota_betsson_over, cuota_betsson_under,
                 jugador_a, jugador_b, fecha_prediccion
                 FROM predicciones
                 WHERE procesado = 1
                   AND cuota_betsson_a IS NOT NULL
                   AND fecha_prediccion >= ?
                 ORDER BY id ASC''', (reset_fecha,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Aún no hay predicciones con líneas Betsson procesadas.")
        return
    unidades_ganador = 0.0
    unidades_ou = 0.0
    unidades_contra = 0.0
    aciertos_g = 0
    aciertos_ou = 0
    aciertos_contra = 0
    total = len(rows)
    racha_g = []
    racha_ou = []
    racha_contra = []
    for row in rows:
        gan_pred, res_real, ac_g, pred_ou, ac_ou, cb_a, cb_b, cb_over, cb_under, jug_a, jug_b, fecha = row
        # Ganador: cuota del jugador predicho
        if gan_pred == jug_a:
            cuota_g = cb_a or 0
        else:
            cuota_g = cb_b or 0
        if cuota_g and cuota_g > 1:
            if ac_g == 1:
                unidades_ganador += round(cuota_g - 1, 4)
                aciertos_g += 1
                racha_g.append("✅")
            else:
                unidades_ganador -= 1
                racha_g.append("❌")
        # Over/Under
        if pred_ou == "Over":
            cuota_ou = cb_over or 0
        else:
            cuota_ou = cb_under or 0
        if cuota_ou and cuota_ou > 1:
            if ac_ou == 1:
                unidades_ou += round(cuota_ou - 1, 4)
                aciertos_ou += 1
                racha_ou.append("✅")
            else:
                unidades_ou -= 1
                racha_ou.append("❌")
        cuota_contra = cb_under if pred_ou == "Over" else cb_over
        if cuota_contra and cuota_contra > 1:
            if ac_ou == 0:
                unidades_contra += round(cuota_contra - 1, 4)
                aciertos_contra += 1
                racha_contra.append("✅")
            elif ac_ou == 1:
                unidades_contra -= 1
                racha_contra.append("❌")
    unidades_ganador = round(unidades_ganador, 2)
    unidades_ou = round(unidades_ou, 2)
    emoji_g = "📈" if unidades_ganador >= 0 else "📉"
    emoji_ou = "📈" if unidades_ou >= 0 else "📉"
    ultimas_g = "".join(racha_g[-10:])
    ultimas_ou = "".join(racha_ou[-10:])
    msg = f"💰 *Simulación de unidades (1u por apuesta)*\n"
    msg += f"_(Solo predicciones con cuotas Betsson)_\n\n"
    msg += f"🏆 *GANADOR*\n"
    msg += f"Predicciones: {len(racha_g)} | Aciertos: {aciertos_g}\n"
    msg += f"Últimas 10: {ultimas_g}\n"
    msg += f"{emoji_g} Resultado: `{'+' if unidades_ganador >= 0 else ''}{unidades_ganador}u`\n\n"
    msg += f"🔢 *OVER/UNDER*\n"
    msg += f"Predicciones: {len(racha_ou)} | Aciertos: {aciertos_ou}\n"
    msg += f"Últimas 10: {ultimas_ou}\n"
    msg += f"{emoji_ou} Resultado: `{'+' if unidades_ou >= 0 else ''}{unidades_ou}u`\n\n"
    emoji_contra = "📈" if unidades_contra >= 0 else "📉"
    ultimas_contra = "".join(racha_contra[-10:])
    msg += f"🔄 *O/U A LA CONTRA (bot invertido):*\n"
    msg += f"Predicciones: {len(racha_contra)} | Aciertos: {aciertos_contra}\n"
    msg += f"Últimas 10: {ultimas_contra}\n"
    msg += f"{emoji_contra} Resultado: `{'+' if unidades_contra >= 0 else ''}{round(unidades_contra, 2)}u`\n"
    # Unidades solo de valor
    conn_v = get_db()
    c_v = conn_v.cursor()
    c_v.execute('''SELECT ganador_predicho, resultado_real, acierto_ganador,
                 prediccion_ou, acierto_ou,
                 cuota_betsson_a, cuota_betsson_b,
                 cuota_betsson_over, cuota_betsson_under,
                 jugador_a, jugador_b, es_valor_ganador, es_valor_ou
                 FROM predicciones
                 WHERE procesado=1 AND es_valor=1 AND cuota_betsson_a IS NOT NULL
                 AND fecha_prediccion >= ?
                 ORDER BY id ASC''', (reset_fecha,))
    rows_v = c_v.fetchall()
    conn_v.close()
    if rows_v:
        u_g = 0.0
        u_ou = 0.0
        for row in rows_v:
            gan_pred, res_real, ac_g, pred_ou, ac_ou, cb_a, cb_b, cb_over, cb_under, jug_a, jug_b, ev_g, ev_ou = row
            if ev_g:
                cuota_g = cb_a if gan_pred == jug_a else cb_b
                if cuota_g and cuota_g > 1:
                    u_g += round(cuota_g - 1, 4) if ac_g == 1 else -1
            if ev_ou:
                cuota_ou = cb_over if pred_ou == "Over" else cb_under
                if cuota_ou and cuota_ou > 1:
                    u_ou += round(cuota_ou - 1, 4) if ac_ou == 1 else -1
        u_g = round(u_g, 2)
        u_ou = round(u_ou, 2)
        n_g = sum(1 for r in rows_v if r[11])
        n_ou = sum(1 for r in rows_v if r[12])
        msg += f"\n🎯 *Solo predicciones VALOR:*\n"
        msg += f"🏆 Ganador: `{'+' if u_g >= 0 else ''}{round(u_g, 2)}u` ({n_g} apuestas)\n"
        msg += f"🔢 O/U: `{'+' if u_ou >= 0 else ''}{round(u_ou, 2)}u` ({n_ou} apuestas)\n"
    await update.message.reply_text(msg, parse_mode="Markdown")
    
async def test_coolbet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        return
    await update.message.reply_text("🔍 Probando scraping Coolbet...")
    cuotas = await get_cuotas_coolbet()
    if cuotas:
        msg = f"✅ Cuotas obtenidas: {len(cuotas)} partidos\n"
        for key, val in list(cuotas.items())[:3]:
            msg += f"• {val['home']} vs {val['away']}: {val['cuota_a']} / {val['cuota_b']}\n"
    else:
        msg = "❌ No se pudieron obtener cuotas"
    await update.message.reply_text(msg)

async def test_odds_api(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        return
    await update.message.reply_text("🔍 Buscando H2H GG en todas las ligas...")
    try:
        API_KEY = "4ffc305b73bbd6e19d68324799824ec0ab43628f68acc6332e137dafd01e45f4"
        for sport in ["basketball", "esports"]:
            r = requests.get(
                "https://api.odds-api.io/v3/events",
                params={"apiKey": API_KEY, "sport": sport, "status": "upcoming"},
                timeout=10
            )
            data = r.json()
            eventos = data if isinstance(data, list) else data.get("data", [])
            ligas = list(set([str(e.get("league", {}).get("name", "?")) for e in eventos]))
            gg = [l for l in ligas if "gg" in l.lower() or "h2h" in l.lower() or "ebasket" in l.lower() or "electronic" in l.lower()]
            if gg:
                await update.message.reply_text(f"✅ Encontrado en {sport}: {gg}")
                return
        await update.message.reply_text("❌ No encontrado en ningún sport")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

def guardar_cookies_betsson(cookies_str):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM betsson_cookies")
    c.execute("INSERT INTO betsson_cookies (cookies, timestamp) VALUES (?, ?)", 
              (cookies_str, int(datetime.utcnow().timestamp())))
    conn.commit()
    conn.close()

def cargar_cookies_betsson():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT cookies, timestamp FROM betsson_cookies ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    if row:
        cookies_str, ts = row
        if (datetime.utcnow().timestamp() - ts) < 14400:
            return cookies_str
    return None

async def renovar_cookies_betsson():
    try:
        print("Renovando cookies Betsson con Playwright...")
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
                locale="es-ES"
            )
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page = await context.new_page()
            await page.goto("https://www.betsson.es/apuestas-deportivas/baloncesto/ebasketball/liga-h2h-gg-de-baloncesto-electronico-4-x-5-minu?tab=liveAndUpcoming", wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(3000)
            cookies = await context.cookies()
            await browser.close()
            cookies_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            guardar_cookies_betsson(cookies_str)
            print(f"Cookies renovadas: {len(cookies)} cookies")
            return cookies_str
    except Exception as e:
        print(f"Error renovando cookies: {e}")
        return None

async def reset_unidades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        return
    set_meta("reset_unidades", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
    await update.message.reply_text("✅ Contador de unidades reseteado desde ahora.")
    
async def get_cuotas_betsson():
    try:
        cookies_str = cargar_cookies_betsson()
        if not cookies_str:
            cookies_str = await renovar_cookies_betsson()
        if not cookies_str:
            print("No se pudieron obtener cookies de Betsson")
            return {}

        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "es-ES,es;q=0.9",
            "brandid": "ff28e5bd-a193-4f34-9abe-af70ffbd1dbf",
            "content-type": "application/json",
            "correlationid": "9cac8414-b673-47e6-804b-2045ebaad389",
            "marketcode": "es",
            "referer": "https://www.betsson.es/apuestas-deportivas/baloncesto/ebasketball/liga-h2h-gg-de-baloncesto-electronico-4-x-5-minu?tab=liveAndUpcoming",
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "sessiontoken": "ew0KICAiYWxnIjogIkhTMjU2IiwNCiAgInR5cCI6ICJKV1QiDQp9.ew0KICAianVyaXNkaWN0aW9uIjogIlVua25vd24iLA0KICAidXNlcklkIjogIjExMTExMTExLTExMTEtMTExMS0xMTExLTExMTExMTExMTExMSIsDQogICJsb2dpblNlc3Npb25JZCI6ICIxMTExMTExMS0xMTExLTExMTEtMTExMS0xMTExMTExMTExMTEiDQp9.yuBO_qNKJHtbCWK3z04cEqU59EKU8pZb2kXHhZ7IeuI",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
            "x-obg-channel": "Web",
            "x-obg-device": "Desktop",
            "x-sb-app-version": "7.37.24.3502-r6766298",
            "x-sb-channel": "Web",
            "x-sb-content-id": "ff28e5bd-a193-4f34-9abe-af70ffbd1dbf",
            "x-sb-country-code": "ES",
            "x-sb-currency-code": "EUR",
            "x-sb-device-type": "Desktop",
            "x-sb-identifier": "EVENT_TABLE_REQUEST",
            "x-sb-jurisdiction": "Dgoj",
            "x-sb-language-code": "es",
            "x-sb-segment-id": "e136f587-21a6-47f4-a5e3-ebfc888bf590",
            "x-sb-static-context-id": "stc--1670310174",
            "x-sb-type": "b2b",
            "x-sb-user-context-id": "stc--1670310174",
            "cookie": cookies_str
        }
        cuotas = {}
        from datetime import timezone
        ahora = datetime.now(timezone.utc)
        manana = ahora + timedelta(hours=24)
        starts_after = ahora.strftime("%Y-%m-%dT%H:%M:%SZ")
        starts_before = manana.strftime("%Y-%m-%dT%H:%M:%SZ")
        url = f"https://www.betsson.es/api/sb/v1/widgets/events-table/v2?categoryIds=4&competitionIds=25847&eventPhase=Prematch&eventSortBy=StartDate&includeSkeleton=true&maxMarketCount=3&pageNumber=1&startsBefore={starts_before}&startsOnOrAfter={starts_after}&priceFormats=1"
        r = requests.get(url, headers=headers, timeout=25)
        if r.status_code != 200:
            print(f"Betsson status {r.status_code}, renovando cookies...")
            cookies_str = await renovar_cookies_betsson()
            if not cookies_str:
                return {}
            headers["cookie"] = cookies_str
            r = requests.get(url, headers=headers, timeout=25)
            if r.status_code != 200:
                return {}
        data = r.json()
        data_raw = data.get("data", {})
        events_list = data_raw.get("events", [])
        all_markets = data_raw.get("markets", [])
        for event in events_list:
            if not isinstance(event, dict):
                continue
            participants = event.get("participants", [])
            if len(participants) < 2:
                continue
            home = participants[0].get("label", "")
            away = participants[1].get("label", "")
            if not home or not away:
                continue
            if not cuotas:  # Solo para el primer evento
                print(f"DEBUG event keys: {list(event.keys())}")
            event_id = event.get("globalId", "").split(".")[-1]
            home_j = extraer_nombre_jugador(home).upper()
            away_j = extraer_nombre_jugador(away).upper()
            cuota_home = None
            cuota_away = None
            cuota_over = None
            cuota_under = None
            linea_ou = None

            # Market ganador
            market_obj = next((m for m in all_markets if m.get("eventId") == event_id and m.get("marketTemplateId") == "ESNMOWINNER2W"), None)
            if market_obj:
                market_id = market_obj.get("id", f"m-f-{event_id}-ESNMOWINNER2W")
                url_market = f"https://www.betsson.es/api/sb/v1/widgets/event-market/v1?includescoreboards=true&marketids={market_id}"
                r_market = requests.get(url_market, headers=headers, timeout=20)
                if r_market.status_code == 200:
                    mdata = r_market.json()
                    mselections = mdata.get("data", {}).get("marketSelections", [])
                    if len(mselections) >= 2:
                        cuota_home = mselections[0].get("odds")
                        cuota_away = mselections[1].get("odds")

            # Market over/under
            ou_obj = next((m for m in all_markets if m.get("eventId") == event_id and m.get("marketTemplateId") == "ESNMOTOTAL"), None)
            if ou_obj:
                linea_ou = ou_obj.get("lineValue")
                market_id_ou = ou_obj.get("id", f"m-f-{event_id}-MWOU-{linea_ou}")
                url_ou = f"https://www.betsson.es/api/sb/v1/widgets/event-market/v1?includescoreboards=true&marketids={market_id_ou}"
                r_ou = requests.get(url_ou, headers=headers, timeout=20)
                if r_ou.status_code == 200:
                    oudata = r_ou.json()
                    ouselections = oudata.get("data", {}).get("marketSelections", [])
                    if len(ouselections) >= 2:
                        cuota_over = ouselections[0].get("odds")
                        cuota_under = ouselections[1].get("odds")

            start_time = event.get("startDate", "")
            try:
                hora_utc_bs = datetime.strptime(start_time, "%Y-%m-%dT%H:%M:%SZ").strftime("%H:%M UTC")
            except:
                hora_utc_bs = "?? UTC"
            if cuota_home and cuota_away:
                cuotas[f"{home_j}_vs_{away_j}"] = {
                    "cuota_a": cuota_home,
                    "cuota_b": cuota_away,
                    "cuota_over": cuota_over,
                    "cuota_under": cuota_under,
                    "linea_ou": linea_ou,
                    "home": home_j,
                    "away": away_j,
                    "hora_utc": hora_utc_bs,
                    "franq_a": extraer_franquicia(home),
                    "franq_b": extraer_franquicia(away)
                }
        print(f"Cuotas Betsson obtenidas: {len(cuotas)} partidos")
        return cuotas
    except Exception as e:
        import traceback
        print(f"Error get_cuotas_betsson: {e}")
        print(traceback.format_exc())
        return {}


async def test_betsson(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        return
    await update.message.reply_text("🔍 Obteniendo cuotas Betsson...")
    cuotas = await get_cuotas_betsson()
    if cuotas:
        msg = f"✅ Cuotas obtenidas: {len(cuotas)} partidos\n"
        for k, v in list(cuotas.items())[:5]:
            ou_str = f" | O/U {v.get('linea_ou')}: {v.get('cuota_over')}/{v.get('cuota_under')}" if v.get('cuota_over') else ""
            msg += f"• {v['home']} vs {v['away']}: {v['cuota_a']} / {v['cuota_b']}{ou_str}\n"
    else:
        msg = "❌ No se pudieron obtener cuotas"
    await update.message.reply_text(msg[:4000])

async def renovar_cookies_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        return
    await update.message.reply_text("🔄 Renovando cookies de Betsson...")
    cookies_str = await renovar_cookies_betsson()
    if cookies_str:
        await update.message.reply_text("✅ Cookies renovadas correctamente")
    else:
        await update.message.reply_text("❌ Error renovando cookies")

async def optimizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _pesos_cache, _pesos_cache_ts
    if not es_permitido(update):
        await update.message.reply_text("No tienes acceso a este bot.")
        return
    await update.message.reply_text("🔍 Analizando predicciones pasadas...")
    pesos_actuales = cargar_pesos()
    resultado = calcular_pesos_optimos()
    if resultado[0] is None:
        await update.message.reply_text(f"❌ {resultado[1]}")
        return
    nuevos_pesos, accuracies, n_muestras = resultado
    set_meta("pesos_optimizados", json.dumps(nuevos_pesos))
    _pesos_cache = nuevos_pesos
    _pesos_cache_ts = time.time()
    nombres = {
        'h2h': 'H2H general',
        'equipo': 'Equipo actual',
        'forma': 'Forma reciente',
        'h2h_rec': 'H2H reciente',
        'matchup': 'Matchup franquicias',
        'defensa': 'Defensa',
        'api': 'Stats API liga'
    }
    msg = "✅ *Optimización completada*\n\n"
    msg += "📊 *Precisión por factor:*\n"
    for k in ['h2h', 'equipo', 'forma', 'h2h_rec', 'matchup', 'defensa', 'api']:
        n = n_muestras.get(k, 0)
        if n < 5:
            msg += f"⚪ {nombres[k]}: sin datos suficientes ({n} muestras)\n"
            continue
        acc = round(accuracies[k] * 100, 1)
        emoji = "🟢" if acc >= 55 else "🟡" if acc >= 50 else "🔴"
        msg += f"{emoji} {nombres[k]}: {acc}% ({n} muestras)\n"
    msg += "\n⚖️ *Pesos anteriores → Nuevos:*\n"
    for k in ['h2h', 'equipo', 'forma', 'h2h_rec', 'matchup', 'defensa', 'api']:
        ant = round(pesos_actuales.get(k, 0) * 100, 1)
        nuevo = round(nuevos_pesos[k] * 100, 1)
        cambio = "↑" if nuevos_pesos[k] > pesos_actuales.get(k, 0) else "↓" if nuevos_pesos[k] < pesos_actuales.get(k, 0) else "="
        msg += f"• {nombres[k]}: {ant}% {cambio} {nuevo}%\n"
    msg += "\n✅ Pesos activos en próximas predicciones"
    pesos_ou, accuracies_ou, n_ou = calcular_pesos_optimos_ou()
    if pesos_ou:
        pesos_ou_prev_str = get_meta("pesos_ou_optimizados") or "{}"
        set_meta("pesos_ou_optimizados", json.dumps(pesos_ou))
        nombres_ou = {'h2h': 'H2H total', 'reciente': 'Forma reciente', 'tendencia': 'Tendencia reciente',
                      'contraataque': 'Contraataque', 'deficit_def': 'Déficit defensivo'}
        pesos_ou_anteriores = json.loads(pesos_ou_prev_str)
        msg += "\n\n📊 *Precisión O/U por componente:*\n"
        for k in ['h2h', 'reciente', 'tendencia', 'contraataque', 'deficit_def']:
            n = n_ou.get(k, 0)
            if n < 10:
                msg += f"⚪ {nombres_ou[k]}: sin datos ({n})\n"
                continue
            acc = round(accuracies_ou[k] * 100, 1)
            emoji = "🟢" if acc >= 55 else "🟡" if acc >= 50 else "🔴"
            msg += f"{emoji} {nombres_ou[k]}: {acc}% ({n} muestras)\n"
        msg += "\n⚖️ *Pesos O/U anteriores → Nuevos:*\n"
        for k in ['h2h', 'reciente', 'tendencia', 'contraataque', 'deficit_def']:
            ant = round(pesos_ou_anteriores.get(k, 0) * 100, 1)
            nuevo = round(pesos_ou[k] * 100, 1)
            cambio = "↑" if pesos_ou[k] > pesos_ou_anteriores.get(k, 0) else "↓" if pesos_ou[k] < pesos_ou_anteriores.get(k, 0) else "="
            msg += f"• {nombres_ou[k]}: {ant}% {cambio} {nuevo}%\n"
    await update.message.reply_text(msg, parse_mode="Markdown")
    
async def debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM predicciones WHERE procesado=1")
    procesadas = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM predicciones WHERE procesado=0 AND cuota_betsson_a IS NOT NULL")
    pendientes_con_cuota = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM predicciones WHERE procesado=0 AND cuota_betsson_a IS NULL")
    pendientes_sin_cuota = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM predicciones WHERE procesado=1 AND es_valor=1")
    valor_procesadas = c.fetchone()[0]
    c.execute("SELECT jugador_a, jugador_b, fecha_prediccion FROM predicciones WHERE procesado=0 AND cuota_betsson_a IS NOT NULL ORDER BY id DESC LIMIT 5")
    c.execute("""SELECT jugador_a, jugador_b, fecha_prediccion, acierto_ganador, 
                 pts_real_a, pts_real_b FROM predicciones 
                 WHERE procesado=1 AND DATE(fecha_prediccion)=DATE('now') 
                 ORDER BY id DESC LIMIT 8""")
    recientes = c.fetchall()
    pendientes = c.fetchall()
    conn.close()
    msg = f"🔧 *Debug predicciones*\n\n"
    msg += f"✅ Procesadas: {procesadas}\n"
    msg += f"⏳ Pendientes con cuota Betsson: {pendientes_con_cuota}\n"
    msg += f"❌ Pendientes sin cuota Betsson: {pendientes_sin_cuota}\n"
    msg += f"🎯 Valor procesadas: {valor_procesadas}\n"
    if pendientes:
        msg += f"\n*Últimas pendientes con cuota:*\n"
        for ja, jb, fecha in pendientes:
            msg += f"• {ja} vs {jb} ({fecha[:10]})\n"
    if recientes:
        msg += f"\n*Procesadas hoy:*\n"
        for ja, jb, fecha, ac, pa, pb in recientes:
            ic = "✅" if ac == 1 else "❌" if ac == 0 else "?"
            score = f" ({pa}-{pb})" if pa is not None else ""
            msg += f"• {ic} {ja} vs {jb}{score} ({fecha[11:16]})\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def debugvalor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM predicciones WHERE procesado=1 AND es_valor=0")
    sin_valor = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM predicciones WHERE procesado=1 AND es_valor=1")
    con_valor = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM predicciones WHERE procesado=1 AND es_valor IS NULL")
    valor_null = c.fetchone()[0]
    conn.close()
    await update.message.reply_text(f"Procesadas sin valor: {sin_valor}\nProcesadas con valor: {con_valor}\nProcesadas valor NULL: {valor_null}")
        
async def mensaje_libre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        await update.message.reply_text("No tienes acceso a este bot.")
        return
    texto = update.message.text.upper()
    if " VS " in texto:
        partes = texto.split(" VS ")
        jugador_a = partes[0].strip()
        jugador_b = partes[1].strip()
        await update.message.reply_text(f"🔍 Analizando {jugador_a} vs {jugador_b}...")
        partidos_h2h = buscar_historial_db(jugador_a, jugador_b)
        partidos_a = buscar_partidos_jugador_db(jugador_a)
        partidos_b = buscar_partidos_jugador_db(jugador_b)
        franq_a = partidos_a[0]["franquicia"] if partidos_a else "Equipo A"
        franq_b = partidos_b[0]["franquicia"] if partidos_b else "Equipo B"
        analisis = analizar_partido(jugador_a, franq_a, jugador_b, franq_b, partidos_h2h, partidos_a, partidos_b)
        msg = formatear_analisis(jugador_a, franq_a, jugador_b, franq_b, analisis)
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text("Escribe algo como: *MYTH vs MALICE* o usa /pronostico MYTH vs MALICE", parse_mode="Markdown")

async def perfil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        await update.message.reply_text("No tienes acceso a este bot.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /perfil JUGADOR\nEjemplo: /perfil CHIEF")
        return
    jugador = " ".join(context.args).upper()
    await update.message.reply_text(f"🔍 Analizando perfil de {jugador}...")
    stats_liga = get_stats_liga()
    api = stats_liga.get(jugador)
    if not api:
        await update.message.reply_text(f"No encontré datos de {jugador} en la API de la liga.")
        return
    msg = generar_perfil_jugador(jugador, api, stats_liga)
    await update.message.reply_text(msg, parse_mode="Markdown")

async def pendientes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        await update.message.reply_text("No tienes acceso a este bot.")
        return
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT jugador_a, jugador_b, franq_a, franq_b,
                 linea_total, prediccion_ou,
                 prob_h2h, prob_equipo, prob_forma, prob_h2h_rec,
                 prob_matchup, prob_defensa, prob_api, fecha_prediccion
                 FROM predicciones
                 WHERE procesado=0
                 ORDER BY fecha_prediccion''')
    rows = c.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("No hay predicciones pendientes.")
        return
    msg = f"📋 *Predicciones pendientes ({len(rows)}):*\n\n"
    for r in rows:
        jugador_a, jugador_b, franq_a, franq_b, linea, pred, \
        p_h2h, p_equipo, p_forma, p_h2h_rec, p_matchup, p_defensa, p_api, fecha = r
        pred_icon = "⬆️" if pred == "Over" else "⬇️"
        franq_txt = f"_{franq_a} vs {franq_b}_\n" if franq_a and franq_b else ""
        msg += f"*{jugador_a} vs {jugador_b}*\n"
        msg += franq_txt
        msg += f"{pred_icon} {pred} {linea}\n"
        factores = []
        if p_h2h is not None: factores.append(f"H2H {round(p_h2h*100)}%")
        if p_equipo is not None: factores.append(f"Eq {round(p_equipo*100)}%")
        if p_forma is not None: factores.append(f"Forma {round(p_forma*100)}%")
        if p_h2h_rec is not None: factores.append(f"H2Hrec {round(p_h2h_rec*100)}%")
        if p_matchup is not None: factores.append(f"MQ {round(p_matchup*100)}%")
        if p_defensa is not None: factores.append(f"Def {round(p_defensa*100)}%")
        if p_api is not None: factores.append(f"API {round(p_api*100)}%")
        if factores:
            msg += " · ".join(factores) + "\n"
        probs = [p for p in [p_h2h, p_equipo, p_forma, p_h2h_rec, p_matchup, p_defensa, p_api] if p is not None]
        if probs:
            media = sum(probs) / 7
            factores_con_datos = sum(1 for p in probs if abs(p - 0.5) > 0.02)
            if media >= 0.60:
                conf_icon = "🟢 Alta"
            elif media >= 0.55:
                conf_icon = "🟡 Media"
            else:
                conf_icon = "⚪ Baja"
            msg += f"{conf_icon} — {factores_con_datos}/7 factores con datos\n"
        msg += "\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def schema(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        return
    conn = get_db()
    c = conn.cursor()
    c.execute("PRAGMA table_info(predicciones)")
    cols = [row[1] for row in c.fetchall()]
    conn.close()
    await update.message.reply_text("\n".join(cols))

async def debug_ou(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        return
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT linea_total, linea_betsson_ou, pts_real_a, pts_real_b
                 FROM predicciones
                 WHERE procesado=1
                 AND linea_betsson_ou IS NOT NULL
                 AND pts_real_a IS NOT NULL''')
    rows = c.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Sin datos suficientes.")
        return
    diffs_bot = []
    diffs_betsson = []
    for linea_bot, linea_bs, pts_a, pts_b in rows:
        total_real = pts_a + pts_b
        if linea_bot:
            diffs_bot.append(total_real - linea_bot)
        if linea_bs:
            diffs_betsson.append(total_real - linea_bs)
    avg_bot = round(sum(diffs_bot) / len(diffs_bot), 2) if diffs_bot else None
    avg_bs = round(sum(diffs_betsson) / len(diffs_betsson), 2) if diffs_betsson else None
    msg = f"📊 *Calibración O/U ({len(rows)} partidos)*\n\n"
    msg += f"Bot: predice {avg_bot:+} pts vs resultado real\n" if avg_bot else "Bot: sin datos\n"
    msg += f"Betsson: predice {avg_bs:+} pts vs resultado real\n" if avg_bs else "Betsson: sin datos\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def reset_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        return
    conn = get_db()
    conn.execute('''UPDATE predicciones SET es_valor=0, es_valor_ganador=0, es_valor_ou=0
                    WHERE enviado_canal IS NULL OR enviado_canal=0''')
    conn.commit()
    n = conn.execute("SELECT changes()").fetchone()[0]
    conn.close()
    await update.message.reply_text(f"✅ Reset completado: {n} predicciones limpiadas.")

async def debug_ou2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        return
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT COUNT(*) FROM predicciones 
                 WHERE procesado=1 AND linea_betsson_ou IS NOT NULL 
                 AND pts_real_a IS NOT NULL AND ou_h2h_total IS NOT NULL''')
    n = c.fetchone()[0]
    conn.close()
    await update.message.reply_text(f"Predicciones válidas para optimizar O/U: {n}")

async def debug_ou3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        return
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT prediccion_ou, acierto_ou, linea_total, linea_betsson_ou, pts_real_a, pts_real_b
                 FROM predicciones
                 WHERE procesado=1 AND linea_betsson_ou IS NOT NULL
                 AND pts_real_a IS NOT NULL AND acierto_ou IS NOT NULL''')
    rows = c.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Sin datos suficientes.")
        return
    total = len(rows)
    overs = [r for r in rows if r[0] == "Over"]
    unders = [r for r in rows if r[0] == "Under"]
    ac_over = sum(1 for r in overs if r[1] == 1)
    ac_under = sum(1 for r in unders if r[1] == 1)
    diffs_bot = [r[4] + r[5] - r[2] for r in rows if r[2]]
    diffs_bs = [r[4] + r[5] - r[3] for r in rows if r[3]]
    avg_diff_bot = round(sum(diffs_bot) / len(diffs_bot), 2) if diffs_bot else None
    avg_diff_bs = round(sum(diffs_bs) / len(diffs_bs), 2) if diffs_bs else None
    msg = f"🔍 *Análisis O/U ({total} partidos)*\n\n"
    msg += f"*Predicciones por dirección:*\n"
    msg += f"Over: {len(overs)} → {ac_over} acertados ({round(ac_over/len(overs)*100,1) if overs else 0}%)\n"
    msg += f"Under: {len(unders)} → {ac_under} acertados ({round(ac_under/len(unders)*100,1) if unders else 0}%)\n\n"
    msg += f"*Calibración de líneas:*\n"
    msg += f"Bot: {avg_diff_bot:+} pts vs resultado real\n" if avg_diff_bot else ""
    msg += f"Betsson: {avg_diff_bs:+} pts vs resultado real\n" if avg_diff_bs else ""
    await update.message.reply_text(msg, parse_mode="Markdown")

async def debug_historial_ou(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        return
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT ou_historial, acierto_ou FROM predicciones
                 WHERE procesado=1 AND ou_historial IS NOT NULL AND acierto_ou IS NOT NULL''')
    rows = c.fetchall()
    conn.close()
    over = [r for r in rows if r[0] > 0.5]
    under = [r for r in rows if r[0] <= 0.5]
    ac_over = sum(1 for r in over if r[1] == 1)
    ac_under = sum(1 for r in under if r[1] == 1)
    msg = f"🔍 *Debug Historial O/U ({len(rows)} muestras)*\n\n"
    msg += f"Predice Over ({len(over)}): {round(ac_over/len(over)*100,1) if over else 0}% acierto\n"
    msg += f"Predice Under ({len(under)}): {round(ac_under/len(under)*100,1) if under else 0}% acierto\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def debug_over(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not es_permitido(update):
        return
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT prediccion_ou, acierto_ou, linea_total, linea_betsson_ou,
                 ou_reciente, pts_real_a, pts_real_b
                 FROM predicciones
                 WHERE procesado=1 AND linea_betsson_ou IS NOT NULL
                 AND pts_real_a IS NOT NULL AND acierto_ou IS NOT NULL
                 AND prediccion_ou = 'Over' ''')
    rows = c.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("Sin datos suficientes.")
        return
    # Por tamaño de diferencia
    rangos = {'5-8': [], '8-12': [], '12+': []}
    for pred, ac, linea_bot, linea_bs, ou_rec, pts_a, pts_b in rows:
        if not linea_bot or not linea_bs:
            continue
        diff = abs(float(linea_bot) - float(linea_bs))
        if diff < 5:
            continue
        elif diff < 8:
            rangos['5-8'].append(ac)
        elif diff < 12:
            rangos['8-12'].append(ac)
        else:
            rangos['12+'].append(ac)
    # Cuando forma reciente coincide en Over
    con_forma = []
    sin_forma = []
    for pred, ac, linea_bot, linea_bs, ou_rec, pts_a, pts_b in rows:
        if not linea_bs or not ou_rec:
            continue
        forma_dice_over = float(ou_rec) > float(linea_bs)
        if forma_dice_over:
            con_forma.append(ac)
        else:
            sin_forma.append(ac)
    msg = f"🔍 *Debug Over ({len(rows)} predicciones)*\n\n"
    msg += f"*Por diferencia de línea:*\n"
    for rango, resultados in rangos.items():
        if resultados:
            acc = round(sum(resultados) / len(resultados) * 100, 1)
            msg += f"• {rango} pts: {acc}% ({len(resultados)} muestras)\n"
    msg += f"\n*Cuando forma reciente coincide en Over:*\n"
    if con_forma:
        acc = round(sum(con_forma) / len(con_forma) * 100, 1)
        msg += f"• Forma coincide: {acc}% ({len(con_forma)} muestras)\n"
    if sin_forma:
        acc = round(sum(sin_forma) / len(sin_forma) * 100, 1)
        msg += f"• Forma no coincide: {acc}% ({len(sin_forma)} muestras)\n"
    await update.message.reply_text(msg, parse_mode="Markdown")
    
# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import time
    time.sleep(15)
    init_db()
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM partidos WHERE score_home = 0 AND score_away = 0")
    conn.commit()
    conn.close()
    conn2 = get_db()
    conn2.execute("DELETE FROM predicciones WHERE procesado=0 AND cuota_betsson_a IS NULL")
    conn2.execute('''DELETE FROM predicciones WHERE procesado=0 AND id NOT IN (
        SELECT MIN(id) FROM predicciones 
        WHERE procesado=0
        GROUP BY jugador_a, jugador_b, DATE(fecha_prediccion)
    )''')
    conn2.commit()
    conn2.close()
    conn3 = get_db()
    conn3.execute('''DELETE FROM predicciones 
                     WHERE procesado=0 
                     AND datetime(fecha_prediccion) < datetime('now', '-24 hours')''')
    conn3.commit()
    conn3.close()
    print("Limpieza de predicciones completada")

    if total_partidos_db() == 0:
        print("Base de datos vacía, cargando datos iniciales...")
        cargar_datos_iniciales(meses=11)
    else:
        print(f"Base de datos lista con {total_partidos_db()} partidos.")

    async def post_init(application):
        asyncio.create_task(tarea_actualizacion_diaria())
        asyncio.create_task(tarea_predicciones_automaticas(application))

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("proximos", proximos))
    app.add_handler(CommandHandler("resultados", resultados))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("pronostico", pronostico))
    app.add_handler(CommandHandler("h2h", h2h))
    app.add_handler(CommandHandler("forma", forma))
    app.add_handler(CommandHandler("ranking", ranking))
    app.add_handler(CommandHandler("rendimiento", rendimiento))
    app.add_handler(CommandHandler("actualizar", actualizar))
    app.add_handler(CommandHandler("testbetsson", test_betsson))
    app.add_handler(CommandHandler("testcoolbet", test_coolbet))
    app.add_handler(CommandHandler("unidades", unidades))
    app.add_handler(CommandHandler("renovarcookies", renovar_cookies_cmd))
    app.add_handler(CommandHandler("debug", debug))
    app.add_handler(CommandHandler("resetunidades", reset_unidades))
    app.add_handler(CommandHandler("optimizar", optimizar))
    app.add_handler(CommandHandler("perfil", perfil))
    app.add_handler(CommandHandler("pendientes", pendientes))
    app.add_handler(CommandHandler("debugou", debug_ou))
    app.add_handler(CommandHandler("schema", schema))
    app.add_handler(CommandHandler("resetvalor", reset_valor))
    app.add_handler(CommandHandler("debugvalor", debugvalor))
    app.add_handler(CommandHandler("debugou2", debug_ou2))
    app.add_handler(CommandHandler("debugou3", debug_ou3))
    app.add_handler(CommandHandler("debughistou", debug_historial_ou))
    app.add_handler(CommandHandler("debugover", debug_over))
    app.add_handler(CommandHandler("testoapi", test_odds_api))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mensaje_libre))

    print("Bot iniciado...")
    app.run_polling()
