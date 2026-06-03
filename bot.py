import os
import requests
import json
import statistics
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = "8917382762:AAGJI3_MKRiEe5nSb1uz56Q-fJYfIchzWuQ"
BETSAPI_TOKEN = "255743-DXkD4nrqNqXhJq"
LEAGUE_ID = "25067"
SPORT_ID = "18"
BASE_URL = "https://api.betsapi.com"

def get_upcoming():
    r = requests.get(f"{BASE_URL}/v3/events/upcoming?sport_id={SPORT_ID}&league_id={LEAGUE_ID}&token={BETSAPI_TOKEN}")
    return r.json().get("results", [])

def get_ended(page=1, day=None):
    url = f"https://api.b365api.com/v3/events/ended?sport_id={SPORT_ID}&league_id={LEAGUE_ID}&token={BETSAPI_TOKEN}&page={page}"
    if day:
        url += f"&day={day}"
    r = requests.get(url)
    return r.json().get("results", [])
def get_event_stats(event_id):
    r = requests.get(f"{BASE_URL}/v1/event/stats_trend?token={BETSAPI_TOKEN}&event_id={event_id}")
    return r.json().get("results", {})

def prob_to_odds(prob):
    if prob <= 0 or prob >= 1:
        return 1.01
    return round(1 / prob, 2)

def calcular_std(valores):
    if len(valores) < 2:
        return 0
    return round(statistics.stdev(valores), 1)

def extraer_nombre_jugador(nombre_equipo):
    if "(" in nombre_equipo and ")" in nombre_equipo:
        return nombre_equipo.split("(")[-1].replace(")", "").strip()
    return nombre_equipo.strip()

def extraer_franquicia(nombre_equipo):
    if "(" in nombre_equipo:
        return nombre_equipo.split("(")[0].strip()
    return nombre_equipo.strip()

def buscar_historial(jugador_a, jugador_b, paginas=50):
    partidos_h2h = []
    partidos_a = []
    partidos_b = []
    for p in range(1, paginas + 1):
        resultados = get_ended(p)
        if not resultados:
            break
        for ev in resultados:
            home = ev.get("home", {}).get("name", "")
            away = ev.get("away", {}).get("name", "")
            ss = ev.get("ss", "")
            if not ss or "-" not in ss:
                continue
            try:
                score_h, score_a = map(int, ss.split("-"))
            except:
                continue
            nombre_home = extraer_nombre_jugador(home).upper()
            nombre_away = extraer_nombre_jugador(away).upper()
            franq_home = extraer_franquicia(home)
            franq_away = extraer_franquicia(away)
            ja = jugador_a.upper()
            jb = jugador_b.upper()
            es_h2h = (nombre_home == ja and nombre_away == jb) or (nombre_home == jb and nombre_away == ja)
            if es_h2h:
                if nombre_home == ja:
                    partidos_h2h.append({"pts_a": score_h, "pts_b": score_a, "gano_a": score_h > score_a, "franq_a": franq_home, "franq_b": franq_away})
                else:
                    partidos_h2h.append({"pts_a": score_a, "pts_b": score_h, "gano_a": score_a > score_h, "franq_a": franq_away, "franq_b": franq_home})
            if nombre_home == ja:
                partidos_a.append({"pts_favor": score_h, "pts_contra": score_a, "gano": score_h > score_a, "franquicia": franq_home})
            elif nombre_away == ja:
                partidos_a.append({"pts_favor": score_a, "pts_contra": score_h, "gano": score_a > score_h, "franquicia": franq_away})
            if nombre_home == jb:
                partidos_b.append({"pts_favor": score_h, "pts_contra": score_a, "gano": score_h > score_a, "franquicia": franq_home})
            elif nombre_away == jb:
                partidos_b.append({"pts_favor": score_a, "pts_contra": score_h, "gano": score_a > score_h, "franquicia": franq_away})
    return partidos_h2h, partidos_a, partidos_b
def analizar_partido(jugador_a, franq_a, jugador_b, franq_b, partidos_h2h, partidos_a, partidos_b):
    resultado = {}
    # H2H historico general (25%)
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
    # H2H con equipos actuales (20%)
    h2h_equipos = [p for p in partidos_h2h if p.get("franq_a", "").upper() == franq_a.upper() and p.get("franq_b", "").upper() == franq_b.upper()]
    if h2h_equipos:
        wins_eq = sum(1 for p in h2h_equipos if p["gano_a"])
        prob_h2h_eq = wins_eq / len(h2h_equipos)
        resultado["h2h_equipos"] = len(h2h_equipos)
        resultado["h2h_wins_eq_a"] = wins_eq if h2h_equipos else 0
    else:
        prob_h2h_eq = 0.5
        resultado["h2h_equipos"] = 0
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
    recientes_a = partidos_a[:15] if len(partidos_a) >= 15 else partidos_a
    recientes_b = partidos_b[:15] if len(partidos_b) >= 15 else partidos_b
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
    h2h_reciente = partidos_h2h[:10] if len(partidos_h2h) >= 10 else partidos_h2h
    if h2h_reciente:
        wins_rec = sum(1 for p in h2h_reciente if p["gano_a"])
        prob_h2h_rec = wins_rec / len(h2h_reciente)
    else:
        prob_h2h_rec = 0.5
    # Probabilidad final ponderada
    prob_final_a = (prob_h2h * 0.25) + (prob_equipo * 0.25) + (prob_h2h_eq * 0.20) + (prob_forma * 0.20) + (prob_h2h_rec * 0.10)
    prob_final_b = 1 - prob_final_a
    resultado["prob_a"] = round(prob_final_a, 4)
    resultado["prob_b"] = round(prob_final_b, 4)
    resultado["cuota_a"] = prob_to_odds(prob_final_a)
    resultado["cuota_b"] = prob_to_odds(prob_final_b)
    # Over/Under
    todos_pts_a = [p["pts_favor"] for p in partidos_a] if partidos_a else []
    todos_pts_b = [p["pts_favor"] for p in partidos_b] if partidos_b else []
    pts_totales_h2h = [p["pts_a"] + p["pts_b"] for p in partidos_h2h] if partidos_h2h else []
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
        linea_a = resultado["avg_pts_a"]
        linea_b = resultado["avg_pts_b"]
        if resultado["avg_total_h2h"]:
            linea_total = round((resultado["avg_total_h2h"] + linea_a + linea_b) / 2, 1)
        else:
            linea_total = round(linea_a + linea_b, 1)
        std_a = resultado["std_pts_a"] or 5
        std_b = resultado["std_pts_b"] or 5
        confianza_a = max(0.52, min(0.75, 0.5 + (1 / (1 + std_a / 10)) * 0.25))
        confianza_b = max(0.52, min(0.75, 0.5 + (1 / (1 + std_b / 10)) * 0.25))
        confianza_total = max(0.52, min(0.72, 0.5 + (1 / (1 + ((std_a + std_b) / 2) / 10)) * 0.22))
        resultado["linea_a"] = linea_a
        resultado["linea_b"] = linea_b
        resultado["linea_total"] = linea_total
        resultado["over_a"] = prob_to_odds(confianza_a)
        resultado["under_a"] = prob_to_odds(1 - confianza_a)
        resultado["over_b"] = prob_to_odds(confianza_b)
        resultado["under_b"] = prob_to_odds(1 - confianza_b)
        resultado["over_total"] = prob_to_odds(confianza_total)
        resultado["under_total"] = prob_to_odds(1 - confianza_total)
        handicap = round(linea_a - linea_b, 1)
        resultado["handicap"] = handicap
    return resultado

def formatear_analisis(jugador_a, franq_a, jugador_b, franq_b, analisis):
    msg = f"🏀 *{jugador_a} ({franq_a}) vs {jugador_b} ({franq_b})*\n\n"
    msg += f"📊 *Datos analizados:*\n"

    # H2H histórico con resultado de cada partido
    total_h2h = analisis.get('h2h_total', 0)
    if total_h2h > 0:
        wins_a = analisis.get('h2h_wins_a', 0)
        wins_b = total_h2h - wins_a
        msg += f"• H2H: {total_h2h} partidos — {jugador_a} {wins_a}W/{wins_b}L vs {jugador_b} {wins_b}W/{wins_a}L\n"
    else:
        msg += f"• H2H total: 0 partidos\n"

    # H2H con equipos actuales
    h2h_equipos = analisis.get('h2h_equipos', 0)
    if h2h_equipos > 0:
        wins_eq_a = analisis.get('h2h_wins_eq_a', 0)
        wins_eq_b = h2h_equipos - wins_eq_a
        msg += f"• H2H con estos equipos: {h2h_equipos} partidos — {jugador_a} {wins_eq_a}W/{wins_eq_b}L vs {jugador_b} {wins_eq_b}W/{wins_eq_a}L\n"
    else:
        msg += f"• H2H con estos equipos: 0 partidos\n"

    # Forma reciente con racha W/L
    if analisis.get('racha_a') and analisis.get('racha_b'):
        msg += f"• Forma reciente {jugador_a}: {'-'.join(analisis['racha_a'].split())}\n"
        msg += f"• Forma reciente {jugador_b}: {'-'.join(analisis['racha_b'].split())}\n"
    elif analisis.get('forma_a') is not None:
        msg += f"• Forma reciente {jugador_a}: {analisis['forma_a']}% victorias\n"
        msg += f"• Forma reciente {jugador_b}: {analisis['forma_b']}% victorias\n"

    if analisis.get('winrate_a_franq') is not None:
        msg += f"• {jugador_a} con {franq_a}: {analisis['winrate_a_franq']}% victorias ({analisis['partidos_a_franq']} partidos)\n"
        msg += f"• {jugador_b} con {franq_b}: {analisis['winrate_b_franq']}% victorias ({analisis['partidos_b_franq']} partidos)\n"

    msg += f"\n🎯 *GANADOR*\n"
    msg += f"{jugador_a}: `{analisis['cuota_a']}` — {jugador_b}: `{analisis['cuota_b']}`\n"

    if analisis.get('linea_a'):
        msg += f"\n📈 *PUNTOS {jugador_a.upper()}*\n"
        msg += f"Línea: {analisis['linea_a']} pts\n"
        msg += f"Over `{analisis['over_a']}` / Under `{analisis['under_a']}`\n"
        msg += f"\n📈 *PUNTOS {jugador_b.upper()}*\n"
        msg += f"Línea: {analisis['linea_b']} pts\n"
        msg += f"Over `{analisis['over_b']}` / Under `{analisis['under_b']}`\n"
        msg += f"\n🔢 *TOTAL DEL PARTIDO*\n"
        msg += f"Línea: {analisis['linea_total']} pts\n"
        msg += f"Over `{analisis['over_total']}` / Under `{analisis['under_total']}`\n"

    return msg
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🏀 *Bot H2H GG League*\n\n"
        "Comandos disponibles:\n"
        "• `/pronostico JUGADORA vs JUGADORB` — análisis completo\n"
        "• `/proximos` — próximos partidos\n"
        "• `/resultados` — últimos resultados\n"
        "• `/stats JUGADOR` — estadísticas de un jugador\n\n"
        "Ejemplo: `/pronostico MYTH vs MALICE`"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def proximos(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await update.message.reply_text("🔍 Consultando últimos resultados...")
    partidos = get_ended()
    if not partidos:
        await update.message.reply_text("No hay resultados disponibles.")
        return
    msg = "🏀 *Últimos resultados H2H GG League:*\n\n"
    for ev in partidos[:8]:
        home = ev.get("home", {}).get("name", "?")
        away = ev.get("away", {}).get("name", "?")
        ss = ev.get("ss", "?")
        msg += f"• {home} vs {away} — `{ss}`\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /stats NOMBREJUGADOR\nEjemplo: /stats MYTH")
        return
    jugador = " ".join(context.args).upper()
    await update.message.reply_text(f"🔍 Buscando estadísticas de {jugador}...")
    _, partidos, _ = buscar_historial(jugador, "DUMMY", paginas=50)
    if not partidos:
        await update.message.reply_text(f"No encontré partidos de {jugador}.")
        return
    total = len(partidos)
    victorias = sum(1 for p in partidos if p["gano"])
    derrotas = total - victorias
    avg_pts = round(sum(p["pts_favor"] for p in partidos) / total, 1)
    avg_contra = round(sum(p["pts_contra"] for p in partidos) / total, 1)
    std = calcular_std([p["pts_favor"] for p in partidos])
    recientes = partidos[:10]
    racha = sum(1 for p in recientes if p["gano"])
    msg = (
        f"📊 *Estadísticas de {jugador}*\n\n"
        f"• Partidos: {total}\n"
        f"• Victorias: {victorias} ({round(victorias/total*100,1)}%)\n"
        f"• Derrotas: {derrotas}\n"
        f"• Promedio puntos: {avg_pts}\n"
        f"• Promedio recibidos: {avg_contra}\n"
        f"• Consistencia: ±{std} pts\n"
        f"• Últimos 10: {racha} victorias\n"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def pronostico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = " ".join(context.args).upper()
    if "VS" not in texto:
        await update.message.reply_text("Uso: /pronostico JUGADORA vs JUGADORB\nEjemplo: /pronostico MYTH vs MALICE")
        return
    partes = texto.split("VS")
    jugador_a = partes[0].strip()
    jugador_b = partes[1].strip()
    await update.message.reply_text(f"🔍 Analizando {jugador_a} vs {jugador_b}...\nEsto puede tardar unos segundos.")
    
    # Buscar equipos en próximos partidos
    franq_a = None
    franq_b = None
    proximos = get_upcoming()
    for ev in proximos:
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
    
    partidos_h2h, partidos_a, partidos_b = buscar_historial(jugador_a, jugador_b, paginas=50)
    
    # Si no encontró equipos en próximos, usar último partido
    if not franq_a:
        franq_a = partidos_a[0]["franquicia"] if partidos_a else "Equipo A"
    if not franq_b:
        franq_b = partidos_b[0]["franquicia"] if partidos_b else "Equipo B"
    
    analisis = analizar_partido(jugador_a, franq_a, jugador_b, franq_b, partidos_h2h, partidos_a, partidos_b)
    msg = formatear_analisis(jugador_a, franq_a, jugador_b, franq_b, analisis)
    await update.message.reply_text(msg, parse_mode="Markdown")

async def mensaje_libre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.upper()
    if " VS " in texto:
        partes = texto.split(" VS ")
        jugador_a = partes[0].strip()
        jugador_b = partes[1].strip()
        await update.message.reply_text(f"🔍 Analizando {jugador_a} vs {jugador_b}...")
        partidos_h2h, partidos_a, partidos_b = buscar_historial(jugador_a, jugador_b, paginas=8)
        franq_a = partidos_a[-1]["franquicia"] if partidos_a else "Equipo A"
        franq_b = partidos_b[-1]["franquicia"] if partidos_b else "Equipo B"
        analisis = analizar_partido(jugador_a, franq_a, jugador_b, franq_b, partidos_h2h, partidos_a, partidos_b)
        msg = formatear_analisis(jugador_a, franq_a, jugador_b, franq_b, analisis)
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text("Escribe algo como: *MYTH vs MALICE* o usa /pronostico MYTH vs MALICE", parse_mode="Markdown")

async def h2h(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = " ".join(context.args).upper()
    if "VS" not in texto:
        await update.message.reply_text("Uso: /h2h JUGADORA vs JUGADORB\nEjemplo: /h2h MYTH vs MALICE")
        return
    partes = texto.split("VS")
    jugador_a = partes[0].strip()
    jugador_b = partes[1].strip()
    await update.message.reply_text(f"🔍 Buscando historial {jugador_a} vs {jugador_b}...")
    partidos_h2h, _, _ = buscar_historial(jugador_a, jugador_b, paginas=50)
    if not partidos_h2h:
        await update.message.reply_text(f"No encontré enfrentamientos entre {jugador_a} y {jugador_b}.")
        return
    msg = f"🏀 *H2H {jugador_a} vs {jugador_b}*\n"
    msg += f"Total: {len(partidos_h2h)} partidos\n\n"
    wins_a = sum(1 for p in partidos_h2h if p["gano_a"])
    wins_b = len(partidos_h2h) - wins_a
    msg += f"{jugador_a}: {wins_a}W/{wins_b}L\n"
    msg += f"{jugador_b}: {wins_b}W/{wins_a}L\n\n"
    msg += f"📋 *Resultados:*\n"
    for i, p in enumerate(partidos_h2h, 1):
        ganador = jugador_a if p["gano_a"] else jugador_b
        msg += f"{i}. {jugador_a} ({p.get('franq_a','?')}) {p['pts_a']} — {p['pts_b']} {jugador_b} ({p.get('franq_b','?')}) → {ganador}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")
    
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("proximos", proximos))
    app.add_handler(CommandHandler("resultados", resultados))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("pronostico", pronostico))
    app.add_handler(CommandHandler("h2h", h2h))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mensaje_libre))
    print("Bot iniciado...")
    app.run_polling()
