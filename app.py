# app.py - Versión unificada y completa (manejo consistente de caja y liquidaciones)
import os
import random
from datetime import date, datetime, timedelta, time
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate  # <-- Aquí agregamos el import
from functools import wraps

# ---------------------------
# Configuración
# ---------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET", "clave_secreta_local_cámbiala")

# URL de la base de datos
DB_DEFAULT = "postgresql+psycopg2://mjesus40:iNZChYKoUcODzbvtCA0VKkj08luyaj5q@dpg-d3538fb3fgac73b4anpg-a.oregon-postgres.render.com/mjesus40"
uri = os.getenv("DATABASE_URL", DB_DEFAULT)

# Ajuste necesario para Render: cambiar postgres:// a postgresql:// si es necesario
if uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = uri
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Inicializar la base de datos
db = SQLAlchemy(app)

# Configuración de Flask-Migrate
migrate = Migrate(app, db)  # <-- Aquí configuramos Flask-Migrate

# Credenciales (simples)
VALID_USER = "mjesus40"
VALID_PASS = "198409"

# ---------------------------
# MODELOS
# ---------------------------
class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), unique=True, nullable=False)
    orden = db.Column(db.Integer, nullable=False, default=0)
    nombre = db.Column(db.String(200), nullable=False)
    direccion = db.Column(db.String(300), nullable=True)
    monto = db.Column(db.Float, nullable=False, default=0.0)         # capital prestado
    plazo = db.Column(db.Integer, nullable=False, default=30)         # días
    interes = db.Column(db.Float, nullable=False, default=0.0)       # %
    saldo = db.Column(db.Float, nullable=False, default=0.0)          # saldo pendiente
    fecha_creacion = db.Column(db.Date, default=date.today)
    ultimo_abono_fecha = db.Column(db.Date, nullable=True)
    cancelado = db.Column(db.Boolean, default=False)                  # ✅ Nuevo campo

    abonos = db.relationship("Abono", backref="cliente", lazy=True, cascade="all, delete-orphan")
    prestamos = db.relationship("Prestamo", backref="cliente", lazy=True, cascade="all, delete-orphan")


class MovimientoCaja(db.Model):
    __tablename__ = "movimiento_caja"
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(20), nullable=False)  # "entrada", "salida", "gasto"
    monto = db.Column(db.Float, nullable=False)
    descripcion = db.Column(db.String(255), nullable=True)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)


class Prestamo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("cliente.id"), nullable=False)
    monto = db.Column(db.Float, nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    movimiento_id = db.Column(db.Integer, db.ForeignKey("movimiento_caja.id"), nullable=True)
    movimiento = db.relationship("MovimientoCaja", foreign_keys=[movimiento_id], uselist=False)


class Abono(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("cliente.id"), nullable=False)
    monto = db.Column(db.Float, nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    movimiento_id = db.Column(db.Integer, db.ForeignKey("movimiento_caja.id"), nullable=True)
    movimiento = db.relationship("MovimientoCaja", foreign_keys=[movimiento_id], uselist=False)


class Liquidacion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, unique=True, nullable=False)
    total_abonos = db.Column(db.Float, default=0.0)
    total_prestamos = db.Column(db.Float, default=0.0)
    caja = db.Column(db.Float, default=0.0)
    paquete = db.Column(db.Float, default=0.0)

# ---------------------------
# HELPERS / UTILIDADES
# ---------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "usuario" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def generar_codigo_numerico():
    code = ''.join(random.choices("0123456789", k=6))
    while Cliente.query.filter_by(codigo=code).first():
        code = ''.join(random.choices("0123456789", k=6))
    return code

def paquete_total_actual():
    s = db.session.query(db.func.coalesce(db.func.sum(Cliente.saldo), 0)).scalar()
    return float(s or 0.0)

def day_range(fecha: date):
    start = datetime.combine(fecha, time.min)
    end = start + timedelta(days=1)
    return start, end

def movimientos_caja_totales_para_dia(fecha: date):
    start, end = day_range(fecha)
    entrada = db.session.query(db.func.coalesce(db.func.sum(MovimientoCaja.monto), 0)).filter(
        MovimientoCaja.fecha >= start, MovimientoCaja.fecha < end, MovimientoCaja.tipo == "entrada").scalar() or 0.0
    salida = db.session.query(db.func.coalesce(db.func.sum(MovimientoCaja.monto), 0)).filter(
        MovimientoCaja.fecha >= start, MovimientoCaja.fecha < end, MovimientoCaja.tipo == "salida").scalar() or 0.0
    gasto = db.session.query(db.func.coalesce(db.func.sum(MovimientoCaja.monto), 0)).filter(
        MovimientoCaja.fecha >= start, MovimientoCaja.fecha < end, MovimientoCaja.tipo == "gasto").scalar() or 0.0
    return float(entrada), float(salida), float(gasto)

def crear_liquidacion_para_fecha(fecha):
    """Crea o devuelve la liquidación de una fecha específica."""
    # Verificar si ya existe la liquidación
    liq = Liquidacion.query.filter_by(fecha=fecha).first()
    if liq:
        return liq  # ✅ Si ya existe, la devolvemos

    # Si no existe, la creamos
    liq = Liquidacion(
        fecha=fecha,
        total_abonos=0.0,
        total_prestamos=0.0,
        caja=0.0,
        paquete=0.0
    )
    db.session.add(liq)
    db.session.commit()
    return liq

from datetime import date, timedelta
from sqlalchemy import func

def actualizar_liquidacion_por_movimiento(fecha: date):
    """Recalcula los totales de la liquidación para la fecha dada."""
    # Normalizar fecha (por si viene con hora)
    fecha = fecha if isinstance(fecha, date) else fecha.date()

    # Asegurar que exista la liquidación del día
    liq = Liquidacion.query.filter_by(fecha=fecha).first()
    if not liq:
        liq = crear_liquidacion_para_fecha(fecha)

    # Rango de día (00:00 a 23:59)
    start, end = day_range(fecha)

    # Totales de movimientos
    tot_abonos = float(
        db.session.query(func.coalesce(func.sum(Abono.monto), 0))
        .filter(Abono.fecha >= start, Abono.fecha < end).scalar() or 0.0
    )
    tot_prestamos = float(
        db.session.query(func.coalesce(func.sum(Prestamo.monto), 0))
        .filter(Prestamo.fecha >= start, Prestamo.fecha < end).scalar() or 0.0
    )
    paquete_actual = paquete_total_actual()

    # Caja: se acumula desde el día anterior
    anterior = Liquidacion.query.filter(Liquidacion.fecha < fecha)\
        .order_by(Liquidacion.fecha.desc()).first()
    caja_anterior = float(anterior.caja) if anterior else 0.0

    mov_entrada, mov_salida, mov_gasto = movimientos_caja_totales_para_dia(fecha)
    caja = caja_anterior + mov_entrada - mov_salida - mov_gasto

    # Actualizar liquidación
    liq.total_abonos = tot_abonos
    liq.total_prestamos = tot_prestamos
    liq.caja = caja
    liq.paquete = paquete_actual

    db.session.commit()
    return liq


def asegurar_liquidaciones_contiguas():
    """Crea liquidaciones para los días faltantes hasta hoy."""
    hoy = date.today()
    ultima = Liquidacion.query.order_by(Liquidacion.fecha.desc()).first()

    if not ultima:
        crear_liquidacion_para_fecha(hoy)
        return

    dia = ultima.fecha + timedelta(days=1)
    while dia <= hoy:
        crear_liquidacion_para_fecha(dia)
        dia += timedelta(days=1)

def cliente_estado_class(cliente: Cliente):
    try:
        venc = cliente.fecha_creacion + timedelta(days=cliente.plazo)
        hoy = date.today()
        if cliente.saldo <= 0:
            return "table-success"  # 👉 este sí, porque ya canceló todo
        if cliente.ultimo_abono_fecha == hoy:
            return ""  # 👈 antes ponía "table-success", ahora dejamos vacío
        if hoy > venc + timedelta(days=30):
            return "table-danger"
        if hoy > venc:
            return "table-warning"
        return ""
    except Exception:
        return ""

# ---------------------------
# RUTAS: AUTH
# ---------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form.get("usuario", "").strip()
        clave = request.form.get("clave", "").strip()
        if usuario == VALID_USER and clave == VALID_PASS:
            session["usuario"] = usuario
            flash("Inicio de sesión correcto", "success")
            return redirect(url_for("index"))
        flash("Usuario o clave incorrectos", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("usuario", None)
    flash("Sesión cerrada", "info")
    return redirect(url_for("login"))

# ---------------------------
# RUTAS PRINCIPALES
# ---------------------------
@app.route("/")
@login_required
def index():
    asegurar_liquidaciones_contiguas()
    liq_hoy = crear_liquidacion_para_fecha(date.today())

    # Limpiar clientes con saldo 0 y que no estén cancelados
    with app.app_context():
        clientes_con_saldo_cero = Cliente.query.filter(Cliente.saldo == 0, Cliente.cancelado == False).all()
        print("Clientes con saldo cero:", clientes_con_saldo_cero)  # Imprimir para ver qué se obtiene
        for cliente in clientes_con_saldo_cero:
            db.session.delete(cliente)  # Elimina el cliente de la base de datos
        db.session.commit()

    # Filtrar los clientes activos (no cancelados y con saldo mayor a 0)
    clientes = Cliente.query.filter(Cliente.cancelado == False, Cliente.saldo > 0).order_by(Cliente.orden).all()
    print("Clientes activos:", clientes)  # Ver qué clientes estamos obteniendo

    return render_template("index.html", clientes=clientes, hoy=date.today(), estado_class=cliente_estado_class, liq_hoy=liq_hoy)

@app.route("/dashboard")
@login_required
def dashboard():
    total_clientes = Cliente.query.count()
    total_abonos = float(db.session.query(db.func.coalesce(db.func.sum(Abono.monto), 0)).scalar() or 0.0)
    total_prestamos = float(db.session.query(db.func.coalesce(db.func.sum(Prestamo.monto), 0)).scalar() or 0.0)
    paquete = paquete_total_actual()
    return render_template("dashboard.html", total_clientes=total_clientes, total_abonos=total_abonos, total_prestamos=total_prestamos, paquete=paquete)

# ---------------------------
# CLIENTES: CREAR / EDITAR / ELIMINAR
# ---------------------------
@app.route("/nuevo_cliente", methods=["GET", "POST"])
@login_required
def nuevo_cliente():
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        direccion = request.form.get("direccion", "").strip()
        try:
            monto = float(request.form.get("monto", 0))
            plazo = int(request.form.get("plazo", 30))
            interes = float(request.form.get("interes", 0))
        except ValueError:
            flash("Monto, plazo o interés inválidos", "warning")
            return redirect(url_for("nuevo_cliente"))

        # 👇 Aquí tomamos el orden desde el formulario
        try:
            orden = int(request.form.get("orden", 0))
        except ValueError:
            orden = 0

        if orden <= 0:
            last = Cliente.query.order_by(Cliente.orden.desc()).first()
            orden = (last.orden + 1) if last else 1

        codigo = generar_codigo_numerico()
        saldo_total = monto + (monto * (interes / 100.0))

        cliente = Cliente(
            codigo=codigo,
            orden=orden,
            nombre=nombre,
            direccion=direccion,
            monto=monto,
            plazo=plazo,
            interes=interes,
            saldo=saldo_total,
            fecha_creacion=date.today()
        )
        db.session.add(cliente)
        db.session.flush()  # obtener id antes de crear relación

        # registrar préstamo y movimiento (salida en caja)
        prestamo = Prestamo(cliente_id=cliente.id, monto=monto, fecha=datetime.utcnow())
        db.session.add(prestamo)
        mov = MovimientoCaja(tipo="salida", monto=monto, descripcion=f"Préstamo a {cliente.nombre}", fecha=datetime.utcnow())
        db.session.add(mov)
        db.session.flush()
        prestamo.movimiento_id = mov.id

        db.session.commit()
        actualizar_liquidacion_por_movimiento(date.today())
        flash("Cliente creado y préstamo registrado", "success")

        # ✅ redirigir con ancla al cliente recién creado
        return redirect(url_for("index") + f"#cliente-{cliente.id}")
    
    # 👇 importante: devolver la vista cuando es GET
    return render_template("nuevo_cliente.html")


@app.route("/editar_cliente/<int:cliente_id>", methods=["GET", "POST"])
@login_required
def editar_cliente(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    if request.method == "POST":
        try:
            cliente.orden = int(request.form.get("orden", cliente.orden))
        except ValueError:
            flash("Orden inválido", "warning")
            return redirect(url_for("editar_cliente", cliente_id=cliente_id))

        cliente.nombre = request.form.get("nombre", cliente.nombre)
        cliente.direccion = request.form.get("direccion", cliente.direccion)
        try:
            cliente.monto = float(request.form.get("monto", cliente.monto))
            cliente.plazo = int(request.form.get("plazo", cliente.plazo))
            cliente.interes = float(request.form.get("interes", cliente.interes))
        except ValueError:
            flash("Monto/plazo/interés inválidos", "warning")
            return redirect(url_for("editar_cliente", cliente_id=cliente_id))

        db.session.commit()
        flash("Cliente actualizado", "success")
        return redirect(url_for("index"))

    return render_template("editar_cliente.html", cliente=cliente)


@app.route("/eliminar_cliente/<int:cliente_id>", methods=["POST"])
@login_required
def eliminar_cliente(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    db.session.delete(cliente)
    db.session.commit()
    actualizar_liquidacion_por_movimiento(date.today())
    flash("Cliente eliminado", "success")
    return redirect(url_for("index"))

from flask import jsonify, request, flash, redirect, url_for
from datetime import datetime, date

def respuesta_ajax(success, mensaje=None, nuevo_saldo=None, cancelado=None):
    """Función reutilizable para manejar las respuestas AJAX."""
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        response = {"success": success}
        if mensaje:
            response["mensaje"] = mensaje
        if nuevo_saldo:
            response["nuevo_saldo"] = nuevo_saldo
        if cancelado is not None:
            response["cancelado"] = cancelado
        return jsonify(response), 400 if not success else 200
    return None

# ---------------------------
# ABONOS
# ---------------------------
@app.route("/abonar/<int:cliente_id>", methods=["POST"])
@login_required
def abonar(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)

    # Evitar abonar a clientes cancelados
    if cliente.cancelado:
        return respuesta_ajax(False, "Cliente cancelado")

    # Obtener monto del formulario
    try:
        monto_abono = float(request.form.get("monto_abono", 0))
    except ValueError:
        return respuesta_ajax(False, "Abono inválido")

    if monto_abono <= 0:
        return respuesta_ajax(False, "El abono debe ser mayor a 0")

    if monto_abono > cliente.saldo:
        return respuesta_ajax(False, "El abono no puede ser mayor al saldo")

    # Aplicar abono
    cliente.saldo -= monto_abono
    cliente.ultimo_abono_fecha = date.today()

    ab = Abono(cliente_id=cliente.id, monto=monto_abono, fecha=datetime.utcnow())
    db.session.add(ab)

    mov = MovimientoCaja(
        tipo="entrada",
        monto=monto_abono,
        descripcion=f"Abono {cliente.nombre}",
        fecha=datetime.utcnow()
    )
    db.session.add(mov)
    db.session.flush()
    ab.movimiento_id = mov.id

    # Cancelar cliente automáticamente si saldo quedó en 0
    if cliente.saldo <= 0:
        cliente.saldo = 0.0
        cliente.cancelado = True

    db.session.commit()
    actualizar_liquidacion_por_movimiento(date.today())

    # Respuesta AJAX
    return respuesta_ajax(True, nuevo_saldo=f"{cliente.saldo:.2f}", cancelado=cliente.cancelado)


@app.route("/eliminar_abono/<int:abono_id>", methods=["POST"])
@login_required
def eliminar_abono(abono_id):
    abono = Abono.query.get_or_404(abono_id)
    cliente = abono.cliente
    fecha_dt = abono.fecha.date() if isinstance(abono.fecha, datetime) else abono.fecha

    # Revertir saldo
    if cliente:
        cliente.saldo += abono.monto
        if cliente.saldo > 0:
            cliente.cancelado = False  # Reactivar cliente si estaba cancelado
        if cliente.ultimo_abono_fecha == fecha_dt:
            otros = Abono.query.filter(
                Abono.cliente_id == cliente.id,
                db.func.date(Abono.fecha) == fecha_dt,
                Abono.id != abono.id
            ).count()
            if otros == 0:
                cliente.ultimo_abono_fecha = None

    # Eliminar movimiento asociado
    if abono.movimiento_id:
        mov = MovimientoCaja.query.get(abono.movimiento_id)
        if mov:
            db.session.delete(mov)

    db.session.delete(abono)
    db.session.commit()
    actualizar_liquidacion_por_movimiento(fecha_dt)
    flash("Abono eliminado, saldo repuesto y caja ajustada", "success")
    return redirect(url_for("liquidacion"))

# ---------------------------
# NUEVA RUTA: DETALLES ABONOS
# ---------------------------

from sqlalchemy import cast, Date

@app.route("/detalle_abonos/<fecha>")
@login_required
def detalle_abonos(fecha):
    fecha_obj = datetime.strptime(fecha, '%Y-%m-%d').date()
    
    # Filtramos solo por la fecha sin tomar en cuenta la hora
    abonos = Abono.query.filter(cast(Abono.fecha, Date) == fecha_obj).all()
    
    return render_template("detalle_abonos.html", abonos=abonos, fecha=fecha_obj)

# ---------------------------
# PRÉSTAMOS
# ---------------------------
@app.route("/eliminar_prestamo/<int:prestamo_id>", methods=["POST"])
@login_required
def eliminar_prestamo(prestamo_id):
    prestamo = Prestamo.query.get_or_404(prestamo_id)
    cliente = prestamo.cliente
    fecha_dt = prestamo.fecha  # fecha + hora completas

    if cliente:
        cliente.saldo -= prestamo.monto
        if cliente.saldo < 0:
            cliente.saldo = 0.0
        # Ajustar cancelación según saldo
        cliente.cancelado = cliente.saldo <= 0

    # eliminar movimiento asociado si existe
    if prestamo.movimiento_id:
        mov = MovimientoCaja.query.get(prestamo.movimiento_id)
        if mov:
            db.session.delete(mov)

    db.session.delete(prestamo)
    db.session.commit()
    actualizar_liquidacion_por_movimiento(fecha_dt)

    flash("Préstamo eliminado correctamente", "success")
    return redirect(url_for("liquidacion"))

@app.route("/detalle_prestamos/<fecha>")
@login_required
def detalle_prestamos(fecha):
    # Lógica de la ruta
    pass

# ---------------------------
# CAJA
# ---------------------------
# Rutas para 'caja_entrada' y 'caja_salida'
@app.route("/caja/entrada", methods=["POST"])
@login_required
def caja_entrada():
    try:
        monto = float(request.form.get("monto", 0))
    except ValueError:
        flash("Monto inválido", "warning")
        return redirect(url_for("liquidacion"))

    if monto <= 0:
        flash("Monto debe ser mayor a 0", "warning")
        return redirect(url_for("liquidacion"))

    descripcion = request.form.get("descripcion", "Entrada manual")
    mov = MovimientoCaja(tipo="entrada", monto=monto, descripcion=descripcion, fecha=datetime.utcnow())
    db.session.add(mov)
    db.session.commit()
    actualizar_liquidacion_por_movimiento(date.today())
    flash("Entrada registrada en caja", "success")
    return redirect(url_for("liquidacion"))

@app.route("/caja/salida", methods=["POST"])
@login_required
def caja_salida():
    try:
        monto = float(request.form.get("monto", 0))
    except ValueError:
        flash("Monto inválido", "warning")
        return redirect(url_for("liquidacion"))

    if monto <= 0:
        flash("Monto debe ser mayor a 0", "warning")
        return redirect(url_for("liquidacion"))

    descripcion = request.form.get("descripcion", "Salida manual")
    mov = MovimientoCaja(tipo="salida", monto=monto, descripcion=descripcion, fecha=datetime.utcnow())
    db.session.add(mov)
    db.session.commit()
    actualizar_liquidacion_por_movimiento(date.today())
    flash("Salida registrada en caja", "success")
    return redirect(url_for("liquidacion"))

@app.route("/caja/gasto", methods=["POST"])
@login_required
def caja_gasto():
    try:
        monto = float(request.form.get("monto", 0))
    except ValueError:
        flash("Monto inválido", "warning")
        return redirect(url_for("liquidacion"))

    if monto <= 0:
        flash("Monto debe ser mayor a 0", "warning")
        return redirect(url_for("liquidacion"))

    descripcion = request.form.get("descripcion", "Gasto manual")
    mov = MovimientoCaja(tipo="gasto", monto=monto, descripcion=descripcion, fecha=datetime.utcnow())
    db.session.add(mov)
    db.session.commit()
    actualizar_liquidacion_por_movimiento(date.today())
    flash("Gasto registrado en caja", "success")
    return redirect(url_for("liquidacion"))


# ---------------------------
# REORDENAR CLIENTES
# ---------------------------
@app.route("/actualizar_orden/<int:cliente_id>", methods=["POST"])
@login_required
def actualizar_orden(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    try:
        nuevo_orden = int(request.form.get("orden", cliente.orden))
    except ValueError:
        flash("Orden inválido", "warning")
        return redirect(url_for("index"))

    if nuevo_orden <= 0:
        flash("El orden debe ser mayor a 0", "warning")
        return redirect(url_for("index"))

    clientes = Cliente.query.order_by(Cliente.orden).all()
    if cliente in clientes:
        clientes.remove(cliente)
    insert_index = min(nuevo_orden - 1, len(clientes))
    clientes.insert(insert_index, cliente)
    for idx, c in enumerate(clientes, start=1):
        c.orden = idx

    db.session.commit()
    flash("Orden actualizado correctamente", "success")
    return redirect(url_for("index"))
# ---------------------------
# LIQUIDACIÓN / RESUMEN
# ---------------------------
@app.route("/liquidacion")
@login_required
def liquidacion():
    asegurar_liquidaciones_contiguas()
    liq_hoy = crear_liquidacion_para_fecha(date.today())

    fecha_inicio = request.args.get("fecha_inicio")
    fecha_fin = request.args.get("fecha_fin")
    resumen_rango = None

    if fecha_inicio and fecha_fin:
        try:
            desde = datetime.strptime(fecha_inicio, "%Y-%m-%d").date()
            hasta = datetime.strptime(fecha_fin, "%Y-%m-%d").date()
        except ValueError:
            flash("Fechas inválidas", "warning")
            return redirect(url_for("liquidacion"))

        liquidaciones = Liquidacion.query.filter(Liquidacion.fecha.between(desde, hasta)).order_by(Liquidacion.fecha.desc()).all()
        total_abonos = sum(l.total_abonos for l in liquidaciones)
        total_prestamos = sum(l.total_prestamos for l in liquidaciones)
        caja_final = liquidaciones[0].caja if liquidaciones else 0.0
        paquete_final = liquidaciones[0].paquete if liquidaciones else 0.0

        resumen_rango = {
            "desde": desde,
            "hasta": hasta,
            "total_abonos": total_abonos,
            "total_prestamos": total_prestamos,
            "caja": caja_final,
            "paquete": paquete_final
        }
        return render_template("liquidacion.html", liquidaciones=liquidaciones, resumen_rango=resumen_rango, hoy=date.today(), liq_hoy=liq_hoy)
    else:
        ultimas = Liquidacion.query.order_by(Liquidacion.fecha.desc()).limit(10).all()
        return render_template("liquidacion.html", liquidaciones=ultimas, resumen_rango=None, hoy=date.today(), liq_hoy=liq_hoy)

# ---------------------------
# ERRORES / INICIALIZACIÓN
# ---------------------------
@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404

# Crear tablas si faltan
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True)

