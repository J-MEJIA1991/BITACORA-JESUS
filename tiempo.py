
# ======================================================
# tiempo.py — versión final (hora local Chile 🇨🇱)
# ======================================================

from datetime import datetime, timedelta, time, date
import pytz

# 🕒 Zona horaria oficial de Chile
CHILE_TZ = pytz.timezone("America/Santiago")

# ------------------------------------------------------
# 🔹 Hora actual local sin tzinfo (para base de datos)
# ------------------------------------------------------
def hora_actual():
    """Devuelve la hora local de Chile (naive, sin tzinfo)."""
    ahora_chile = datetime.now(CHILE_TZ)
    return ahora_chile.replace(tzinfo=None)

# ------------------------------------------------------
# 🔹 Fecha local (solo día)
# ------------------------------------------------------
def local_date():
    """Devuelve la fecha local de Chile (solo date)."""
    return hora_actual().date()

# ------------------------------------------------------
# 🔹 Rango horario del día completo (inicio-fin)
# ------------------------------------------------------
def day_range(fecha: date):
    """Devuelve el inicio y fin del día completo según hora local de Chile."""
    inicio = datetime.combine(fecha, time.min)
    fin = datetime.combine(fecha + timedelta(days=1), time.min)
    return inicio, fin

# ------------------------------------------------------
# 🔹 Formatear hora chilena legible
# ------------------------------------------------------
def to_hora_chile(dt):
    """Convierte un datetime a formato legible HH:MM:SS AM/PM (hora Chile)."""
    if dt is None:
        return ""
    if dt.tzinfo is not None:
        dt = dt.astimezone(CHILE_TZ)
    else:
        dt = CHILE_TZ.localize(dt)
    return dt.strftime("%I:%M:%S %p")

# ------------------------------------------------------
# 🔹 Límites del mes actual en hora chilena 🇨🇱
# ------------------------------------------------------
def mes_actual_chile_bounds():
    """
    Devuelve (inicio, fin, ahora) del mes actual en hora local de Chile.
    Ejemplo: 2025-11-01 00:00:00 a 2025-11-30 23:59:59
    """
    ahora = datetime.now(CHILE_TZ).replace(tzinfo=None)
    inicio = datetime(ahora.year, ahora.month, 1)
    if ahora.month == 12:
        fin = datetime(ahora.year + 1, 1, 1) - timedelta(seconds=1)
    else:
        fin = datetime(ahora.year, ahora.month + 1, 1) - timedelta(seconds=1)
    return inicio, fin, ahora 


