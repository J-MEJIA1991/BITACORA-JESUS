
# ======================================================
# helpers.py — versión FINAL (Créditos System, hora Chile 🇨🇱)
# ======================================================

from datetime import date, datetime, timedelta
from sqlalchemy import func, case
from extensions import db
from modelos import Cliente, Prestamo, Abono, MovimientoCaja, Liquidacion
from tiempo import hora_actual, local_date, day_range
from extensions import cache


# ---------------------------------------------------
# 🔹 Generar código único
# ---------------------------------------------------
import random
def generar_codigo_cliente():
    """Genera un código numérico único de 6 dígitos para un cliente."""
    while True:
        codigo = ''.join(random.choices('0123456789', k=6))
        if not Cliente.query.filter_by(codigo=codigo).first():
            return codigo


# ---------------------------------------------------
# 🔹 Crear liquidación arrastrando caja anterior (única oficial)
# ---------------------------------------------------
def crear_liquidacion_para_fecha(fecha: date):
    """Crea la liquidación para una fecha determinada arrastrando la caja del día anterior."""
    liq_existente = Liquidacion.query.filter_by(fecha=fecha).first()
    if liq_existente:
        return liq_existente

    # Buscar la caja del día anterior
    dia_anterior = fecha - timedelta(days=1)
    anterior = Liquidacion.query.filter_by(fecha=dia_anterior).first()
    caja_anterior = anterior.caja if anterior else 0.0

    # Crear nueva liquidación
    nueva = Liquidacion(
        fecha=fecha,
        caja_manual=caja_anterior,
        caja=caja_anterior
    )
    db.session.add(nueva)
    db.session.commit()
    return nueva


# ---------------------------------------------------
# 🔹 Totales globales (Cartera + Caja total)
# ---------------------------------------------------
def obtener_resumen_total():
    """Calcula los totales generales de caja y cartera del sistema."""
    total_entradas = (
        db.session.query(func.sum(case((MovimientoCaja.tipo == 'entrada_manual', MovimientoCaja.monto), else_=0)))
        .scalar() or 0.0
    )

    total_salidas = (
        db.session.query(func.sum(case((MovimientoCaja.tipo == 'salida', MovimientoCaja.monto), else_=0)))
        .scalar() or 0.0
    )

    total_gastos = (
        db.session.query(func.sum(case((MovimientoCaja.tipo == 'gasto', MovimientoCaja.monto), else_=0)))
        .scalar() or 0.0
    )

    caja_total = total_entradas - total_salidas - total_gastos

    cartera_total = float(
        db.session.query(func.coalesce(func.sum(Prestamo.saldo), 0)).scalar() or 0.0
    )

    return {
        'caja_total': caja_total,
        'cartera_total': cartera_total
    }


# ---------------------------------------------------
# 🔄 Actualizar liquidación del día tras cualquier movimiento
# ---------------------------------------------------
def actualizar_liquidacion_por_movimiento(fecha: date, commit: bool = True):
    """
    Recalcula la liquidación para una fecha según los movimientos del día.
    Si commit=False, solo devuelve el objeto sin guardar.
    """
    start, end = day_range(fecha)

    # 💰 Entradas por abonos
    entradas_abonos = (
        db.session.query(func.coalesce(func.sum(Abono.monto), 0))
        .filter(Abono.fecha >= start, Abono.fecha < end)
        .scalar() or 0.0
    )

    # 💵 Entradas manuales
    entradas_manual = (
        db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0))
        .filter(
            MovimientoCaja.tipo == 'entrada_manual',
            MovimientoCaja.fecha >= start,
            MovimientoCaja.fecha < end
        )
        .scalar() or 0.0
    )

    # 💸 Salidas manuales
    salidas_manual = (
        db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0))
        .filter(
            MovimientoCaja.tipo == 'salida',
            MovimientoCaja.fecha >= start,
            MovimientoCaja.fecha < end
        )
        .scalar() or 0.0
    )

    # 🧾 Gastos
    gastos = (
        db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0))
        .filter(
            MovimientoCaja.tipo == 'gasto',
            MovimientoCaja.fecha >= start,
            MovimientoCaja.fecha < end
        )
        .scalar() or 0.0
    )

    # 💳 Préstamos entregados
    prestamos_entregados = (
        db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0))
        .filter(
            MovimientoCaja.tipo == 'prestamo',
            MovimientoCaja.fecha >= start,
            MovimientoCaja.fecha < end
        )
        .scalar() or 0.0
    )

    # 📦 Caja anterior
    liq_anterior = (
        Liquidacion.query.filter(Liquidacion.fecha < fecha)
        .order_by(Liquidacion.fecha.desc())
        .first()
    )
    caja_anterior = liq_anterior.caja if liq_anterior else 0.0

    # 🔄 Crear o actualizar registro de liquidación
    liq = crear_liquidacion_para_fecha(fecha)

    liq.entradas = entradas_abonos
    liq.entradas_caja = entradas_manual
    liq.salidas = salidas_manual
    liq.gastos = gastos
    liq.prestamos_hoy = prestamos_entregados
    liq.caja_manual = caja_anterior
    liq.caja = (
        caja_anterior
        + entradas_abonos
        + entradas_manual
        - (prestamos_entregados + salidas_manual + gastos)
    )

    if commit:
        db.session.commit()

    return liq


# ---------------------------------------------------
# ♻️ Cache resumen
# ---------------------------------------------------
def eliminar_cache_resumen_hoy():
    """
    Elimina el cache del resumen diario basado en la fecha actual en Chile.
    Esto asegura que los cambios en abonos, préstamos o caja se reflejen correctamente.
    """
    hoy = local_date()
    clave = f"resumen_{hoy.isoformat()}"
    cache.delete(clave)
