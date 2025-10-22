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
VALID_USER = os.getenv("APP_USER", "mjesus40")
VALID_PASS = os.getenv("APP_PASS", "198409")

def login_required(f):
    """Protege las rutas que requieren sesión activa."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "usuario" not in session:
            return redirect(url_for("app_rutas.login"))
        return f(*args, **kwargs)
    return wrapper


# ======================================================
# 📊 DASHBOARD GENERAL — Créditos
# ======================================================
@app_rutas.route("/dashboard")
@login_required
def dashboard():
    hoy = local_date()
    start, end = day_range(hoy)

    total_clientes_activos = db.session.query(func.count(Cliente.id)) \
        .filter(Cliente.cancelado == False).scalar() or 0

    total_abonos = db.session.query(func.coalesce(func.sum(Abono.monto), 0)) \
        .filter(Abono.fecha >= start, Abono.fecha < end).scalar() or 0.0

    total_prestamos = db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0)) \
        .filter(MovimientoCaja.tipo == "prestamo",
                MovimientoCaja.fecha >= start,
                MovimientoCaja.fecha < end).scalar() or 0.0

    total_entradas = db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0)) \
        .filter(MovimientoCaja.tipo == "entrada_manual",
                MovimientoCaja.fecha >= start,
                MovimientoCaja.fecha < end).scalar() or 0.0

    total_salidas = db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0)) \
        .filter(MovimientoCaja.tipo == "salida",
                MovimientoCaja.fecha >= start,
                MovimientoCaja.fecha < end).scalar() or 0.0

    total_gastos = db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0)) \
        .filter(MovimientoCaja.tipo == "gasto",
                MovimientoCaja.fecha >= start,
                MovimientoCaja.fecha < end).scalar() or 0.0

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
        caja_total=caja_total
    )


# ======================================================
# 🏠 RUTA PRINCIPAL — CLIENTES + TARJETA DE RESUMEN
# ======================================================
@app_rutas.route("/")
@login_required
def index():
    clientes = (
        Cliente.query.filter_by(cancelado=False)
        .order_by(Cliente.orden.asc().nullsfirst(), Cliente.id.asc())
        .all()
    )

    # Reasignar orden si está roto
    for idx, c in enumerate(clientes, start=1):
        if not c.orden or c.orden != idx:
            c.orden = idx
    db.session.commit()

    hoy = local_date()
    for c in clientes:
        estado = "normal"
        if c.prestamos:
            ultimo = max(c.prestamos, key=lambda p: p.fecha)
            if ultimo.plazo:
                fecha_venc = ultimo.fecha + timedelta(days=ultimo.plazo)
                dias_pasados = (hoy - fecha_venc).days
                if 0 <= dias_pasados < 30:
                    estado = "vencido"
                elif dias_pasados >= 30:
                    estado = "moroso"
        c.estado_plazo = estado

    resumen = obtener_resumen_total()
    start, end = day_range(hoy)

    total_abonos = db.session.query(func.coalesce(func.sum(Abono.monto), 0)) \
        .filter(Abono.fecha >= start, Abono.fecha < end).scalar() or 0.0

    total_prestamos = db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0)) \
        .filter(MovimientoCaja.tipo == "prestamo",
                MovimientoCaja.fecha >= start,
                MovimientoCaja.fecha < end).scalar() or 0.0

    total_entradas = db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0)) \
        .filter(MovimientoCaja.tipo == "entrada_manual",
                MovimientoCaja.fecha >= start,
                MovimientoCaja.fecha < end).scalar() or 0.0

    total_salidas = db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0)) \
        .filter(MovimientoCaja.tipo == "salida",
                MovimientoCaja.fecha >= start,
                MovimientoCaja.fecha < end).scalar() or 0.0

    total_gastos = db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0)) \
        .filter(MovimientoCaja.tipo == "gasto",
                MovimientoCaja.fecha >= start,
                MovimientoCaja.fecha < end).scalar() or 0.0

    caja_total = total_abonos + total_entradas - (total_prestamos + total_salidas + total_gastos)

    return render_template(
        "index.html",
        clientes=clientes,
        resumen=resumen,
        hoy=hoy,
        total_abonos=total_abonos,
        total_prestamos=total_prestamos,
        total_entradas=total_entradas,
        total_salidas=total_salidas,
        total_gastos=total_gastos,
        caja_total=caja_total
    )
# ======================================================
# ✏️ EDITAR PRÉSTAMO — (GET/POST)
# ======================================================
@app_rutas.route("/editar_prestamo/<int:cliente_id>", methods=["GET", "POST"])
def editar_prestamo(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    prestamo = max(cliente.prestamos, key=lambda p: p.fecha) if cliente.prestamos else None

    # 📤 GET — devolver datos actuales
    if request.method == "GET":
        if not prestamo:
            return jsonify({"ok": False, "error": "El cliente no tiene préstamo activo."})
        return jsonify({
            "ok": True,
            "data": {
                "monto": prestamo.monto,
                "interes": prestamo.interes,
                "plazo": prestamo.plazo,
                "frecuencia": prestamo.frecuencia
            }
        })

    # 📥 POST — actualizar préstamo
    try:
        if not prestamo:
            return jsonify({"ok": False, "error": "No hay préstamo asociado a este cliente."})

        prestamo.monto = float(request.form.get("monto", prestamo.monto))
        prestamo.interes = float(request.form.get("interes", prestamo.interes))
        prestamo.plazo = int(request.form.get("plazo", prestamo.plazo))
        prestamo.frecuencia = request.form.get("frecuencia", prestamo.frecuencia)

        # Mantener saldo si ya tiene abonos
        if not prestamo.abonos or len(prestamo.abonos) == 0:
            prestamo.saldo = prestamo.monto + (prestamo.monto * prestamo.interes / 100)

        db.session.commit()
        return jsonify({"ok": True, "msg": "Préstamo actualizado correctamente."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "error": str(e)})


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
# 👥 CLIENTES CANCELADOS — LISTADO Y REACTIVACIÓN
# ======================================================
@app_rutas.route("/clientes_cancelados")
@login_required
def clientes_cancelados_view():
    clientes = Cliente.query.filter_by(cancelado=True).order_by(Cliente.nombre.asc()).all()
    total_cancelados = len(clientes)
    total_saldos = sum(c.saldo or 0 for c in clientes)
    return render_template(
        "clientes_cancelados.html",
        clientes=clientes,
        total_cancelados=total_cancelados,
        total_saldos=total_saldos,
    )


@app_rutas.route("/reactivar_cliente/<int:cliente_id>", methods=["POST"])
@login_required
def reactivar_cliente(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)

    if not cliente.cancelado:
        flash(f"El cliente {cliente.nombre} ya está activo.", "info")
        return redirect(url_for("app_rutas.clientes_cancelados_view"))

    # ✅ Reactivar cliente
    cliente.cancelado = False
    cliente.saldo = 0.0
    if hasattr(cliente, "ultimo_abono_fecha"):
        cliente.ultimo_abono_fecha = None

    db.session.commit()
    flash(f"El cliente {cliente.nombre} fue reactivado correctamente ✅", "success")
    return redirect(url_for("app_rutas.clientes_cancelados_view"))


# ======================================================
# ✏️ ACTUALIZAR ORDEN DE CLIENTE
# ======================================================
@app_rutas.route("/actualizar_orden/<int:cliente_id>", methods=["POST"])
@login_required
def actualizar_orden(cliente_id):
    nueva_orden = request.form.get("orden", type=int)
    if nueva_orden is None:
        flash("Debe ingresar un número de orden válido.", "warning")
        return redirect(url_for("app_rutas.index"))

    cliente = Cliente.query.get_or_404(cliente_id)
    cliente.orden = nueva_orden
    db.session.commit()

    flash(f"Orden del cliente {cliente.nombre} actualizada a {nueva_orden}.", "success")
    return redirect(url_for("app_rutas.index"))
# ======================================================
# 🧍‍♂️ NUEVO CLIENTE — CREACIÓN Y REACTIVACIÓN
# ======================================================
@app_rutas.route("/nuevo_cliente", methods=["GET", "POST"])
@login_required
def nuevo_cliente():
    if request.method == "POST":
        nombre = request.form.get("nombre")
        codigo = request.form.get("codigo")
        direccion = request.form.get("direccion")
        telefono = request.form.get("telefono")
        monto = request.form.get("monto", type=float)
        interes = request.form.get("interes", type=float) or 0.0
        plazo = request.form.get("plazo", type=int)
        orden = request.form.get("orden", type=int)
        frecuencia = (request.form.get("frecuencia") or "diario").strip().lower()
        FRECUENCIAS_VALIDAS = {"diario", "semanal", "quincenal", "mensual"}
        if frecuencia not in FRECUENCIAS_VALIDAS:
            frecuencia = "diario"

        if not codigo:
            flash("Debe ingresar un código de cliente.", "warning")
            return redirect(url_for("app_rutas.nuevo_cliente"))

        cliente_existente = Cliente.query.filter_by(codigo=codigo).first()

        # 🔁 Reactivar cliente cancelado
        if cliente_existente and cliente_existente.cancelado:
            cliente_existente.cancelado = False
            cliente_existente.nombre = nombre or cliente_existente.nombre
            cliente_existente.direccion = direccion or cliente_existente.direccion
            cliente_existente.telefono = telefono or cliente_existente.telefono
            cliente_existente.orden = orden or cliente_existente.orden
            cliente_existente.fecha_creacion = local_date()

            if monto and monto > 0:
                saldo_total = monto + (monto * (interes / 100.0))
                nuevo_prestamo = Prestamo(
                    cliente_id=cliente_existente.id,
                    monto=monto,
                    saldo=saldo_total,
                    fecha=local_date(),
                    interes=interes,
                    plazo=plazo,
                    frecuencia=frecuencia,
                )
                db.session.add(nuevo_prestamo)

                mov = MovimientoCaja(
                    tipo="prestamo",
                    monto=monto,
                    descripcion=f"Nuevo préstamo (reactivado) a {cliente_existente.nombre}",
                    fecha=hora_actual(),  # ✅ hora actual en Chile
                )
                db.session.add(mov)
                cliente_existente.saldo = saldo_total

            db.session.commit()
            actualizar_liquidacion_por_movimiento(local_date())
            flash(f"Cliente {cliente_existente.nombre} reactivado correctamente.", "success")
            return redirect(url_for("app_rutas.index", resaltado=cliente_existente.id))

        # 🔹 Código duplicado y activo
        if cliente_existente and not cliente_existente.cancelado:
            flash("Ese código ya pertenece a un cliente activo.", "warning")
            return redirect(url_for("app_rutas.nuevo_cliente"))

        # 🔹 Crear cliente nuevo
        cliente = Cliente(
            nombre=nombre or "",
            codigo=codigo,
            direccion=direccion or "",
            telefono=telefono or "",
            orden=orden,
            fecha_creacion=local_date(),
            cancelado=False,
        )
        db.session.add(cliente)
        db.session.commit()

        # 💸 Crear préstamo inicial
        if monto and monto > 0:
            saldo_total = monto + (monto * (interes / 100.0))
            nuevo_prestamo = Prestamo(
                cliente_id=cliente.id,
                monto=monto,
                saldo=saldo_total,
                fecha=local_date(),
                interes=interes,
                plazo=plazo,
                frecuencia=frecuencia,
            )
            db.session.add(nuevo_prestamo)

            mov = MovimientoCaja(
                tipo="prestamo",
                monto=monto,
                descripcion=f"Préstamo inicial a {cliente.nombre or 'cliente'}",
                fecha=hora_actual(),  # ✅ hora actual en Chile
            )
            db.session.add(mov)
            cliente.saldo = saldo_total

            db.session.commit()
            actualizar_liquidacion_por_movimiento(local_date())

        flash(f"Cliente {nombre or codigo} creado correctamente.", "success")
        return redirect(url_for("app_rutas.index", resaltado=cliente.id))

    codigo_sugerido = generar_codigo_cliente()
    return render_template("nuevo_cliente.html", codigo_sugerido=codigo_sugerido)

# ======================================================
# ❌ ELIMINAR CLIENTE — CON REINTEGRO ÚNICO
# ======================================================
@app_rutas.route("/eliminar_cliente/<int:cliente_id>", methods=["POST"])
@login_required
def eliminar_cliente(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)

    if cliente.cancelado:
        flash(f"⚠️ El cliente {cliente.nombre} ya estaba cancelado.", "info")
        return redirect(url_for("app_rutas.index"))

    print(f"\n🧾 Eliminando cliente {cliente.nombre}...")

    monto_prestado = sum(p.monto for p in cliente.prestamos)
    saldo_restante = float(monto_prestado or 0.0)

    for p in cliente.prestamos:
        db.session.delete(p)

    movs_previos = MovimientoCaja.query.filter(
        MovimientoCaja.descripcion.ilike(f"%{cliente.nombre}%")
    ).all()
    for m in movs_previos:
        db.session.delete(m)

    cliente.cancelado = True
    cliente.saldo = 0.0

    if saldo_restante > 0:
        mov_reverso = MovimientoCaja(
            tipo="entrada_manual",
            monto=saldo_restante,
            descripcion=f"Reintegro único de cliente {cliente.nombre}",
            fecha=hora_actual(),  # ✅ UTC seguro
        )
        db.session.add(mov_reverso)

    db.session.commit()
    liq = actualizar_liquidacion_por_movimiento(local_date())

    flash(f"✅ Cliente {cliente.nombre} eliminado correctamente.", "success")
    return redirect(url_for("app_rutas.index"))


# ======================================================
# 💵 OTORGAR PRÉSTAMO A CLIENTE
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

    saldo_con_interes = monto + (monto * (interes / 100.0))
    prestamo = Prestamo(
        cliente_id=cliente.id,
        monto=monto,
        interes=interes,
        plazo=plazo,
        fecha=local_date(),
        saldo=saldo_con_interes,
    )
    db.session.add(prestamo)

    mov = MovimientoCaja(
        tipo="salida",
        monto=monto,
        descripcion=f"Préstamo a {cliente.nombre}",
        fecha=hora_actual(),  # ✅ hora real convertida a UTC
    )
    db.session.add(mov)
    db.session.commit()

    actualizar_liquidacion_por_movimiento(local_date())

    flash(f"Préstamo de ${monto:.2f} otorgado a {cliente.nombre}", "success")
    return redirect(url_for("app_rutas.index"))

# ======================================================
# 💰 REGISTRAR ABONO POR CÓDIGO
# ======================================================
@app_rutas.route("/registrar_abono_por_codigo", methods=["POST"])
@login_required
def registrar_abono_por_codigo():
    codigo = request.form.get("codigo", "").strip()
    monto = float(request.form.get("monto") or 0)

    if monto <= 0:
        msg = "Monto inválido"
        flash(msg, "danger")
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"ok": False, "error": msg}), 400
        return redirect(url_for("app_rutas.index"))

    # 🔍 Buscar cliente
    cliente = Cliente.query.filter_by(codigo=codigo).first()
    if not cliente:
        msg = "Código no encontrado"
        flash(msg, "danger")
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"ok": False, "error": msg}), 404
        return redirect(url_for("app_rutas.index"))

    # 🔎 Buscar préstamo activo
    prestamo = (
        Prestamo.query.filter(Prestamo.cliente_id == cliente.id, Prestamo.saldo > 0)
        .order_by(Prestamo.fecha.desc(), Prestamo.id.desc())
        .first()
    )
    if not prestamo:
        msg = "Cliente sin préstamos pendientes"
        flash(msg, "warning")
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"ok": False, "error": msg}), 400
        return redirect(url_for("app_rutas.index"))

    # 💵 Registrar abono
    abono = Abono(
        prestamo_id=prestamo.id,
        monto=monto,
        fecha=hora_actual(),  # ✅ hora local de Chile (corrige el NameError)
    )
    db.session.add(abono)

    # 🔄 Actualizar saldo
    prestamo.saldo = max(0.0, (prestamo.saldo or 0) - monto)

    total_saldo_cliente = (
        db.session.query(func.coalesce(func.sum(Prestamo.saldo), 0.0))
        .filter(Prestamo.cliente_id == cliente.id)
        .scalar()
        or 0.0
    )
    cliente.saldo = total_saldo_cliente

    # 📅 Actualizar fecha del último abono
    if hasattr(cliente, "ultimo_abono_fecha"):
        cliente.ultimo_abono_fecha = local_date()

    # ✅ Cancelar si queda en 0
    cancelado = False
    if round(cliente.saldo, 2) <= 0:
        cliente.cancelado = True
        cliente.saldo = 0.0
        cancelado = True
        flash(f"✅ {cliente.nombre} quedó en saldo 0 y fue movido a Clientes Cancelados.", "info")

    db.session.commit()
    actualizar_liquidacion_por_movimiento(local_date())

    # ⚡ Respuesta AJAX
    if request.headers.get("X-Requested-With") == "fetch":
        payload = {
            "ok": True,
            "cliente_id": cliente.id,
            "saldo": float(cliente.saldo),
            "cancelado": cancelado,
        }
        if hasattr(cliente, "ultimo_abono_fecha"):
            payload["fecha_abono"] = cliente.ultimo_abono_fecha.strftime("%Y-%m-%d")
        return jsonify(payload), 200

    flash(f"💰 Abono de ${monto:.2f} registrado para {cliente.nombre}", "success")
    return redirect(url_for("app_rutas.index"))

# ======================================================
# 📜 HISTORIAL DE ABONOS POR CLIENTE
# ======================================================
@app_rutas.route("/historial_abonos/<int:cliente_id>")
@login_required
def historial_abonos(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    prestamo = cliente.prestamos[-1] if cliente.prestamos else None

    if prestamo:
        monto = float(prestamo.monto or 0.0)
        interes = float(prestamo.interes or 0.0)
        plazo = int(prestamo.plazo or 0)
        total = monto + (monto * interes / 100)
        cuota = (total / plazo) if plazo > 0 else 0.0
        modo = prestamo.frecuencia or "—"
        fecha_inicial = prestamo.fecha.strftime("%d-%m-%Y") if prestamo.fecha else "—"
    else:
        monto = total = cuota = 0.0
        modo = fecha_inicial = "—"

    datos_prestamo = {
        "nombre": cliente.nombre,
        "fecha_inicial": fecha_inicial,
        "monto": monto,
        "total": total,
        "cuota": cuota,
        "modo": modo,
        "datos": cliente.direccion or "—",
        "saldo": float(cliente.saldo or 0.0),
    }

    items = []
    saldo_inicial = float(cliente.saldo or total)

    if prestamo and prestamo.abonos:
        abonos_ordenados = sorted(prestamo.abonos, key=lambda x: x.fecha)
        saldo_restante = saldo_inicial
        for a in reversed(abonos_ordenados):
            saldo_restante += float(a.monto or 0.0)

        saldo_actual = saldo_restante
        for a in abonos_ordenados:
            saldo_actual -= float(a.monto or 0.0)
            if saldo_actual < 0:
                saldo_actual = 0.0
            items.append({
                "id": a.id,
                "codigo": cliente.codigo,
                "fecha": a.fecha.astimezone().strftime("%d-%m-%Y"),  # ✅ hora local Chile
                "hora": a.fecha.astimezone().strftime("%I:%M:%S %p"),
                "monto": float(a.monto),
                "saldo": round(saldo_actual, 2)
            })
        items.reverse()

    if not items:
        items.append({
            "id": 0,
            "codigo": cliente.codigo,
            "fecha": hora_actual().strftime("%d-%m-%Y"),
            "hora": "auto",
            "monto": 0.00,
            "saldo": round(float(cliente.saldo or total or 0.0), 2)
        })

    return jsonify({"ok": True, "prestamo": datos_prestamo, "abonos": items})


# ======================================================
# 💵 REGISTRAR ABONO DIRECTO POR CLIENTE
# ======================================================
@app_rutas.route("/abonar/<int:cliente_id>", methods=["POST"])
@login_required
def abonar(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    monto_abono = request.form.get("monto", type=float)

    if not monto_abono or monto_abono <= 0:
        flash("El monto del abono debe ser mayor que cero.", "warning")
        return redirect(url_for("app_rutas.index"))

    prestamo = (
        Prestamo.query.filter_by(cliente_id=cliente.id)
        .order_by(Prestamo.id.desc())
        .first()
    )
    if not prestamo:
        flash("⚠️ Este cliente no tiene préstamos activos.", "warning")
        return redirect(url_for("app_rutas.index"))

    nuevo_abono = Abono(
        prestamo_id=prestamo.id,
        monto=monto_abono,
        fecha=hora_actual(),  # ✅ corrige desfase de hora
    )
    db.session.add(nuevo_abono)

    # 🔄 Actualizar saldos
    prestamo.saldo = max(0.0, (prestamo.saldo or 0) - monto_abono)
    cliente.saldo = cliente.saldo_total()
    if hasattr(cliente, "ultimo_abono_fecha"):
        cliente.ultimo_abono_fecha = local_date()

    if round(cliente.saldo, 2) <= 0:
        cliente.saldo = 0.0
        cliente.cancelado = True
        flash(f"✅ El cliente {cliente.nombre} ha sido cancelado.", "info")

    db.session.commit()
    actualizar_liquidacion_por_movimiento(local_date())

    flash(f"💰 Se registró un abono de ${monto_abono:.2f} para {cliente.nombre}.", "success")
    return redirect(url_for("app_rutas.index"))


# ======================================================
# 🗑️ ELIMINAR ABONO
# ======================================================
@app_rutas.route("/eliminar_abono/<int:abono_id>", methods=["POST"])
@login_required
def eliminar_abono(abono_id):
    try:
        abono = Abono.query.get_or_404(abono_id)
        prestamo = abono.prestamo
        cliente = prestamo.cliente

        prestamo.saldo = (prestamo.saldo or 0) + (abono.monto or 0)
        db.session.delete(abono)
        db.session.flush()

        total_saldo_cliente = (
            db.session.query(func.coalesce(func.sum(Prestamo.saldo), 0.0))
            .filter(Prestamo.cliente_id == cliente.id)
            .scalar()
            or 0.0
        )
        cliente.saldo = total_saldo_cliente

        if cliente.cancelado and round(cliente.saldo, 2) > 0:
            cliente.cancelado = False

        actualizar_liquidacion_por_movimiento(local_date())
        db.session.commit()

        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({
                "ok": True,
                "cliente_id": cliente.id,
                "saldo": float(cliente.saldo),
                "cancelado": cliente.cancelado,
            }), 200

        flash(f"🗑️ Abono de ${abono.monto:.2f} eliminado correctamente.", "info")
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
# 📊 LIQUIDACIÓN — DÍA ACTUAL
# ======================================================
@app_rutas.route("/liquidacion")
@login_required
def liquidacion_view():
    hoy = local_date()
    liq = Liquidacion.query.filter_by(fecha=hoy).first()
    if not liq:
        liq = crear_liquidacion_para_fecha(hoy)

    liquidaciones = [liq]
    resumen = obtener_resumen_total()

    total_caja = liq.caja or 0.0
    cartera_total = resumen["cartera_total"]

    return render_template(
        "liquidacion.html",
        hoy=hoy,
        liq=liq,
        liquidaciones=liquidaciones,
        total_caja=total_caja,
        cartera_total=cartera_total,
        resumen=resumen,
    )


# ======================================================
# 🗂️ LIQUIDACIONES — HISTÓRICO Y RANGO DE FECHAS
# ======================================================
@app_rutas.route("/liquidaciones", methods=["GET", "POST"])
@login_required
def liquidaciones():
    fecha_desde = request.args.get("desde")
    fecha_hasta = request.args.get("hasta")

    query = Liquidacion.query

    if fecha_desde and fecha_hasta:
        try:
            desde = datetime.strptime(fecha_desde, "%Y-%m-%d").date()
            hasta = datetime.strptime(fecha_hasta, "%Y-%m-%d").date()
            query = query.filter(Liquidacion.fecha >= desde, Liquidacion.fecha <= hasta)
        except ValueError:
            flash("Formato de fecha inválido. Use YYYY-MM-DD", "danger")
            return redirect(url_for("app_rutas.liquidaciones"))
    else:
        query = query.order_by(Liquidacion.fecha.desc()).limit(10)

    liquidaciones = query.all()
    total_entradas = sum(l.entradas or 0 for l in liquidaciones)
    total_prestamos = sum(l.prestamos_hoy or 0 for l in liquidaciones)
    total_entradas_caja = sum(l.entradas_caja or 0 for l in liquidaciones)
    total_salidas = sum(l.salidas or 0 for l in liquidaciones)
    total_gastos = sum(l.gastos or 0 for l in liquidaciones)
    total_caja = sum(l.caja or 0 for l in liquidaciones)

    resumen = obtener_resumen_total()

    return render_template(
        "liquidaciones.html",
        liquidaciones=liquidaciones,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        total_entradas=total_entradas,
        total_prestamos=total_prestamos,
        total_entradas_caja=total_entradas_caja,
        total_salidas=total_salidas,
        total_gastos=total_gastos,
        total_caja=total_caja,
        resumen=resumen,
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
