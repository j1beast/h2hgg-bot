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

TELEGRAM_TOKEN = "8917382762:AAGJI3_MKRiEe5nSb1uz56Q-fJYfIchzWuQ"
BETSAPI_TOKEN = "255743-DXkD4nrqNqXhJq"
LEAGUE_ID = "25067"
SPORT_ID = "18"
BASE_URL = "https://api.b365api.com"
DB_PATH = "/app/data/cache.db"
USUARIOS_PERMITIDOS = [7339330267, 1021947497, 409760550, 1316315194, 1478076850]
def es_permitido(update):
    return update.effective_user.id in USUARIOS_PERMITIDOS
    
# ─────────────────────────────────────────────
# BASE DE DATOS
# ─────────────────────────────────────────────

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
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
        fecha_prediccion TEXT,
        resultado_real TEXT,
        acierto_ganador INTEGER,
        acierto_ou INTEGER,
        procesado INTEGER DEFAULT 0
    )''')
    conn.commit()
    conn.close()

def get_db():
    return sqlite3.connect(DB_PATH)

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
    r = requests.get(f"{BASE_URL}/v1/events/upcoming?sport_id={SPORT_ID}&league_id={LEAGUE_ID}&token={BETSAPI_TOKEN}", timeout=10)
    return r.json().get("results", [])

def get_ended(page=1, day=None):
    url = f"{BASE_URL}/v3/events/ended?sport_id={SPORT_ID}&league_id={LEAGUE_ID}&token={BETSAPI_TOKEN}&page={page}"
    if day:
        url += f"&day={day}"
    r = requests.get(url, timeout=10)
    return r.json().get("results", [])

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
    print(f"Actualización diaria: {total} partidos nuevos")
    return total

async def tarea_actualizacion_diaria():
    while True:
        now = datetime.utcnow()
        manana_4am = datetime(now.year, now.month, now.day, 4, 0, 0) + timedelta(days=1)
        segundos = (manana_4am - now).total_seconds()
        await asyncio.sleep(segundos)
        actualizar_datos_hoy()

def guardar_prediccion(jugador_a, franq_a, jugador_b, franq_b, analisis):
    conn = get_db()
    c = conn.cursor()
    ganador = jugador_a if analisis["prob_a"] > analisis["prob_b"] else jugador_b
    cuota_ganador = analisis["cuota_a"] if analisis["prob_a"] > analisis["prob_b"] else analisis["cuota_b"]
    c.execute('''INSERT OR IGNORE INTO predicciones
        (jugador_a, jugador_b, franq_a, franq_b, ganador_predicho, cuota_ganador, linea_total, cuota_over, cuota_under, fecha_prediccion, procesado)
        VALUES (?,?,?,?,?,?,?,?,?,?,0)''',
        (jugador_a, jugador_b, franq_a, franq_b, ganador, cuota_ganador,
         analisis.get("linea_total"), analisis.get("over_total"), analisis.get("under_total"),
         datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def verificar_predicciones():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, jugador_a, jugador_b, ganador_predicho, linea_total FROM predicciones WHERE procesado = 0")
    pendientes = c.fetchall()
    for pred_id, jugador_a, jugador_b, ganador_predicho, linea_total in pendientes:
        partidos_h2h = buscar_historial_db(jugador_a, jugador_b)
        if not partidos_h2h:
            continue
        ultimo = partidos_h2h[0]
        fecha_pred = None
        c.execute("SELECT fecha_prediccion FROM predicciones WHERE id=?", (pred_id,))
        row = c.fetchone()
        if row:
            fecha_pred = row[0]
        if not fecha_pred:
            continue
        fecha_pred_dt = datetime.strptime(fecha_pred, "%Y-%m-%d %H:%M:%S")
        if ultimo.get("fecha") and ultimo["fecha"] >= fecha_pred_dt.strftime("%Y-%m-%d"):
            ganador_real = jugador_a if ultimo["gano_a"] else jugador_b
            acierto_ganador = 1 if ganador_real == ganador_predicho else 0
            total_real = ultimo["pts_a"] + ultimo["pts_b"]
            acierto_ou = 1 if (linea_total and total_real > linea_total) else 0
            c.execute('''UPDATE predicciones SET resultado_real=?, acierto_ganador=?, acierto_ou=?, procesado=1
                         WHERE id=?''', (ganador_real, acierto_ganador, acierto_ou, pred_id))
    conn.commit()
    conn.close()

async def tarea_predicciones_automaticas():
    while True:
        try:
            proximos = get_upcoming()
            for ev in proximos:
                home = ev.get("home", {}).get("name", "")
                away = ev.get("away", {}).get("name", "")
                jugador_a = extraer_nombre_jugador(home).upper()
                jugador_b = extraer_nombre_jugador(away).upper()
                franq_a = extraer_franquicia(home)
                franq_b = extraer_franquicia(away)
                partidos_h2h = buscar_historial_db(jugador_a, jugador_b)
                partidos_a = buscar_partidos_jugador_db(jugador_a)
                partidos_b = buscar_partidos_jugador_db(jugador_b)
                if partidos_a and partidos_b:
                    analisis = analizar_partido(jugador_a, franq_a, jugador_b, franq_b, partidos_h2h, partidos_a, partidos_b)
                    guardar_prediccion(jugador_a, franq_a, jugador_b, franq_b, analisis)
            verificar_predicciones()
        except Exception as e:
            print(f"Error en predicciones automáticas: {e}")
        await asyncio.sleep(1800)  # 30 minutos
        
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

def prob_to_odds(prob):
    if prob <= 0 or prob >= 1:
        return 1.01
    margen = 1.06
    return round(1 / (prob * margen), 2)

def calcular_std(valores):
    if len(valores) < 2:
        return 0
    return round(statistics.stdev(valores), 1)
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

    if porcentaje >= 0.75:
        return "🟢 Alta"
    elif porcentaje >= 0.45:
        return "🟡 Media"
    else:
        return "🔴 Baja"
        
def analizar_partido(jugador_a, franq_a, jugador_b, franq_b, partidos_h2h, partidos_a, partidos_b):
    resultado = {}
    # H2H histórico general (25%)
    if partidos_h2h:
        wins_a = sum(1 for p in partidos_h2h if p["gano_a"])
        total_h2h = len(partidos_h2h)
        prob_h2h = wins_a / total_h2h
        pts_a_h2h = [p["pts_a"] for p in partidos_h2h]
        pts_b_h2h = [p["pts_b"] for p in partidos_h2h]
        resultado["h2h_total"] = total_h2h
        resultado["h2h_wins_a"] = wins_a
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

    # Rendimiento con equipo actual (25%)
    partidos_a_franq = [p for p in partidos_a if p.get("franquicia", "").upper() == franq_a.upper()]
    partidos_b_franq = [p for p in partidos_b if p.get("franquicia", "").upper() == franq_b.upper()]
    if partidos_a_franq and partidos_b_franq:
        win_rate_a = sum(1 for p in partidos_a_franq if p["gano"]) / len(partidos_a_franq)
        win_rate_b = sum(1 for p in partidos_b_franq if p["gano"]) / len(partidos_b_franq)
        prob_equipo = win_rate_a / (win_rate_a + win_rate_b) if (win_rate_a + win_rate_b) > 0 else 0.5
        resultado["winrate_a_franq"] = round(win_rate_a * 100, 1)
        resultado["winrate_b_franq"] = round(win_rate_b * 100, 1)
        resultado["partidos_a_franq"] = len(partidos_a_franq)
        resultado["partidos_b_franq"] = len(partidos_b_franq)
    else:
        prob_equipo = 0.5
        resultado["winrate_a_franq"] = None
        resultado["winrate_b_franq"] = None

    # Forma reciente (20%)
    recientes_a = partidos_a[:15]
    recientes_b = partidos_b[:15]
    if recientes_a and recientes_b:
        forma_a = sum(1 for p in recientes_a if p["gano"]) / len(recientes_a)
        forma_b = sum(1 for p in recientes_b if p["gano"]) / len(recientes_b)
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
        wins_rec = sum(1 for p in h2h_reciente if p["gano_a"])
        prob_h2h_rec = wins_rec / len(h2h_reciente)
    else:
        prob_h2h_rec = 0.5

    # Probabilidad final ponderada
    pocos_partidos_franq = (resultado.get("partidos_a_franq") or 0) < 5 or (resultado.get("partidos_b_franq") or 0) < 5
    if pocos_partidos_franq:
        prob_final_a = (prob_h2h * 0.30) + (prob_equipo * 0.10) + (prob_h2h_eq * 0.20) + (prob_forma * 0.25) + (prob_h2h_rec * 0.15)
    else:
        prob_final_a = (prob_h2h * 0.25) + (prob_equipo * 0.25) + (prob_h2h_eq * 0.20) + (prob_forma * 0.20) + (prob_h2h_rec * 0.10)
    prob_final_b = 1 - prob_final_a
    resultado["prob_a"] = round(prob_final_a, 4)
    resultado["prob_b"] = round(prob_final_b, 4)
    resultado["cuota_a"] = prob_to_odds(prob_final_a)
    resultado["cuota_b"] = prob_to_odds(prob_final_b)

    # Over/Under
    todos_pts_a = [p["pts_favor"] for p in partidos_a]
    todos_pts_b = [p["pts_favor"] for p in partidos_b]
    pts_totales_h2h = [p["pts_a"] + p["pts_b"] for p in partidos_h2h] if partidos_h2h else []

    # Forma reciente de anotación (últimos 7 partidos)
    recientes_pts_a = [p["pts_favor"] for p in partidos_a[:7]]
    recientes_pts_b = [p["pts_favor"] for p in partidos_b[:7]]

    # H2H con mismos equipos - puntos
    pts_a_h2h_eq = [p["pts_a"] for p in h2h_equipos]
    pts_b_h2h_eq = [p["pts_b"] for p in h2h_equipos]

    if todos_pts_a:
        resultado["avg_pts_a"] = round(sum(todos_pts_a) / len(todos_pts_a), 1)
        resultado["std_pts_a"] = calcular_std(todos_pts_a)
    else:
        resultado["avg_pts_a"] = None
        resultado["std_pts_a"] = None

    if todos_pts_b:
        resultado["avg_pts_b"] = round(sum(todos_pts_b) / len(todos_pts_b), 1)
        resultado["std_pts_b"] = calcular_std(todos_pts_b)
    else:
        resultado["avg_pts_b"] = None
        resultado["std_pts_b"] = None

    if pts_totales_h2h:
        resultado["avg_total_h2h"] = round(sum(pts_totales_h2h) / len(pts_totales_h2h), 1)
    else:
        resultado["avg_total_h2h"] = None

    if resultado["avg_pts_a"] and resultado["avg_pts_b"]:
        # Forma reciente anotación
        avg_reciente_a = round(sum(recientes_pts_a) / len(recientes_pts_a), 1) if recientes_pts_a else resultado["avg_pts_a"]
        avg_reciente_b = round(sum(recientes_pts_b) / len(recientes_pts_b), 1) if recientes_pts_b else resultado["avg_pts_b"]

        # H2H mismos equipos puntos
        avg_h2h_eq_a = round(sum(pts_a_h2h_eq) / len(pts_a_h2h_eq), 1) if pts_a_h2h_eq else resultado["avg_pts_a"]
        avg_h2h_eq_b = round(sum(pts_b_h2h_eq) / len(pts_b_h2h_eq), 1) if pts_b_h2h_eq else resultado["avg_pts_b"]

        # Ajuste equipo actual
        adj_a = resultado["avg_pts_a"]
        adj_b = resultado["avg_pts_b"]
    if partidos_a_franq:
        pts_franq_a = [p["pts_favor"] for p in partidos_a_franq]
        adj_a = round(sum(pts_franq_a) / len(pts_franq_a), 1)
    if partidos_b_franq:
        pts_franq_b = [p["pts_favor"] for p in partidos_b_franq]
        adj_b = round(sum(pts_franq_b) / len(pts_franq_b), 1)

        # Línea ponderada jugador A: 25% histórico + 20% h2h total + 10% consistencia + 15% equipo actual + 20% forma reciente + 10% h2h mismos equipos
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

        linea_total = round(
            avg_total_h2h * 0.30 +
            (resultado["avg_pts_a"] + resultado["avg_pts_b"]) * 0.18 +
            (consistencia_a + consistencia_b) * 0.10 +
            (adj_a + adj_b) * 0.15 +
            (avg_reciente_a + avg_reciente_b) * 0.17 +
            (avg_h2h_eq_a + avg_h2h_eq_b) * 0.10, 1)
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

    return resultado

# ─────────────────────────────────────────────
# FORMATO DE MENSAJES
# ─────────────────────────────────────────────

def formatear_analisis(jugador_a, franq_a, jugador_b, franq_b, analisis):
    msg = f"🏀 *{jugador_a} ({franq_a}) vs {jugador_b} ({franq_b})*\n\n"
    msg += f"📊 *Datos analizados:*\n"

    total_h2h = analisis.get('h2h_total', 0)
    if total_h2h > 0:
        wins_a = analisis.get('h2h_wins_a', 0)
        wins_b = total_h2h - wins_a
        msg += f"• H2H: {total_h2h} partidos — {jugador_a} {wins_a}W/{wins_b}L vs {jugador_b} {wins_b}W/{wins_a}L\n"
    else:
        msg += f"• H2H: 0 partidos\n"

    h2h_equipos = analisis.get('h2h_equipos', 0)
    if h2h_equipos > 0:
        wins_eq_a = analisis.get('h2h_wins_eq_a', 0)
        wins_eq_b = h2h_equipos - wins_eq_a
        msg += f"• H2H con estos equipos: {h2h_equipos} partidos — {jugador_a} {wins_eq_a}W/{wins_eq_b}L vs {jugador_b} {wins_eq_b}W/{wins_eq_a}L\n"
    else:
        msg += f"• H2H con estos equipos: 0 partidos\n"

    if analisis.get('racha_a') and analisis.get('racha_b'):
        racha_a = "-".join(analisis['racha_a'].split())
        racha_b = "-".join(analisis['racha_b'].split())
        msg += f"• Forma reciente {jugador_a}: {racha_a}\n"
        msg += f"• Forma reciente {jugador_b}: {racha_b}\n"
    elif analisis.get('forma_a') is not None:
        msg += f"• Forma reciente {jugador_a}: {analisis['forma_a']}% victorias\n"
        msg += f"• Forma reciente {jugador_b}: {analisis['forma_b']}% victorias\n"

    if analisis.get('winrate_a_franq') is not None:
        msg += f"• {jugador_a} con {franq_a}: {analisis['winrate_a_franq']}% victorias ({analisis['partidos_a_franq']} partidos)\n"
        msg += f"• {jugador_b} con {franq_b}: {analisis['winrate_b_franq']}% victorias ({analisis['partidos_b_franq']} partidos)\n"

    msg += f"\n🔮 *Confianza predicción: {analisis.get('confianza', 'N/A')}*\n"
    msg += f"\n🎯 *GANADOR*\n"
    msg += f"{jugador_a}: `{analisis['cuota_a']}` — {jugador_b}: `{analisis['cuota_b']}`\n"

    if analisis.get('linea_total'):
        msg += f"\n🔢 *TOTAL DEL PARTIDO*\n"
        msg += f"Línea: {analisis['linea_total']} pts\n"
        msg += f"Over `{analisis['over_total']}` / Under `{analisis['under_total']}`\n"

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
    await update.message.reply_text("🔍 Consultando próximos partidos...")
    partidos = get_upcoming()
    if not partidos:
        await update.message.reply_text("No hay próximos partidos disponibles ahora mismo.")
        return
    msg = "🏀 *Próximos partidos H2H GG League:*\n\n"
    for ev in partidos[:8]:
        home = ev.get("home", {}).get("name", "?")
        away = ev.get("away", {}).get("name", "?")
        t = ev.get("time", "")
        hora = datetime.utcfromtimestamp(int(t)).strftime("%H:%M") if t else "?"
        msg += f"• {home} vs {away} — {hora} UTC\n"
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
    if not partidos:
        await update.message.reply_text(f"No encontré partidos de {jugador} en la base de datos.")
        return
    total = len(partidos)
    victorias = sum(1 for p in partidos if p["gano"])
    derrotas = total - victorias
    avg_pts = round(sum(p["pts_favor"] for p in partidos) / total, 1)
    avg_contra = round(sum(p["pts_contra"] for p in partidos) / total, 1)
    std = calcular_std([p["pts_favor"] for p in partidos])
    recientes = partidos[:10]
    racha = sum(1 for p in recientes if p["gano"])
    racha_str = "-".join(["W" if p["gano"] else "L" for p in recientes])
    msg = (
        f"📊 *Estadísticas de {jugador}*\n\n"
        f"• Partidos: {total}\n"
        f"• Victorias: {victorias} ({round(victorias/total*100,1)}%)\n"
        f"• Derrotas: {derrotas}\n"
        f"• Promedio puntos: {avg_pts}\n"
        f"• Promedio recibidos: {avg_contra}\n"
        f"• Consistencia: ±{std} pts\n"
        f"• Últimos 10: {racha_str}\n"
    )
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

    # Buscar equipos en próximos partidos
    franq_a = None
    franq_b = None
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

    if not franq_a:
        franq_a = partidos_a[0]["franquicia"] if partidos_a else "Equipo A"
    if not franq_b:
        franq_b = partidos_b[0]["franquicia"] if partidos_b else "Equipo B"

    analisis = analizar_partido(jugador_a, franq_a, jugador_b, franq_b, partidos_h2h, partidos_a, partidos_b)
    msg = formatear_analisis(jugador_a, franq_a, jugador_b, franq_b, analisis)
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
    await update.message.reply_text(msg, parse_mode="Markdown")
    
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
    borrados = c.rowcount
    conn.commit()
    conn.close()
    print(f"Partidos 0-0 eliminados: {borrados}")
    if total_partidos_db() == 0:
        print("Base de datos vacía, cargando datos iniciales...")
        cargar_datos_iniciales(meses=11)
    else:
        print(f"Base de datos lista con {total_partidos_db()} partidos.")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mensaje_libre))

    loop = asyncio.get_event_loop()
    loop.create_task(tarea_actualizacion_diaria())
    loop.create_task(tarea_predicciones_automaticas())

    print("Bot iniciado...")
    app.run_polling()
