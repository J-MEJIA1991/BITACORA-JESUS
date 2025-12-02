# ======================================================
# rutas.py — versión CORREGIDA (hora real de Chile 🇨🇱)
# ======================================================

import os
from datetime import datetime, timedelta
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, session, jsonify
)
from functools import wraps
from sqlalchemy import func
from extensions import db
from modelos import Cliente, Prestamo, Abono, MovimientoCaja, Liquidacion
from helpers import (
    generar_codigo_cliente,
    crear_liquidacion_para_fecha,
    obtener_resumen_total,
    actualizar_liquidacion_por_movimiento,
)
from tiempo import hora_actual, to_hora_chile as hora_chile, mes_actual_chile_bounds
import tiempo


# ======================================================
# 🕒 CONFIGURACIÓN HORARIA Y UTILIDADES
# ======================================================
from tiempo import (
    hora_actual,   # ✅ Devuelve hora local de Chile (sin tzinfo)
    local_date,    # ✅ Devuelve fecha local de Chile
    day_range,     # ✅ Devuelve inicio y fin del día local
    to_hora_chile  # ✅ Convierte UTC → hora chilena legible
)

# ======================================================
# 🔧 CONFIGURACIÓN DEL BLUEPRINT
# ======================================================
app_rutas = Blueprint("app_rutas", __name__)

# ======================================================
# 🔐 LOGIN / AUTENTICACIÓN
# ======================================================
VALID_USER = os.getenv("APP_USER", "j-mejia")
VALID_PASS = os.getenv("APP_PASS", "honny")

def login_required(f):
    """Protege las rutas que requieren sesión activa."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "usuario" not in session:
            return redirect(url_for("app_rutas.login"))
        return f(*args, **kwargs)
    return wrapper

# ======================================================
# 📊 DASHBOARD GENERAL — Créditos (versión corregida)
# ======================================================
@app_rutas.route("/dashboard")
@login_required
def dashboard():
    hoy = local_date()
    start, end = day_range(hoy)

    # 🔹 Total de clientes activos
    total_clientes_activos = (
        db.session.query(func.count(Cliente.id))
        .filter(Cliente.cancelado == False)
        .scalar() or 0
    )

    # 💰 Total de abonos del día
    total_abonos = (
        db.session.query(func.coalesce(func.sum(Abono.monto), 0.0))
        .filter(Abono.fecha >= start, Abono.fecha < end)
        .scalar() or 0.0
    )

    # 🏦 Total de préstamos (desde Prestamo, no MovimientoCaja)
    total_prestamos = (
        db.session.query(func.coalesce(func.sum(Prestamo.monto), 0.0))
        .join(Cliente, Prestamo.cliente_id == Cliente.id)
        .filter(
            Cliente.cancelado == False,
            Prestamo.fecha >= start,
            Prestamo.fecha < end
        )
        .scalar() or 0.0
    )

    # 💵 Entradas manuales
    total_entradas = (
        db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0.0))
        .filter(
            MovimientoCaja.tipo == "entrada_manual",
            MovimientoCaja.fecha >= start,
            MovimientoCaja.fecha < end
        )
        .scalar() or 0.0
    )

    # 💸 Salidas
    total_salidas = (
        db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0.0))
        .filter(
            MovimientoCaja.tipo == "salida",
            MovimientoCaja.fecha >= start,
            MovimientoCaja.fecha < end
        )
        .scalar() or 0.0
    )

    # 🧾 Gastos
    total_gastos = (
        db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0.0))
        .filter(
            MovimientoCaja.tipo == "gasto",
            MovimientoCaja.fecha >= start,
            MovimientoCaja.fecha < end
        )
        .scalar() or 0.0
    )

    # 📦 Caja total del día
    caja_total = total_abonos + total_entradas - (total_prestamos + total_salidas + total_gastos)

    return render_template(
        "dashboard.html",
        hoy=hoy,
        total_clientes_activos=total_clientes_activos,
        total_abonos=total_abonos,
        total_prestamos=total_prestamos,
        total_entradas=total_entradas,
        total_salidas=total_salidas,
        total_gastos=total_gastos,
        caja_total=caja_total,
    )



# ======================================================
# 🏠 RUTA PRINCIPAL — CLIENTES + TARJETA DE RESUMEN (FINAL)
# ======================================================
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from datetime import timedelta
from flask import current_app

# caché memoria del día
_cache_resumen = {"fecha": None, "data": None, "timestamp": 0}

@app_rutas.route("/")
@login_required
def index():
    from helpers import eliminar_cache_resumen_hoy, obtener_resumen_total, actualizar_liquidacion_por_movimiento

    eliminar_cache_resumen_hoy()  # evita corrupción visual después de mover orden

    hoy = local_date()

    # === USAR CACHE SI ES MISMO DÍA Y <30s ============================
    import time
    if (
        _cache_resumen["fecha"] == hoy
        and time.time() - _cache_resumen["timestamp"] < 30
    ):
        print("♻️ Cache index usado.")
        data = _cache_resumen["data"]
        return render_template(
            "index.html",
            clientes=data["clientes"],
            resumen_hoy=data["resumen_hoy"],
            resumen_total=data["resumen_total"],
            hoy=hoy
        )

    print("⚙️ Recalculando index...")

    # clientes activos ordenados
    clientes = (
        Cliente.query.options(joinedload(Cliente.prestamos))
        .filter_by(cancelado=False)
        .order_by(Cliente.orden.asc().nullsfirst(), Cliente.id.asc())
        .all()
    )

    # reparar orden roto
    orden_cambiado = False
    for idx, c in enumerate(clientes, start=1):
        if not c.orden or c.orden != idx:
            c.orden = idx
            orden_cambiado = True
    if orden_cambiado:
        db.session.commit()

    # estado plazo
    subquery = (
        db.session.query(
            Prestamo.cliente_id, func.max(Prestamo.fecha).label("ultima_fecha")
        )
        .group_by(Prestamo.cliente_id)
        .subquery()
    )
    ultimos = dict(db.session.query(subquery.c.cliente_id, subquery.c.ultima_fecha).all())

    for c in clientes:
        estado = "normal"
        ultima_fecha = ultimos.get(c.id)
        if ultima_fecha:
            p = (
                Prestamo.query.filter_by(cliente_id=c.id, fecha=ultima_fecha).first()
            )
            if p and p.plazo:
                fecha_venc = p.fecha + timedelta(days=p.plazo)
                dias_pasados = (hoy - fecha_venc).days
                if 0 <= dias_pasados < 30:
                    estado = "vencido"
                elif dias_pasados >= 30:
                    estado = "moroso"
        c.estado_plazo = estado

    # === resumen del día LOC contable =================================
    liq_hoy = actualizar_liquidacion_por_movimiento(hoy, commit=False)

    resumen_hoy = {
        "entradas": liq_hoy.entradas,
        "entradas_caja": liq_hoy.entradas_caja,
        "prestamos_hoy": liq_hoy.prestamos_hoy,
        "salidas": liq_hoy.salidas,
        "gastos": liq_hoy.gastos,
        "caja_manual": liq_hoy.caja_manual,
        "caja": liq_hoy.caja,
    }

    resumen_total = obtener_resumen_total()

    # === SAVE CACHE =====================================
    _cache_resumen["fecha"] = hoy
    _cache_resumen["data"] = {
        "clientes": clientes,
        "resumen_hoy": resumen_hoy,
        "resumen_total": resumen_total,
    }
    _cache_resumen["timestamp"] = time.time()

    return render_template(
        "index.html",
        clientes=clientes,
        resumen_hoy=resumen_hoy,
        resumen_total=resumen_total,
        hoy=hoy
    )

    # ======================================================
    # 📋 Renderizar plantilla
    # ======================================================
    return render_template(
        "index.html",
        clientes=clientes,
        hoy=hoy,
        resumen=resumen_total,
        total_abonos=resumen_hoy["abonos"],
        total_prestamos=resumen_hoy["prestamos"],
        total_entradas=resumen_hoy["entradas"],
        total_salidas=resumen_hoy["salidas"],
        total_gastos=resumen_hoy["gastos"],
        caja_total=resumen_hoy["caja_total"],
    )

# ======================================================
# 🔐 LOGIN Y LOGOUT
# ======================================================
@app_rutas.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        clave = request.form.get("clave", "").strip()
        if usuario == VALID_USER and clave == VALID_PASS:
            session["usuario"] = usuario
            flash("Inicio de sesión correcto ✅", "success")
            return redirect(url_for("app_rutas.index"))
        flash("Usuario o clave incorrectos ❌", "danger")
    return render_template("login.html")


@app_rutas.route("/logout")
def logout():
    session.pop("usuario", None)
    flash("👋 Sesión cerrada correctamente.", "info")
    return redirect(url_for("app_rutas.login"))

# ======================================================
# 🧍‍♂️ NUEVO CLIENTE — CREACIÓN Y RENOVACIÓN (FINAL con orden automático igual que index)
# ======================================================
@app_rutas.route("/nuevo_cliente", methods=["GET", "POST"])
@login_required
def nuevo_cliente():
    from datetime import timedelta
    from sqlalchemy import func
    from helpers import eliminar_cache_resumen_hoy

    if request.method == "POST":
        try:
            nombre = (request.form.get("nombre") or "").strip()
            codigo = (request.form.get("codigo") or "").strip()
            direccion = (request.form.get("direccion") or "").strip()
            telefono = (request.form.get("telefono") or "").strip()
            monto = request.form.get("monto", type=float) or 0.0
            interes = request.form.get("interes", type=float) or 0.0
            plazo = request.form.get("plazo", type=int) or 0
            orden = request.form.get("orden", type=int) or 0
            frecuencia = (request.form.get("frecuencia") or "diario").strip().lower()

            if orden <= 0:
                flash("El número de orden es inválido. Ese número no existe en la lista.", "warning")
                return redirect(url_for("app_rutas.nuevo_cliente"))

            FRECUENCIAS_VALIDAS = {"diario", "semanal", "quincenal", "mensual"}
            if frecuencia not in FRECUENCIAS_VALIDAS:
                frecuencia = "diario"

            if not codigo:
                flash("Debe ingresar un código de cliente.", "warning")
                return redirect(url_for("app_rutas.nuevo_cliente"))

            hoy = local_date()
            cliente = Cliente.query.filter_by(codigo=codigo).first()

            # ======================================================
            # 🔁 Renovación de cliente cancelado
            # ======================================================
            if cliente and cliente.cancelado:
                nuevo = Cliente(
                    nombre=cliente.nombre,
                    codigo=cliente.codigo,
                    direccion=direccion or cliente.direccion or "",
                    telefono=telefono or cliente.telefono or "",
                    orden=orden,
                    fecha_creacion=hoy,
                    ultimo_abono_fecha=None,
                    saldo=0.0,
                    cancelado=False,
                )
                db.session.add(nuevo)
                db.session.flush()

                # mover otros para abajo (MISMA LÓGICA DEL INDEX)
                Cliente.query.filter(
                    Cliente.id != nuevo.id,
                    Cliente.cancelado == False,
                    Cliente.orden >= nuevo.orden
                ).update({Cliente.orden: Cliente.orden + 1}, synchronize_session=False)

                # préstamo
                if monto > 0:
                    saldo_total = monto + (monto * (interes / 100.0))
                    prestamo = Prestamo(
                        cliente_id=nuevo.id,
                        monto=monto,
                        saldo=saldo_total,
                        fecha=hoy,
                        interes=interes,
                        plazo=plazo,
                        frecuencia=frecuencia,
                    )
                    mov = MovimientoCaja(
                        tipo="prestamo",
                        monto=monto,
                        descripcion=f"Renovación del préstamo para {nuevo.nombre}",
                        fecha=hora_actual(),
                    )
                    nuevo.saldo = saldo_total
                    db.session.add_all([prestamo, mov])

                eliminar_cache_resumen_hoy()
                db.session.commit()

                if monto > 0:
                    actualizar_liquidacion_por_movimiento(hoy, commit=False)
                    db.session.commit()
                flash(f"Cliente {nuevo.nombre} renovado correctamente (histórico preservado).", "success")
                return redirect(url_for("app_rutas.index", focus_abono=nuevo.id))

            # ======================================================
            # 🚫 Ya existe activo
            # ======================================================
            if cliente and not cliente.cancelado:
                flash("Ese código ya pertenece a un cliente activo.", "warning")
                return redirect(url_for("app_rutas.nuevo_cliente"))

            # ======================================================
            # 🆕 Nuevo cliente
            # ======================================================
            nuevo = Cliente(
                nombre=nombre or codigo,
                codigo=codigo,
                direccion=direccion or "",
                telefono=telefono or "",
                orden=orden,
                fecha_creacion=hoy,
                cancelado=False,
            )
            db.session.add(nuevo)
            db.session.flush()

            # mover otros para abajo exactamente igual que index
            Cliente.query.filter(
                Cliente.id != nuevo.id,
                Cliente.cancelado == False,
                Cliente.orden >= nuevo.orden
            ).update({Cliente.orden: Cliente.orden + 1}, synchronize_session=False)

            # préstamo inicial
            if monto > 0:
                saldo_total = monto + (monto * (interes / 100.0))
                prestamo = Prestamo(
                    cliente_id=nuevo.id,
                    monto=monto,
                    saldo=saldo_total,
                    fecha=hoy,
                    interes=interes,
                    plazo=plazo,
                    frecuencia=frecuencia,
                )
                mov = MovimientoCaja(
                    tipo="prestamo",
                    monto=monto,
                    descripcion=f"Préstamo inicial a {nuevo.nombre}",
                    fecha=hora_actual(),
                )
                nuevo.saldo = saldo_total
                db.session.add_all([prestamo, mov])

            eliminar_cache_resumen_hoy()
            db.session.commit()

            if monto > 0:
                actualizar_liquidacion_por_movimiento(hoy, commit=False)
                db.session.commit()

            flash(f"Cliente {nuevo.nombre} creado correctamente.", "success")
            return redirect(url_for("app_rutas.index", focus_abono=nuevo.id))

        except Exception as e:
            db.session.rollback()
            print(f"[ERROR nuevo_cliente] {e}")
            flash("Ocurrió un error inesperado al crear o renovar el cliente.", "danger")
            return redirect(url_for("app_rutas.nuevo_cliente"))

    # GET
    try:
        codigo_sugerido = generar_codigo_cliente()
    except Exception:
        codigo_sugerido = "000000"

    return render_template("nuevo_cliente.html", codigo_sugerido=codigo_sugerido)

# ======================================================
# 📋 CLIENTES CANCELADOS — VERSIÓN FINAL (detecta renovados por código activo)
# ======================================================
@app_rutas.route("/clientes_cancelados")
@login_required
def clientes_cancelados_view():
    """
    Muestra todos los clientes cancelados (cancelado=True y saldo=0),
    conservando el histórico y marcando en verde los que fueron renovados.
    Se considera 'renovado' si existe otro cliente activo con el mismo código.
    """
    from datetime import datetime

    clientes_cancelados = (
        Cliente.query
        .filter(Cliente.cancelado == True, Cliente.saldo <= 0.01)
        .order_by(Cliente.orden.asc().nullslast())
        .all()
    )

    data = []
    for c in clientes_cancelados:
        if not c.prestamos:
            continue

        prestamo = max(c.prestamos, key=lambda p: p.fecha)
        fecha_salida = c.ultimo_abono_fecha or prestamo.fecha
        salida_total = prestamo.monto + (prestamo.monto * (prestamo.interes or 0) / 100)
        ultimo_abono_monto = 0.0

        # 💚 Nuevo criterio de renovación:
        # existe otro cliente activo con el mismo código
        renovado = Cliente.query.filter(
            Cliente.codigo == c.codigo,
            Cliente.cancelado == False,
            Cliente.id != c.id
        ).first() is not None

        # 🧮 Días de duración
        try:
            dias = (fecha_salida - prestamo.fecha).days if fecha_salida else 0
        except TypeError:
            dias = 0

        # 💰 Último abono
        if prestamo.abonos:
            ultimo = max(prestamo.abonos, key=lambda a: a.fecha)
            ultimo_abono_monto = ultimo.monto

        data.append({
            "id": c.id,
            "orden": c.orden,
            "codigo": c.codigo,
            "dias": dias,
            "fecha_salida": fecha_salida.strftime("%d-%m-%Y") if fecha_salida else "—",
            "nombre": c.nombre,
            "salida_total": salida_total,
            "ultimo_abono_monto": ultimo_abono_monto,
            "saldo": round(c.saldo or 0.0, 2),
            "renovado": renovado,
        })

    total_cancelados = len(data)
    total_renovados = sum(1 for c in data if c["renovado"])

    return render_template(
        "clientes_cancelados.html",
        clientes=data,
        total_cancelados=total_cancelados,
        total_renovados=total_renovados
    )


# ======================================================
# 🧹 LIMPIAR CLIENTES CANCELADOS (versión FINAL mejorada)
# ======================================================
@app_rutas.route("/limpiar_cancelados")
@login_required
def limpiar_cancelados():
    """
    Elimina préstamos antiguos con saldo cero (más de 180 días),
    manteniendo la base de datos limpia sin afectar registros recientes.
    """
    from datetime import timedelta

    try:
        # 🗓️ Fecha límite (hace 180 días desde hoy)
        limite = local_date() - timedelta(days=180)

        # 🧾 Buscar y eliminar préstamos viejos cancelados o liquidados
        prestamos_viejos = Prestamo.query.filter(
            Prestamo.saldo <= 0,
            Prestamo.fecha < limite
        ).delete(synchronize_session=False)

        db.session.commit()
        flash(f"🧹 Se limpiaron {prestamos_viejos} préstamos antiguos (anteriores a {limite.strftime('%d/%m/%Y')}).", "info")

    except Exception as e:
        db.session.rollback()
        print(f"[ERROR limpiar_cancelados] {e}")
        flash("⚠️ Error al intentar limpiar los préstamos antiguos.", "danger")

    return redirect(url_for("app_rutas.clientes_cancelados_view"))

# ======================================================
# 🔁 REACTIVAR CLIENTE DESDE CANCELADOS (versión FINAL ✅ corregida)
# ======================================================
@app_rutas.route("/reactivar_cliente/<int:cliente_id>", methods=["POST"])
@login_required
def reactivar_cliente(cliente_id):
    """
    Reactiva un cliente cancelado, dejando su registro anterior como histórico.
    - El cliente original se conserva como cancelado.
    - Se crea un nuevo cliente activo con los mismos datos base.
    - Si se ingresa deuda, se suma al saldo y se registra salida en caja.
    """
    from sqlalchemy import func

    # ======================================================
    # 🔍 1️⃣ Obtener cliente y verificar estado
    # ======================================================
    cliente_antiguo = Cliente.query.get_or_404(cliente_id)

    if not cliente_antiguo.cancelado:
        msg = f"⚠️ El cliente {cliente_antiguo.nombre} ya está activo."
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"ok": False, "error": msg}), 400
        flash(msg, "info")
        return redirect(url_for("app_rutas.clientes_cancelados_view"))

    # ======================================================
    # 💾 1.5️⃣ Asegurar que el antiguo quede guardado como histórico
    # ======================================================
    # Guardar los valores antes de hacer commit (para evitar DetachedInstanceError)
    codigo_old = cliente_antiguo.codigo
    orden_old = cliente_antiguo.orden or 1
    nombre_old = cliente_antiguo.nombre
    direccion_old = cliente_antiguo.direccion

    cliente_antiguo.cancelado = True
    cliente_antiguo.ultimo_abono_fecha = hora_actual()

    db.session.commit()  # 🧩 Guardamos antes de crear el nuevo
    db.session.expunge(cliente_antiguo)  # 🔒 Lo sacamos de la sesión actual

    # ======================================================
    # 🧩 2️⃣ Crear nuevo cliente activo (manteniendo el antiguo como histórico)
    # ======================================================
    nuevo_cliente = Cliente(
        codigo=codigo_old,
        orden=orden_old,
        nombre=nombre_old,
        direccion=direccion_old,
        saldo=0.0,
        fecha_creacion=local_date(),
        ultimo_abono_fecha=None,
        cancelado=False
    )
    db.session.add(nuevo_cliente)
    db.session.flush()  # ✅ Obtener el ID antes de continuar

    # ======================================================
    # 💰 3️⃣ Capturar deuda o abono desde formulario
    # ======================================================
    try:
        deuda_pendiente = float(request.form.get("abono", 0) or 0)
    except ValueError:
        deuda_pendiente = 0.0

    # ======================================================
    # 💵 4️⃣ Crear préstamo asociado al nuevo cliente
    # ======================================================
    nuevo_prestamo = Prestamo(
        cliente_id=nuevo_cliente.id,
        monto=deuda_pendiente,
        interes=0.0,
        plazo=0,
        fecha=local_date(),
        saldo=deuda_pendiente,
        frecuencia="diario",
    )
    db.session.add(nuevo_prestamo)

    # ======================================================
    # 💸 5️⃣ Registrar movimiento en caja si hay deuda
    # ======================================================
    if deuda_pendiente > 0:
        mov = MovimientoCaja(
            tipo="salida",
            monto=deuda_pendiente,
            descripcion=f"Reactivación de {nuevo_cliente.nombre} — deuda pendiente",
            fecha=hora_actual(),
        )
        db.session.add(mov)

    # ======================================================
    # 🧮 6️⃣ Calcular saldo y actualizar estados
    # ======================================================
    nuevo_cliente.saldo = deuda_pendiente

    # ======================================================
    # 💾 7️⃣ Guardar cambios y actualizar liquidación
    # ======================================================
    db.session.commit()
    actualizar_liquidacion_por_movimiento(local_date())

    # ======================================================
    # 💬 8️⃣ Respuesta final (Fetch o navegación normal)
    # ======================================================
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify({
            "ok": True,
            "id": nuevo_cliente.id,
            "nombre": nuevo_cliente.nombre,
            "saldo": float(nuevo_cliente.saldo),
            "deuda": float(deuda_pendiente),
        }), 200

    flash(f"🟢 Cliente {nuevo_cliente.nombre} renovado correctamente.", "success")
    return redirect(url_for("app_rutas.index"))

# ======================================================
# ✏️ ACTUALIZAR ORDEN DE CLIENTE — con desplazamiento automático
# ======================================================
@app_rutas.route("/actualizar_orden/<int:cliente_id>", methods=["POST"])
@login_required
def actualizar_orden(cliente_id):
    from helpers import eliminar_cache_resumen_hoy

    nueva_orden = request.form.get("orden", type=int)
    if not nueva_orden or nueva_orden < 1:
        return "orden inválida", 400

    cliente = Cliente.query.get_or_404(cliente_id)
    orden_actual = cliente.orden or 9999

    if nueva_orden == orden_actual:
        return "OK"

    try:
        # ✅ REORDENAMIENTO UNIVERSAL (funciona saltos cortos y largos)
        if nueva_orden < orden_actual:
            # mover hacia arriba
            Cliente.query.filter(
                Cliente.orden >= nueva_orden,
                Cliente.orden < orden_actual,
                Cliente.cancelado == False,
                Cliente.id != cliente.id
            ).update({Cliente.orden: Cliente.orden + 1}, synchronize_session=False)
        else:
            # mover hacia abajo
            Cliente.query.filter(
                Cliente.orden <= nueva_orden,
                Cliente.orden > orden_actual,
                Cliente.cancelado == False,
                Cliente.id != cliente.id
            ).update({Cliente.orden: Cliente.orden - 1}, synchronize_session=False)

        cliente.orden = nueva_orden
        db.session.commit()

        # 🔥 invalidar cache del día
        eliminar_cache_resumen_hoy()

        return "OK"

    except Exception as e:
        db.session.rollback()
        print("[ERROR actualizar_orden]", e)
        return "error interno", 500

# ======================================================
# ❌ ELIMINAR CLIENTE — VERSIÓN FINAL (prestamo_revertido + capital real)
# ======================================================
@app_rutas.route("/eliminar_cliente/<int:cliente_id>", methods=["POST"])
@login_required
def eliminar_cliente(cliente_id):
    try:
        cliente = Cliente.query.get_or_404(cliente_id)

        # ⚠️ Caso 1: Ya estaba cancelado
        if cliente.cancelado:
            msg = f"⚠️ El cliente {cliente.nombre} ya estaba cancelado."
            if request.headers.get("X-Requested-With") == "fetch":
                return jsonify({"ok": False, "error": msg}), 400
            flash(msg, "info")
            return redirect(url_for("app_rutas.index"))

        print(f"\n🧾 Eliminando cliente {cliente.nombre}...")

        # ------------------------------------------------------
        # 1️⃣ Calcular CAPITAL pendiente REAL (sin intereses)
        # ------------------------------------------------------
        capital_total = sum((p.monto or 0) for p in cliente.prestamos)
        total_abonos = sum((a.monto or 0) for p in cliente.prestamos for a in p.abonos)
        capital_pendiente = capital_total - total_abonos

        # ------------------------------------------------------
        # 2️⃣ Eliminar préstamos y abonos asociados
        # ------------------------------------------------------
        prestamos_a_eliminar = list(cliente.prestamos)
        for p in prestamos_a_eliminar:
            db.session.delete(p)

        # ------------------------------------------------------
        # 3️⃣ Eliminar movimientos de caja relacionados anteriores
        # ------------------------------------------------------
        if cliente.nombre:
            movs_previos = MovimientoCaja.query.filter(
                MovimientoCaja.descripcion.ilike(f"%{cliente.nombre}%")
            ).all()
            for m in movs_previos:
                db.session.delete(m)

        # ------------------------------------------------------
        # 4️⃣ Marcar cliente como cancelado
        # ------------------------------------------------------
        cliente.cancelado = True
        cliente.saldo = 0.0

        # ------------------------------------------------------
        # 5️⃣ Registrar REINTEGRO a caja SOLO del capital pendiente
        # ------------------------------------------------------
        if capital_pendiente > 0:
            mov_reverso = MovimientoCaja(
                tipo="prestamo_revertido",
                monto=capital_pendiente,
                descripcion=f"♻️ Reversión de capital del cliente {cliente.nombre}",
                fecha=hora_actual(),
            )
            db.session.add(mov_reverso)

        # ------------------------------------------------------
        # 6️⃣ Guardar cambios
        # ------------------------------------------------------
        db.session.commit()
        actualizar_liquidacion_por_movimiento(local_date())

        # ------------------------------------------------------
        # 7️⃣ Respuesta flexible (HTML o AJAX)
        # ------------------------------------------------------
        msg_ok = f"🗑️ Cliente {cliente.nombre} eliminado correctamente."
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"ok": True, "mensaje": msg_ok, "cliente_id": cliente.id}), 200

        flash(msg_ok, "success")
        return redirect(url_for("app_rutas.index"))

    except Exception as e:
        db.session.rollback()
        print(f"[ERROR eliminar_cliente] {e}")
        msg_err = "❌ Ocurrió un error al eliminar el cliente."
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"ok": False, "error": msg_err}), 500
        flash(msg_err, "danger")
        return redirect(url_for("app_rutas.index"))

# ======================================================
# 💵 OTORGAR PRÉSTAMO A CLIENTE (VERSIÓN CORREGIDA)
# ======================================================
@app_rutas.route("/otorgar_prestamo/<int:cliente_id>", methods=["POST"])
@login_required
def otorgar_prestamo(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)

    try:
        monto = float(request.form.get("monto", 0))
        interes = float(request.form.get("interes", 0))
        plazo = int(request.form.get("plazo") or 0)
    except ValueError:
        flash("Valores de préstamo inválidos.", "danger")
        return redirect(url_for("app_rutas.index"))

    if monto <= 0:
        flash("El monto debe ser mayor a 0", "warning")
        return redirect(url_for("app_rutas.index"))

    hoy = local_date()

    # 🔒 (Opcional) NO permitir otro préstamo si ya tiene uno con saldo > 0
    prestamo_activo = (
        Prestamo.query
        .filter(Prestamo.cliente_id == cliente.id, Prestamo.saldo > 0)
        .order_by(Prestamo.fecha.desc())
        .first()
    )
    if prestamo_activo:
        flash("Este cliente ya tiene un préstamo activo.", "warning")
        return redirect(url_for("app_rutas.index", focus_abono=cliente.id))

    # 💰 Calcular saldo total con interés
    saldo_con_interes = monto + (monto * (interes / 100.0))

    # 🧾 Crear préstamo nuevo
    prestamo = Prestamo(
        cliente_id=cliente.id,
        monto=monto,
        interes=interes,
        plazo=plazo,
        fecha=hoy,
        saldo=saldo_con_interes,
        frecuencia="diario",              # o lo que uses por defecto
        ultima_aplicacion_interes=hoy,    # para que quede coherente
    )
    db.session.add(prestamo)

    # 🧍‍♂️ Sincronizar el CLIENTE con este nuevo préstamo
    cliente.monto = monto
    cliente.interes = interes
    cliente.plazo = plazo
    cliente.saldo = saldo_con_interes
    cliente.cancelado = False           # ✅ quedará "activo"
    cliente.ultimo_abono_fecha = None   # todavía no tiene abonos

    # 💸 Registrar movimiento en caja (yo usaría tipo="prestamo" para unificar)
    mov = MovimientoCaja(
        tipo="prestamo",  # 👈 antes tenías "salida"; si en otros lados usas "prestamo", mejor esto
        monto=monto,
        descripcion=f"Préstamo a {cliente.nombre}",
        fecha=hora_actual(),
    )
    db.session.add(mov)

    # 🧮 Actualizar cache / liquidación
    eliminar_cache_resumen_hoy()
    db.session.commit()

    actualizar_liquidacion_por_movimiento(hoy, commit=False)
    db.session.commit()

    flash(f"Préstamo de ${monto:.0f} otorgado a {cliente.nombre}", "success")
    return redirect(url_for("app_rutas.index", focus_abono=cliente.id))

# ======================================================
# 🧾 HISTORIAL DE ABONOS — para modal (vista cancelados)
# ======================================================
@app_rutas.route("/historial_abonos_html/<int:cliente_id>")
@login_required
def historial_abonos_html(cliente_id):
    """Devuelve el historial de abonos de un cliente en formato HTML para el modal."""
    cliente = Cliente.query.get_or_404(cliente_id)
    prestamo = cliente.prestamos[-1] if cliente.prestamos else None

    if not prestamo:
        return "<p class='text-center text-muted'>Este cliente no tiene préstamos registrados.</p>"

    abonos = sorted(prestamo.abonos, key=lambda a: a.fecha, reverse=True)
    if not abonos:
        return "<p class='text-center text-muted'>No se registran abonos para este cliente.</p>"

    saldo_actual = prestamo.saldo + sum(a.monto for a in abonos)
    html = f"""
    <h5 class="text-center mb-3">Historial de Abonos — {cliente.nombre}</h5>
    <div class="table-responsive">
      <table class="table table-sm table-bordered table-striped align-middle text-center">
        <thead class="table-dark">
          <tr>
            <th>#</th>
            <th>Fecha</th>
            <th>Hora</th>
            <th>Monto</th>
            <th>Saldo restante</th>
          </tr>
        </thead>
        <tbody>
    """
    for i, ab in enumerate(abonos, 1):
        fecha = ab.fecha.strftime("%d-%m-%Y")
        hora = ab.fecha.strftime("%H:%M:%S")
        saldo_actual -= ab.monto
        html += f"""
          <tr>
            <td>{i}</td>
            <td>{fecha}</td>
            <td>{hora}</td>
            <td>${ab.monto:,.2f}</td>
            <td>${saldo_actual:,.2f}</td>
          </tr>
        """
    html += "</tbody></table></div>"
    return html

# ======================================================
# 🧾 HISTORIAL DE ABONOS — CORREGIDO (orden y saldo real)
# ======================================================
@app_rutas.route("/historial_abonos/<int:cliente_id>")
@login_required
def historial_abonos_json(cliente_id):
    """Devuelve el historial de abonos y datos del préstamo en formato JSON."""
    from datetime import datetime

    cliente = Cliente.query.get_or_404(cliente_id)
    prestamo = (
        Prestamo.query.filter_by(cliente_id=cliente.id)
        .order_by(Prestamo.id.desc())
        .first()
    )

    if not prestamo:
        return jsonify({"ok": False, "error": "El cliente no tiene préstamos registrados."})

    # 🔹 Ordenar por fecha ascendente (más antiguos primero)
    abonos = sorted(prestamo.abonos, key=lambda a: a.fecha or datetime.min)
    if not abonos:
        return jsonify({"ok": False, "error": "No se registran abonos para este cliente."})

    # 🔹 Calcular el saldo histórico correctamente
    saldo_restante = prestamo.monto + (prestamo.monto * (prestamo.interes or 0) / 100)
    data_abonos = []

    for ab in abonos:
        fecha = ab.fecha.strftime("%d-%m-%Y") if ab.fecha else "-"
        hora = ab.fecha.strftime("%H:%M:%S") if ab.fecha else "-"
        saldo_restante -= ab.monto or 0
        data_abonos.append({
            "id": ab.id,
            "codigo": cliente.codigo,
            "fecha": fecha,
            "hora": hora,
            "monto": ab.monto or 0,
            "saldo": round(max(saldo_restante, 0), 2)
        })

    # 🔹 Información del préstamo
    data_prestamo = {
        "nombre": cliente.nombre,
        "fecha_inicial": prestamo.fecha.strftime("%d-%m-%Y") if prestamo.fecha else "-",
        "monto": float(prestamo.monto or 0),
        "total": round(prestamo.monto + (prestamo.monto * (prestamo.interes or 0) / 100), 2),
        "cuota": float(getattr(prestamo, "cuota", 0)),
        "modo": prestamo.frecuencia or "-",
        "datos": getattr(prestamo, "detalle", "-"),
        "saldo": float(prestamo.saldo or 0),
    }

    return jsonify({
        "ok": True,
        "prestamo": data_prestamo,
        "abonos": data_abonos
    })


# ======================================================
# 💰 REGISTRAR ABONO POR CÓDIGO (versión estable, permite abonar cancelados)
# ======================================================
@app_rutas.route("/registrar_abono_por_codigo", methods=["POST"])
@login_required
def registrar_abono_por_codigo():
    from sqlalchemy import func

    codigo = request.form.get("codigo", "").strip()
    monto = float(request.form.get("monto") or 0)
    es_fetch = request.headers.get("X-Requested-With") == "fetch"

    # ⚠️ Validar monto
    if monto <= 0:
        msg = "Monto inválido."
        return (jsonify({"ok": False, "error": msg}), 400) if es_fetch else (
            flash(msg, "danger"), redirect(url_for("app_rutas.index"))
        )[1]

    # 🔍 Buscar cliente
    cliente = Cliente.query.filter_by(codigo=codigo).first()
    if not cliente:
        msg = f"Código {codigo} no encontrado."
        return (jsonify({"ok": False, "error": msg}), 404) if es_fetch else (
            flash(msg, "danger"), redirect(url_for("app_rutas.index"))
        )[1]

    # 👇 YA NO BLOQUEAMOS POR CANCELADO
    # antes aquí estaba el error

    # 🔎 Buscar préstamo activo
    prestamo = (
        Prestamo.query.filter(
            Prestamo.cliente_id == cliente.id,
            Prestamo.saldo > 0
        )
        .order_by(Prestamo.fecha.desc(), Prestamo.id.desc())
        .first()
    )
    if not prestamo:
        msg = "Cliente sin préstamos pendientes."
        return (jsonify({"ok": False, "error": msg}), 400) if es_fetch else (
            flash(msg, "warning"), redirect(url_for("app_rutas.index"))
        )[1]

    # 📈 Verificar interés mensual
    interes_aplicado = False
    dias_transcurridos = 0
    if (prestamo.frecuencia or "").lower() == "mensual":
        dias_transcurridos = (local_date() - (prestamo.ultima_aplicacion_interes or prestamo.fecha)).days
        if dias_transcurridos >= 30:
            interes_extra = prestamo.monto * (prestamo.interes or 0) / 100
            prestamo.saldo += interes_extra
            prestamo.ultima_aplicacion_interes = local_date()
            interes_aplicado = True

            db.session.add(MovimientoCaja(
                tipo="entrada_manual",
                monto=interes_extra,
                descripcion=f"Interés mensual aplicado a {cliente.nombre}",
                fecha=hora_actual()
            ))

    # 💵 Registrar abono
    abono = Abono(
        prestamo_id=prestamo.id,
        monto=monto,
        fecha=hora_actual()
    )
    db.session.add(abono)

    # 🔄 Actualizar saldos
    prestamo.saldo = max(0.0, (prestamo.saldo or 0) - monto)
    cliente.saldo = (
        db.session.query(func.coalesce(func.sum(Prestamo.saldo), 0.0))
        .filter(Prestamo.cliente_id == cliente.id)
        .scalar()
        or 0.0
    )
    cliente.ultimo_abono_fecha = local_date()

    cancelado = False
    saldo_redondeado = round(cliente.saldo, 2)

    # si queda en 0 ⇒ cancelar
    if saldo_redondeado <= 0:
        cliente.saldo = 0.0
        cliente.cancelado = True
        cancelado = True
    else:
        # si estaba cancelado y vuelve a tener saldo ⇒ reactivar
        if cliente.cancelado:
            cliente.cancelado = False

    db.session.commit()
    actualizar_liquidacion_por_movimiento(local_date())

    # ✅ Respuesta JSON o redirección
    if es_fetch:
        return jsonify({
            "ok": True,
            "cliente_id": cliente.id,
            "cliente_nombre": cliente.nombre,
            "saldo": float(cliente.saldo),
            "cancelado": cancelado,
            "monto": monto,
            "interes_aplicado": interes_aplicado
        }), 200

    # Navegador normal
    flash(f"💰 Abono de ${monto:.2f} registrado para {cliente.nombre}", "success")
    if cancelado:
        flash(f"✅ {cliente.nombre} quedó en saldo 0 y fue movido a cancelados.", "info")
    return redirect(url_for("app_rutas.index"))


# ======================================================
# 💹 GANANCIAS DEL MES — por interés
# ======================================================
@app_rutas.route("/ganancias_mes")
@login_required
def ganancias_mes_view():
    # ✅ Se llama directamente desde el módulo tiempo
    import tiempo
    inicio, fin, _ahora = tiempo.mes_actual_chile_bounds()

    q = (
        db.session.query(Prestamo, Cliente)
        .join(Cliente, Prestamo.cliente_id == Cliente.id)
        .filter(Prestamo.fecha >= inicio, Prestamo.fecha <= fin)
        .order_by(Prestamo.fecha.asc(), Cliente.codigo.asc())
    )

    filas = []
    total_venta = 0
    total_ganancia = 0

    for p, c in q.all():
        venta = float(p.monto or 0)
        interes = float(p.interes or 0)
        ganancia = venta * (interes / 100)

        filas.append({
            "codigo": c.codigo,
            "fecha": p.fecha,
            "nombre": c.nombre,
            "venta": str(int(round(venta))),
            "interes": str(interes),
            "ganancia": str(int(round(ganancia))),
        })

        total_venta += int(round(venta))
        total_ganancia += int(round(ganancia))

    return render_template(
        "ganancias_mes.html",
        filas=filas,
        total_venta=str(total_venta),
        total_ganancia=str(total_ganancia),
        fecha_inicio=inicio,
        fecha_fin=fin
    )


# ======================================================
# 🗑️ ELIMINAR ABONO (reactiva y recalcula caja histórica)
# ======================================================
@app_rutas.route("/eliminar_abono/<int:abono_id>", methods=["POST"])
@login_required
def eliminar_abono(abono_id):
    from sqlalchemy import func
    try:
        abono = Abono.query.get_or_404(abono_id)
        prestamo = abono.prestamo
        cliente = prestamo.cliente

        # 🗓️ Guardar la fecha original del abono (zona Chile ya normalizada en tu modelo)
        fecha_abono_dt = abono.fecha
        fecha_abono = fecha_abono_dt.date() if hasattr(fecha_abono_dt, "date") else local_date()

        # 🔁 Devolver el monto al saldo del préstamo
        prestamo.saldo = float(prestamo.saldo or 0) + float(abono.monto or 0)

        # 🗑️ Borrar el abono y recalcular saldo del cliente
        monto_borrado = float(abono.monto or 0)
        db.session.delete(abono)
        db.session.flush()

        total_saldo_cliente = (
            db.session.query(func.coalesce(func.sum(Prestamo.saldo), 0.0))
            .filter(Prestamo.cliente_id == cliente.id)
            .scalar()
            or 0.0
        )
        cliente.saldo = float(total_saldo_cliente)

        # 🔄 Si estaba cancelado y ahora vuelve a deber → reactivar
        reactivado = False
        if cliente.cancelado and round(cliente.saldo, 2) > 0:
            cliente.cancelado = False
            # Usamos fecha local (solo fecha) para "volver a estar activo hoy"
            cliente.ultimo_abono_fecha = local_date()
            reactivado = True

        db.session.commit()

        # 📅 Recalcular liquidaciones desde la fecha del abono hasta hoy (propaga el cambio)
        def _recalc_desde(fecha_inicio):
            d = fecha_inicio
            hoy = local_date()
            while d <= hoy:
                actualizar_liquidacion_por_movimiento(d, commit=True)
                d = d + timedelta(days=1)

        _recalc_desde(fecha_abono)

        # ✅ Respuesta AJAX
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({
                "ok": True,
                "cliente_id": cliente.id,
                "saldo": float(cliente.saldo),
                "cancelado": cliente.cancelado,
                "reactivado": reactivado,
                "monto_borrado": monto_borrado
            }), 200

        # Navegador normal
        flash(f"🗑️ Abono de ${monto_borrado:.2f} eliminado correctamente.", "info")
        if reactivado:
            flash(f"🔁 {cliente.nombre} fue reactivado.", "success")
            return redirect(url_for("app_rutas.index", resaltar=cliente.id))
        return redirect(url_for("app_rutas.index"))

    except Exception as e:
        db.session.rollback()
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"ok": False, "error": str(e)}), 500
        flash("❌ Error interno al eliminar abono.", "danger")
        return redirect(url_for("app_rutas.index"))


# ======================================================
# 💼 CAJA — MOVIMIENTO GENÉRICO (entrada_manual / salida / gasto)
# ======================================================
@app_rutas.route("/caja/<tipo>", methods=["POST"])
@login_required
def caja_movimiento(tipo):
    tipos_validos = ["entrada_manual", "salida", "gasto"]
    if tipo not in tipos_validos:
        flash("Tipo inválido", "danger")
        return redirect(url_for("app_rutas.liquidacion_view"))

    try:
        monto = float(request.form.get("monto", 0))
    except ValueError:
        monto = 0

    if monto <= 0:
        flash("Monto inválido", "warning")
        return redirect(url_for("app_rutas.liquidacion_view"))

    descripcion = request.form.get("descripcion", f"{tipo.replace('_', ' ').capitalize()} manual")

    # 🚫 Evitar registrar préstamos como salidas
    if tipo == "salida" and ("préstamo" in descripcion.lower() or "prestamo" in descripcion.lower()):
        flash("Los préstamos no deben registrarse como salidas. Usa el módulo de préstamos.", "warning")
        return redirect(url_for("app_rutas.liquidacion_view"))

    # 💾 Registrar movimiento en caja
    mov = MovimientoCaja(
        tipo=tipo,
        monto=monto,
        descripcion=descripcion,
        fecha=hora_actual(),  # ✅ Corregido: hora local de Chile
    )
    db.session.add(mov)
    db.session.commit()

    # 🔄 Actualizar liquidación del día
    actualizar_liquidacion_por_movimiento(local_date())

    flash(f"{tipo.replace('_', ' ').capitalize()} registrada correctamente en la caja.", "success")
    return redirect(url_for("app_rutas.liquidacion_view"))


# ======================================================
# 💵 CAJA — ENTRADA DIRECTA
# ======================================================
@app_rutas.route("/caja_entrada", methods=["POST"])
@login_required
def caja_entrada():
    return caja_movimiento("entrada_manual")


# ======================================================
# 💸 CAJA — SALIDA DIRECTA
# ======================================================
@app_rutas.route("/caja_salida", methods=["POST"])
@login_required
def caja_salida():
    return caja_movimiento("salida")


# ======================================================
# 🧾 CAJA — GASTO DIRECTO
# ======================================================
@app_rutas.route("/caja_gasto", methods=["POST"])
@login_required
def caja_gasto():
    monto = request.form.get("monto", type=float)
    descripcion = request.form.get("descripcion", "")

    if monto and monto > 0:
        mov = MovimientoCaja(
            tipo="gasto",
            monto=monto,
            descripcion=descripcion or "Gasto general",
            fecha=hora_actual(),  # ✅ hora real Chile (UTC)
        )
        db.session.add(mov)
        db.session.commit()
        actualizar_liquidacion_por_movimiento(local_date())
        flash(f"🧾 Gasto de ${monto:.2f} registrado correctamente.", "warning")
    else:
        flash("Debe ingresar un monto válido.", "danger")

    return redirect(url_for("app_rutas.liquidacion_view"))


# ======================================================
# 🔎 VERIFICAR CAJA — ABONOS MAL CLASIFICADOS
# ======================================================
@app_rutas.route("/verificar_caja")
@login_required
def verificar_caja():
    abonos_incorrectos = (
        MovimientoCaja.query.filter(
            MovimientoCaja.tipo == "entrada_manual",
            MovimientoCaja.descripcion.ilike("%abono%")
        ).count()
    )

    if abonos_incorrectos == 0:
        flash("✅ Caja limpia: no hay abonos mal clasificados.", "success")
    else:
        flash(f"🚨 Hay {abonos_incorrectos} abonos mal clasificados en 'entrada_manual'.", "danger")

    return redirect(url_for("app_rutas.liquidacion_view"))


# ======================================================
# 🩺 ESTADO DE CAJA (JSON)
# ======================================================
@app_rutas.route("/revisar_caja_estado")
@login_required
def revisar_caja_estado():
    errores = (
        MovimientoCaja.query.filter(
            MovimientoCaja.tipo == "entrada_manual",
            MovimientoCaja.descripcion.ilike("%abono%")
        ).count()
    )
    return jsonify({"errores": errores})


# ======================================================
# 🧹 REPARAR CAJA — ELIMINA ABONOS MAL CLASIFICADOS
# ======================================================
@app_rutas.route("/reparar_caja")
@login_required
def reparar_caja():
    abonos_erroneos = (
        MovimientoCaja.query.filter(
            MovimientoCaja.tipo == "entrada_manual",
            MovimientoCaja.descripcion.ilike("%abono%")
        ).all()
    )

    if not abonos_erroneos:
        flash("✅ No se encontraron abonos mal clasificados.", "success")
        return redirect(url_for("app_rutas.liquidacion_view"))

    for m in abonos_erroneos:
        db.session.delete(m)
    db.session.commit()

    liq = actualizar_liquidacion_por_movimiento(local_date())
    flash(
        f"🧹 Se eliminaron {len(abonos_erroneos)} abonos mal clasificados y se recalculó la liquidación del {liq.fecha}.",
        "info",
    )
    return redirect(url_for("app_rutas.liquidacion_view"))


# ======================================================
# 📊 LIQUIDACIÓN DEL DÍA (con arrastre y totales coherentes)
# ======================================================
@app_rutas.route("/liquidacion")
@login_required
def liquidacion_view():
    try:
        hoy = local_date()

        # 1) Garantiza registro de liquidación de hoy con caja_anterior arrastrada
        crear_liquidacion_para_fecha(hoy)

        # 2) Recalcula totales del día usando movimientos y abonos (no doble commit)
        liq = actualizar_liquidacion_por_movimiento(hoy, commit=False)
        db.session.commit()

        # 3) Resumen global (caja total acumulada y cartera)
        resumen = obtener_resumen_total()
        cartera_total = float(resumen.get("cartera_total", 0.0))

        # 4) Render compatible con plantilla `liquidacion.html`
        return render_template(
            "liquidacion.html",
            hoy=hoy,
            liq=liq,
            liquidaciones=[liq],            # para la tabla del día
            total_caja=liq.caja,            # coincide con “Caja Final” del día
            cartera_total=cartera_total,
            resumen=resumen,
        )

    except Exception as e:
        print("[ERROR liquidacion_view]", e)
        flash("❌ Error al calcular la liquidación del día.", "danger")
        return redirect(url_for("app_rutas.index"))

# ======================================================
# 🗂️ LIQUIDACIONES — HISTÓRICO Y RANGO DE FECHAS (con días vacíos)
# ======================================================
@app_rutas.route("/liquidaciones", methods=["GET"])
@login_required
def liquidaciones():
    fecha_desde = request.args.get("desde")
    fecha_hasta = request.args.get("hasta")

    # 🔎 Sin rango: últimos 10 registros reales en BD
    if not fecha_desde or not fecha_hasta:
        items = Liquidacion.query.order_by(Liquidacion.fecha.desc()).limit(10).all()
        resumen = obtener_resumen_total()
        return render_template(
            "liquidaciones.html",
            liquidaciones=items,
            fecha_desde=None,
            fecha_hasta=None,
            total_entradas=sum(l.entradas or 0 for l in items),
            total_prestamos=sum(l.prestamos_hoy or 0 for l in items),
            total_entradas_caja=sum(l.entradas_caja or 0 for l in items),
            total_salidas=sum(l.salidas or 0 for l in items),
            total_gastos=sum(l.gastos or 0 for l in items),
            total_caja=sum(l.caja or 0 for l in items),
            resumen=resumen,
            hora_chile=hora_chile,
            hora_actual=hora_actual,
        )

    # 🗓️ Rango: normaliza fechas y rellena huecos
    try:
        desde = datetime.strptime(fecha_desde, "%Y-%m-%d").date()
        hasta = datetime.strptime(fecha_hasta, "%Y-%m-%d").date()
    except ValueError:
        flash("Formato de fecha inválido (use YYYY-MM-DD).", "danger")
        return redirect(url_for("app_rutas.liquidaciones"))

    registros = {
        l.fecha: l
        for l in Liquidacion.query.filter(
            Liquidacion.fecha >= desde, Liquidacion.fecha <= hasta
        ).all()
    }

    dias = (hasta - desde).days + 1
    items = []
    for i in range(dias):
        fecha = desde + timedelta(days=i)
        liq = registros.get(fecha)
        if not liq:
            # objeto “visual” vacío para mostrar fila en la tabla
            liq = Liquidacion(
                fecha=fecha,
                caja_manual=0.0,
                entradas=0.0,
                entradas_caja=0.0,
                prestamos_hoy=0.0,
                salidas=0.0,
                gastos=0.0,
                caja=0.0,
            )
        items.append(liq)

    resumen = obtener_resumen_total()
    return render_template(
        "liquidaciones.html",
        liquidaciones=items,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        total_entradas=sum(l.entradas or 0 for l in items),
        total_prestamos=sum(l.prestamos_hoy or 0 for l in items),
        total_entradas_caja=sum(l.entradas_caja or 0 for l in items),
        total_salidas=sum(l.salidas or 0 for l in items),
        total_gastos=sum(l.gastos or 0 for l in items),
        total_caja=sum(l.caja or 0 for l in items),
        resumen=resumen,
        hora_chile=hora_chile,
        hora_actual=hora_actual,
    )


# ======================================================
# 📅 REPORTES — MOVIMIENTOS POR DÍA (entrada, abono, salida, gasto)
# ======================================================
@app_rutas.route("/movimientos_por_dia/<tipo>/<fecha>")
@login_required
def movimientos_por_dia(tipo, fecha):
    fecha_obj = datetime.strptime(fecha, "%Y-%m-%d").date()
    start, end = day_range(fecha_obj)

    if tipo == "entrada_manual":
        movimientos = (
            MovimientoCaja.query.filter(
                MovimientoCaja.tipo == "entrada_manual",
                MovimientoCaja.fecha >= start,
                MovimientoCaja.fecha < end,
            )
            .order_by(MovimientoCaja.fecha.desc())
            .all()
        )
        titulo = "💵 Entradas Manuales"
        total = sum(m.monto for m in movimientos)

    elif tipo == "abono":
        movimientos = (
            Abono.query
            .join(Prestamo, Abono.prestamo_id == Prestamo.id)
            .join(Cliente, Prestamo.cliente_id == Cliente.id)
            .filter(Abono.fecha >= start, Abono.fecha < end)
            .with_entities(Abono.fecha, Cliente.nombre, Abono.monto)
            .order_by(Abono.fecha.desc())
            .all()
        )
        titulo = "💰 Ingresos por Abonos"
        total = sum(m[2] for m in movimientos)

    elif tipo in ["salida", "gasto"]:
        movimientos = (
            MovimientoCaja.query.filter(
                MovimientoCaja.tipo == tipo,
                MovimientoCaja.fecha >= start,
                MovimientoCaja.fecha < end,
            )
            .order_by(MovimientoCaja.fecha.desc())
            .all()
        )
        titulo = "💸 Salidas" if tipo == "salida" else "🧾 Gastos"
        total = sum(m.monto for m in movimientos)

    else:
        flash("Tipo de movimiento no válido.", "danger")
        return redirect(url_for("app_rutas.liquidacion_view"))

    return render_template(
        "movimientos_por_dia.html",
        movimientos=movimientos,
        tipo=tipo,
        fecha=fecha_obj,
        total=total,
        titulo=titulo,
        hoy=local_date(),
    )

# ======================================================
# 📅 REPORTES — PRÉSTAMOS POR DÍA
# ======================================================
@app_rutas.route("/prestamos_por_dia/<fecha>")
@login_required
def prestamos_por_dia(fecha):
    from datetime import datetime
    fecha_obj = datetime.strptime(fecha, "%Y-%m-%d").date()
    start, end = day_range(fecha_obj)

    prestamos = (
        Prestamo.query
        .join(Cliente, Prestamo.cliente_id == Cliente.id)
        .filter(
            Prestamo.fecha >= start,
            Prestamo.fecha < end,
            Cliente.cancelado == False
        )
        .with_entities(Cliente.nombre, Prestamo.monto, Prestamo.fecha)
        .order_by(Prestamo.fecha.desc())
        .all()
    )

    total_prestamos = sum(p.monto for p in prestamos)
    return render_template(
        "prestamos_por_dia.html",
        prestamos=prestamos,
        fecha=fecha_obj,
        total_prestamos=total_prestamos,
    )

# ======================================================
# 🕒 TEST DE HORA LOCAL DE CHILE 🇨🇱
# ======================================================
@app_rutas.route("/test_hora")
def test_hora():
    """
    Ruta de prueba para verificar que la hora y fecha local de Chile
    se estén registrando y mostrando correctamente en el sistema.
    """
    from tiempo import hora_actual, local_date, to_hora_chile
    from datetime import datetime

    # 🕒 Hora actual según función interna (hora local sin tz)
    ahora = hora_actual()
    ahora_str = ahora.strftime("%Y-%m-%d %H:%M:%S")

    # 🌍 Conversión desde UTC a hora chilena (solo para validar)
    chile_str = to_hora_chile(datetime.utcnow())

    # 📅 Fecha local (solo fecha sin hora)
    fecha_local = local_date()

    return f"""
    <html>
    <head>
        <title>🕒 Test Hora Chile</title>
        <meta charset="utf-8">
        <style>
            body {{
                font-family: 'Segoe UI', sans-serif;
                background-color: #f5f5f5;
                color: #222;
                margin: 40px;
            }}
            .card {{
                background: white;
                border-radius: 10px;
                padding: 20px 30px;
                box-shadow: 0 3px 8px rgba(0,0,0,0.2);
                max-width: 500px;
            }}
            h2 {{
                color: #0066cc;
                margin-bottom: 20px;
            }}
            p {{
                font-size: 16px;
                line-height: 1.6;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <h2>🕒 Test de Hora Local de Chile 🇨🇱</h2>
            <p><b>Hora actual (hora_actual):</b> {ahora_str}</p>
            <p><b>Hora UTC convertida a Chile:</b> {chile_str}</p>
            <p><b>Fecha local:</b> {fecha_local}</p>
        </div>
    </body>
    </html>
    """


# ======================================================
# 🚫 ERROR 404 — PÁGINA NO ENCONTRADA
# ======================================================
@app_rutas.app_errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404
