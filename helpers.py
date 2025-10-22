# ======================================================
# helpers.py — versión FINAL (Créditos System, hora Chile 🇨🇱)
# ======================================================

from datetime import date, datetime, time, timedelta
import random
from sqlalchemy import func
from extensions import db
from modelos import Cliente, Prestamo, Abono, MovimientoCaja, Liquidacion

# ⏰ Importar funciones de hora local
from tiempo import hora_actual, local_date, day_range

# ---------------------------------------------------
# 🔹 Generar códigos únicos
# ---------------------------------------------------
def generar_codigo_cliente():
    """Genera un código numérico único de 6 dígitos para un cliente."""
    while True:
        codigo = ''.join(random.choices('0123456789', k=6))
        if not Cliente.query.filter_by(codigo=codigo).first():
            return codigo


# ---------------------------------------------------
# 🔹 Crear o buscar liquidación existente
# ---------------------------------------------------
def crear_liquidacion_para_fecha(fecha: date):
    """Crea la liquidación para una fecha si no existe."""
    liq = Liquidacion.query.filter_by(fecha=fecha).first()
    if not liq:
        liq = Liquidacion(fecha=fecha)
        db.session.add(liq)
        db.session.commit()
    return liq


# ---------------------------------------------------
# 🔹 Obtener totales generales
# ---------------------------------------------------
def obtener_resumen_total():
    """Calcula los totales generales de caja y cartera."""
    total_entradas = (
        db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0))
        .filter(MovimientoCaja.tipo == 'entrada_manual')
        .scalar() or 0.0
    )

    total_salidas = (
        db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0))
        .filter(MovimientoCaja.tipo == 'salida')
        .scalar() or 0.0
    )

    total_gastos = (
        db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0))
        .filter(MovimientoCaja.tipo == 'gasto')
        .scalar() or 0.0
    )

    caja_total = total_entradas - total_salidas - total_gastos
    cartera_total = float(
        db.session.query(func.coalesce(func.sum(Prestamo.saldo), 0)).scalar() or 0.0
    )

    return {'caja_total': caja_total, 'cartera_total': cartera_total}


# ======================================================
# 🔄 RECONSTRUIR MOVIMIENTOS DE PRÉSTAMOS
# ======================================================
def reconstruir_movimientos_prestamos():
    """
    🔧 Repara la tabla MovimientoCaja eliminando todos los movimientos tipo 'prestamo'
    y los vuelve a generar solo para clientes activos (no cancelados).
    Luego actualiza la liquidación del día actual.
    """
    borrados = MovimientoCaja.query.filter_by(tipo="prestamo").delete()
    db.session.commit()
    print(f"🗑️ Movimientos de préstamo eliminados: {borrados}")

    nuevos = 0
    for p in Prestamo.query.all():
        if p.cliente and not p.cliente.cancelado:
            mov = MovimientoCaja(
                tipo="prestamo",
                monto=p.monto,
                descripcion=f"Préstamo a {p.cliente.nombre}",
                fecha=datetime.combine(p.fecha, datetime.min.time())
            )
            db.session.add(mov)
            nuevos += 1

    db.session.commit()
    print(f"✅ Movimientos válidos reconstruidos: {nuevos}")

    from helpers import actualizar_liquidacion_por_movimiento
    liq = actualizar_liquidacion_por_movimiento(local_date())

    print(f"📅 Liquidación del {liq.fecha} actualizada correctamente.")
    print(f"💰 Caja final: {liq.caja:.2f}")
    return liq


# ---------------------------------------------------
# 🔹 Actualizar liquidación diaria
# ---------------------------------------------------
def actualizar_liquidacion_por_movimiento(fecha: date):
    """Recalcula la liquidación para una fecha según movimientos y abonos (hora Chile)."""
    start, end = day_range(fecha)

    # 💰 Abonos de clientes
    entradas_abonos = (
        db.session.query(func.coalesce(func.sum(Abono.monto), 0))
        .join(Prestamo, Abono.prestamo_id == Prestamo.id)
        .filter(Abono.fecha >= start, Abono.fecha < end)
        .scalar() or 0.0
    )

    # 💵 Entradas manuales
    entradas_manual = (
        db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0))
        .filter(
            MovimientoCaja.tipo == 'entrada_manual',
            MovimientoCaja.fecha >= start,
            MovimientoCaja.fecha < end,
        )
        .scalar() or 0.0
    )

    # 💸 Salidas manuales
    salidas_manual = (
        db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0))
        .filter(
            MovimientoCaja.tipo == 'salida',
            MovimientoCaja.fecha >= start,
            MovimientoCaja.fecha < end,
        )
        .scalar() or 0.0
    )

    # 🧾 Gastos
    gastos = (
        db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0))
        .filter(
            MovimientoCaja.tipo == 'gasto',
            MovimientoCaja.fecha >= start,
            MovimientoCaja.fecha < end,
        )
        .scalar() or 0.0
    )

    # 🏦 Préstamos entregados
    prestamos_entregados = (
        db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0))
        .filter(
            MovimientoCaja.tipo == 'prestamo',
            MovimientoCaja.fecha >= start,
            MovimientoCaja.fecha < end,
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

    # 🔢 Calcular totales
    total_entradas = entradas_abonos + entradas_manual
    total_salidas = salidas_manual
    caja_actual = caja_anterior + total_entradas - (prestamos_entregados + total_salidas + gastos)

    # 🔄 Crear o actualizar registro
    liq = crear_liquidacion_para_fecha(fecha)
    liq.entradas = entradas_abonos
    liq.entradas_caja = entradas_manual
    liq.prestamos_hoy = prestamos_entregados
    liq.salidas = salidas_manual
    liq.gastos = gastos
    liq.caja_manual = caja_anterior
    liq.caja = caja_actual

    db.session.commit()
    return liq


# ---------------------------------------------------
# 🔹 Reparar cliente manualmente (reverso en caja)
# ---------------------------------------------------
def reparar_cliente(nombre: str | int):
    """
    Repara un cliente que fue eliminado antes de la actualización de la ruta.
    - Crea una entrada manual devolviendo el saldo pendiente a la caja.
    - Marca al cliente como cancelado y su saldo en 0.
    - Actualiza la liquidación del día actual.
    Puede usarse por nombre o por ID.
    """
    if isinstance(nombre, int):
        cliente = Cliente.query.get(nombre)
    else:
        cliente = Cliente.query.filter_by(nombre=nombre).first()

    if not cliente:
        print(f"❌ No se encontró el cliente '{nombre}'.")
        return

    if cliente.saldo <= 0:
        print(f"ℹ️ El cliente '{cliente.nombre}' no tiene saldo para revertir (saldo actual = {cliente.saldo}).")
        return

    # 💵 Crear movimiento de reverso
    mov = MovimientoCaja(
        tipo="entrada_manual",
        monto=cliente.saldo,
        descripcion=f"Reverso manual cliente {cliente.nombre}",
        fecha=hora_actual(),  # 👈 hora local de Chile
    )
    db.session.add(mov)

    saldo_devuelto = cliente.saldo
    cliente.saldo = 0
    cliente.cancelado = True
    db.session.commit()

    try:
        actualizar_liquidacion_por_movimiento(local_date())
    except Exception as e:
        print(f"⚠️ No se pudo actualizar la liquidación automáticamente: {e}")

    print(f"✅ Cliente '{cliente.nombre}' reparado correctamente.")
    print(f"💰 Se devolvieron ${saldo_devuelto:.2f} a la caja.")

# ======================================================
# 🧭 Función para normalizar hora sin zona (modo local Chile)
# ======================================================
def hora_sin_tz(dt=None):
    """
    Convierte cualquier datetime a hora chilena sin tzinfo (naive),
    útil para guardar en BD sin perder la hora real local.
    """
    if dt is None:
        dt = datetime.now(CHILE_TZ)
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(CHILE_TZ).replace(tzinfo=None)


