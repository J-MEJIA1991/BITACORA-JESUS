
import os
import random
from datetime import datetime, date, timedelta, time
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import func

# ---------------------------
# CONFIGURACIÓN APP
# ---------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET", "clave_secreta_local_cámbiala")

# ---------------------------
# BASE DE DATOS
# ---------------------------
DB_DEFAULT = "postgresql+psycopg2://neondb_owner:npg_Jom4Ed6OAMLh@ep-frosty-snow-adg8fr51-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
DATABASE_URL = os.getenv("DATABASE_URL", DB_DEFAULT)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# ---------------------------
# LOGIN
# ---------------------------
VALID_USER = "j-mejia"
VALID_PASS = "honny"

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "usuario" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

# ---------------------------
# MODELOS
# ---------------------------
class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    direccion = db.Column(db.String(255))
    telefono = db.Column(db.String(50))
    orden = db.Column(db.Integer)
    fecha_creacion = db.Column(db.Date, default=date.today)
    cancelado = db.Column(db.Boolean, default=False)
    saldo = db.Column(db.Float, default=0.0)
    prestamos = db.relationship("Prestamo", backref="cliente", lazy=True)

    # ✅ Saldo total basado en el préstamo activo o más reciente
    def saldo_total(self):
        if not self.prestamos:
            return float(self.saldo or 0.0)
        ultimo = max(self.prestamos, key=lambda p: p.fecha)
        return float(ultimo.saldo or 0.0)

    # ✅ Capital total (solo del préstamo actual, no todos los antiguos)
    def capital_total(self):
        if not self.prestamos:
            return 0.0
        ultimo = max(self.prestamos, key=lambda p: p.fecha)
        return float(ultimo.monto or 0.0)


class Prestamo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("cliente.id"), nullable=False)
    monto = db.Column(db.Float, nullable=False)
    saldo = db.Column(db.Float, nullable=False)
    interes = db.Column(db.Float, default=0.0)
    plazo = db.Column(db.Integer)
    fecha = db.Column(db.Date, default=date.today)
    entregado = db.Column(db.Boolean, default=True)

class Abono(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    prestamo_id = db.Column(db.Integer, db.ForeignKey("prestamo.id"), nullable=False)
    monto = db.Column(db.Float, nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.now)
    prestamo = db.relationship("Prestamo", backref=db.backref("abonos", lazy=True))

class MovimientoCaja(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(20), nullable=False)
    monto = db.Column(db.Float, nullable=False)
    descripcion = db.Column(db.String(255))
    fecha = db.Column(db.DateTime, default=datetime.now)

class Liquidacion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, unique=True, nullable=False)

    # 💰 Ingresos = abonos de clientes
    entradas = db.Column(db.Float, default=0.0)

    # 💵 Entradas manuales (efectivo directo)
    entradas_caja = db.Column(db.Float, default=0.0)  # ✅ NUEVO CAMPO

    # 💸 Salidas manuales
    salidas = db.Column(db.Float, default=0.0)

    # 🧾 Gastos registrados
    gastos = db.Column(db.Float, default=0.0)

    # 💼 Caja final del día
    caja = db.Column(db.Float, default=0.0)

    # 📦 Caja anterior (manual o calculada)
    caja_manual = db.Column(db.Float, default=0.0)

    # 🏦 Préstamos entregados en el día
    prestamos_hoy = db.Column(db.Float, default=0.0)

    # --- PROPIEDADES CALCULADAS ---
    @property
    def total_abonos(self):
        return self.entradas or 0.0

    @property
    def total_entradas_caja(self):
        return self.entradas_caja or 0.0

    @property
    def total_prestamos(self):
        return self.prestamos_hoy or 0.0

    @property
    def total_salidas(self):
        return self.salidas or 0.0

    @property
    def total_gastos(self):
        return self.gastos or 0.0

    @property
    def total_caja(self):
        return self.caja or 0.0

# ---------------------------
# FUNCIONES AUXILIARES
# ---------------------------
import random
from app import Cliente

def generar_codigo_cliente():
    """Genera un código numérico único de 6 dígitos para un cliente."""
    while True:
        codigo = ''.join(random.choices("0123456789", k=6))
        existe = Cliente.query.filter_by(codigo=codigo).first()
        if not existe:
            return codigo
def day_range(fecha: date):
    start = datetime.combine(fecha, time.min)
    end = start + timedelta(days=1)
    return start, end

def generar_codigo_cliente():
    code = ''.join(random.choices('0123456789', k=6))
    while Cliente.query.filter_by(codigo=code).first():
        code = ''.join(random.choices('0123456789', k=6))
    return code

def crear_liquidacion_para_fecha(fecha):
    liq = Liquidacion.query.filter_by(fecha=fecha).first()
    if not liq:
        liq = Liquidacion(fecha=fecha)
        db.session.add(liq)
        db.session.commit()
    return liq

def obtener_resumen_total():
    total_entradas = db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0))\
        .filter(MovimientoCaja.tipo == 'entrada').scalar() or 0.0
    total_salidas = db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0))\
        .filter(MovimientoCaja.tipo == 'salida').scalar() or 0.0
    total_gastos = db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0))\
        .filter(MovimientoCaja.tipo == 'gasto').scalar() or 0.0

    caja_total = total_entradas - total_salidas - total_gastos
    cartera_total = float(db.session.query(func.coalesce(func.sum(Prestamo.saldo), 0)).scalar() or 0.0)
    return {'caja_total': caja_total, 'cartera_total': cartera_total}

def actualizar_liquidacion_por_movimiento(fecha: date):
    start, end = day_range(fecha)

    # 💰 Abonos hechos por clientes (verdaderos ingresos)
    entradas_abonos = db.session.query(func.coalesce(func.sum(Abono.monto), 0)) \
        .join(Prestamo, Abono.prestamo_id == Prestamo.id) \
        .filter(Abono.fecha >= start, Abono.fecha < end).scalar() or 0.0

    # 💵 Entradas manuales (efectivo real en caja)
    entradas_manual = db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0)) \
        .filter(
            MovimientoCaja.tipo == 'entrada_manual',
            MovimientoCaja.fecha >= start,
            MovimientoCaja.fecha < end
        ).scalar() or 0.0

    # 💸 Salidas manuales (excluye préstamos)
    salidas_manual = db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0)) \
        .filter(
            MovimientoCaja.tipo == 'salida',
            ~MovimientoCaja.descripcion.ilike('%prestamo%'),
            MovimientoCaja.fecha >= start,
            MovimientoCaja.fecha < end
        ).scalar() or 0.0

    # 🧾 Gastos
    gastos = db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0)) \
        .filter(
            MovimientoCaja.tipo == 'gasto',
            MovimientoCaja.fecha >= start,
            MovimientoCaja.fecha < end
        ).scalar() or 0.0

    # 🏦 Préstamos entregados (tipo 'prestamo')
    prestamos_entregados = db.session.query(func.coalesce(func.sum(MovimientoCaja.monto), 0)) \
        .filter(
            MovimientoCaja.tipo == 'prestamo',
            MovimientoCaja.fecha >= start,
            MovimientoCaja.fecha < end
        ).scalar() or 0.0

    # 🔁 Liquidación anterior
    liq_anterior = Liquidacion.query.filter(Liquidacion.fecha < fecha) \
        .order_by(Liquidacion.fecha.desc()).first()
    caja_anterior = liq_anterior.caja if liq_anterior else 0.0

    # ✅ Entradas totales = abonos + entradas manuales
    total_entradas = entradas_abonos + entradas_manual

    # ✅ Salidas totales (solo salidas reales, sin préstamos)
    total_salidas = salidas_manual

    # 💼 Caja actual: baja también por préstamos
    caja_actual = caja_anterior + total_entradas - (prestamos_entregados + total_salidas + gastos)

    # 🔄 Crear o actualizar liquidación
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

# ---------------------------
# RUTAS
# ---------------------------
@app.route('/')
@login_required
def index():
    # ✅ Mostrar solo clientes activos (no cancelados)
    clientes = Cliente.query.filter_by(cancelado=False)\
        .order_by(Cliente.orden.asc().nullsfirst(), Cliente.id.asc())\
        .all()

    # Mantener orden numérico limpio
    for idx, c in enumerate(clientes, start=1):
        if not c.orden or c.orden != idx:
            c.orden = idx
    db.session.commit()

    # Obtener resumen general
    resumen = obtener_resumen_total()
    hoy = date.today()

    return render_template('index.html', clientes=clientes, resumen=resumen, hoy=hoy)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form.get('usuario','').strip()
        clave = request.form.get('clave','').strip()
        if usuario == VALID_USER and clave == VALID_PASS:
            session['usuario'] = usuario
            flash('Inicio de sesión correcto','success')
            return redirect(url_for('index'))
        flash('Usuario o clave incorrectos','danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('usuario', None)
    flash('Sesión cerrada','info')
    return redirect(url_for('login'))

@app.route('/clientes_cancelados')
@login_required
def clientes_cancelados_view():
    # ✅ Mostrar solo los clientes cancelados
    clientes = Cliente.query.filter_by(cancelado=True).order_by(Cliente.nombre.asc()).all()

    # Totales informativos
    total_cancelados = len(clientes)
    total_saldos = sum(c.saldo or 0 for c in clientes)

    return render_template(
        'clientes_cancelados.html',
        clientes=clientes,
        total_cancelados=total_cancelados,
        total_saldos=total_saldos
    )

@app.route('/reactivar_cliente/<int:cliente_id>', methods=['POST'])
@login_required
def reactivar_cliente(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)

    if not cliente.cancelado:
        flash(f"El cliente {cliente.nombre} ya está activo.", "info")
        return redirect(url_for('clientes_cancelados_view'))

    # ✅ Reactivar cliente
    cliente.cancelado = False
    cliente.saldo = 0.0  # empieza con saldo limpio
    cliente.ultimo_abono_fecha = None

    db.session.commit()
    flash(f"El cliente {cliente.nombre} fue reactivado correctamente.", "success")
    return redirect(url_for('clientes_cancelados_view'))


# ---------------------------
# RUTAS DE PRÉSTAMOS Y ABONOS
# ---------------------------
@app.route('/otorgar_prestamo/<int:cliente_id>', methods=['POST'])
@login_required
def otorgar_prestamo(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    try:
        monto = float(request.form.get('monto', 0))
        interes = float(request.form.get('interes', 0))
        plazo = int(request.form.get('plazo') or 0)
    except ValueError:
        flash('Valores de préstamo inválidos', 'danger')
        return redirect(url_for('index'))

    if monto <= 0:
        flash('El monto debe ser mayor a 0', 'warning')
        return redirect(url_for('index'))

    # ✅ Cálculo correcto del saldo con interés
    saldo_con_interes = monto + (monto * (interes / 100.0))
    prestamo = Prestamo(
        cliente_id=cliente.id,
        monto=monto,
        interes=interes,
        plazo=plazo,
        fecha=date.today(),
        saldo=saldo_con_interes
    )
    db.session.add(prestamo)

    # Registrar salida en caja (préstamo entregado)
    mov = MovimientoCaja(
        tipo='salida',
        monto=monto,
        descripcion=f'Préstamo a {cliente.nombre}',
        fecha=datetime.now()
    )
    db.session.add(mov)
    db.session.commit()

    # ✅ Actualizamos la liquidación del día
    actualizar_liquidacion_por_movimiento(date.today())

    flash(f'Préstamo de {monto:.2f} otorgado a {cliente.nombre}', 'success')
    return redirect(url_for('index'))

@app.route('/registrar_abono_por_codigo', methods=['POST'])
@login_required
def registrar_abono_por_codigo():
    codigo = request.form.get('codigo', '').strip()
    monto = float(request.form.get('monto') or 0)
    if monto <= 0:
        flash('Monto inválido', 'danger')
        return redirect(url_for('liquidacion'))

    # 🔎 Buscar cliente por código
    cliente = Cliente.query.filter_by(codigo=codigo).first()
    if not cliente:
        flash('Código no encontrado', 'danger')
        return redirect(url_for('liquidacion'))

    # 🔍 Buscar préstamo activo (más reciente con saldo > 0)
    prestamo = (
        Prestamo.query
        .filter(Prestamo.cliente_id == cliente.id, Prestamo.saldo > 0)
        .order_by(Prestamo.fecha.desc(), Prestamo.id.desc())
        .first()
    )
    if not prestamo:
        flash('Cliente sin préstamos pendientes', 'warning')
        return redirect(url_for('liquidacion'))

    # 💰 Registrar el abono (solo en tabla Abono)
    abono = Abono(prestamo_id=prestamo.id, monto=monto, fecha=datetime.now())
    db.session.add(abono)

    # 🔄 Actualizar saldo del préstamo
    prestamo.saldo = max(0.0, (prestamo.saldo or 0) - monto)
    db.session.commit()

    # 📉 Recalcular saldo total del cliente
    saldo_total = cliente.saldo_total()

    # ✅ Si quedó en cero, marcar como cancelado
    if round(saldo_total, 2) <= 0:
        cliente.cancelado = True
        cliente.saldo = 0.0
        db.session.commit()
        flash(f"✅ {cliente.nombre} quedó en saldo 0 y fue movido a Clientes Cancelados.", "info")

    # 🔄 Actualizar la liquidación del día (sin registrar movimiento de caja)
    actualizar_liquidacion_por_movimiento(date.today())

    flash(f'💰 Abono de ${monto:.2f} registrado para {cliente.nombre}', 'success')
    return redirect(url_for('liquidacion'))

@app.route('/historial_abonos/<int:cliente_id>')
@login_required
def historial_abonos(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    items = []
    for p in cliente.prestamos:
        for a in p.abonos:
            items.append({
                'id': a.id,
                'fecha_dt': a.fecha,
                'fecha': a.fecha.strftime("%d/%m/%Y"),
                'hora': a.fecha.strftime("%H:%M"),
                'nombre': cliente.nombre,
                'monto': float(a.monto)
            })
    items.sort(key=lambda x: x['fecha_dt'], reverse=True)
    for it in items:
        it.pop('fecha_dt', None)
    return jsonify({'abonos': items})

@app.route('/abonar/<int:cliente_id>', methods=['POST'])
@login_required
def abonar(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    monto_abono = request.form.get('monto', type=float)

    if not monto_abono or monto_abono <= 0:
        flash("El monto del abono debe ser mayor que cero.", "warning")
        return redirect(url_for('index'))

    # Buscar el préstamo activo más reciente
    prestamo = Prestamo.query.filter_by(cliente_id=cliente.id).order_by(Prestamo.id.desc()).first()
    if not prestamo:
        flash("⚠️ Este cliente no tiene préstamos activos.", "warning")
        return redirect(url_for('index'))

    # ✅ Registrar el abono (solo en la tabla Abono)
    nuevo_abono = Abono(
        prestamo_id=prestamo.id,
        monto=monto_abono,
        fecha=datetime.now()
    )
    db.session.add(nuevo_abono)

    # Actualizar saldo del préstamo y cliente
    prestamo.saldo = max(0.0, (prestamo.saldo or 0) - monto_abono)
    cliente.saldo = cliente.saldo_total()
    cliente.ultimo_abono_fecha = datetime.now()

    # Si queda en 0, cancelarlo automáticamente
    if round(cliente.saldo, 2) <= 0:
        cliente.saldo = 0.0
        cliente.cancelado = True
        flash(f"✅ El cliente {cliente.nombre} ha sido cancelado.", "info")

    db.session.commit()

    # ✅ Actualizar la liquidación del día
    actualizar_liquidacion_por_movimiento(date.today())

    flash(f"💰 Se registró un abono de ${monto_abono:.2f} para {cliente.nombre}.", "success")
    return redirect(url_for('index'))


@app.route('/eliminar_abono/<int:abono_id>', methods=['POST'])
@login_required
def eliminar_abono(abono_id):
    abono = Abono.query.get_or_404(abono_id)

    # Buscar cliente relacionado
    cliente = (
        Cliente.query.join(Prestamo, Cliente.id == Prestamo.cliente_id)
        .filter(Prestamo.id == abono.prestamo_id)
        .first()
    )

    if not cliente:
        flash("No se encontró el cliente asociado a este abono.", "danger")
        return redirect(url_for('index'))

    # Revertir el saldo del cliente
    cliente.saldo += abono.monto

    # ✅ Si el cliente estaba cancelado, reactivarlo automáticamente
    if cliente.cancelado and cliente.saldo > 0:
        cliente.cancelado = False
        flash(f"El cliente {cliente.nombre} fue reactivado automáticamente.", "info")

    # Eliminar el abono
    db.session.delete(abono)
    db.session.commit()

    # Actualizar la liquidación
    actualizar_liquidacion_por_movimiento(date.today())

    flash(f"🗑️ Se eliminó el abono de ${abono.monto:.2f} de {cliente.nombre}.", "warning")
    return redirect(url_for('index'))

# ---------------------------
# RUTAS DE CAJA
# ---------------------------

@app.route('/caja/<tipo>', methods=['POST'])
@login_required
def caja_movimiento(tipo):
    # ✅ Solo permitimos tipos válidos
    tipos_validos = ['entrada_manual', 'salida', 'gasto']
    if tipo not in tipos_validos:
        flash('Tipo inválido', 'danger')
        return redirect(url_for('liquidacion'))

    try:
        monto = float(request.form.get('monto', 0))
    except ValueError:
        monto = 0

    if monto <= 0:
        flash('Monto inválido', 'warning')
        return redirect(url_for('liquidacion'))

    descripcion = request.form.get('descripcion', f'{tipo.replace("_", " ").capitalize()} manual')

    # 🚫 Evitar registrar préstamos como salidas
    if tipo == 'salida' and ('préstamo' in descripcion.lower() or 'prestamo' in descripcion.lower()):
        flash('⚠️ Los préstamos no deben registrarse como salidas de caja. Usa el módulo de préstamos.', 'warning')
        return redirect(url_for('liquidacion'))

    # ✅ Registrar movimiento válido
    mov = MovimientoCaja(
        tipo=tipo,
        monto=monto,
        descripcion=descripcion,
        fecha=datetime.now()
    )
    db.session.add(mov)
    db.session.commit()

    # 🔄 Actualizar liquidación del día
    actualizar_liquidacion_por_movimiento(date.today())

    flash(f'{tipo.replace("_", " ").capitalize()} registrada correctamente en la caja.', 'success')
    return redirect(url_for('liquidacion'))


@app.route('/caja_entrada', methods=['POST'])
@login_required
def caja_entrada():
    """Entrada manual de efectivo a la caja."""
    return caja_movimiento('entrada_manual')


@app.route('/caja_salida', methods=['POST'])
@login_required
def caja_salida():
    """Salida manual de efectivo desde la caja."""
    return caja_movimiento('salida')


@app.route('/caja_gasto', methods=['POST'])
@login_required
def caja_gasto():
    """Registrar gasto (salida no recuperable)."""
    monto = request.form.get("monto", type=float)
    descripcion = request.form.get("descripcion", "")

    if monto and monto > 0:
        mov = MovimientoCaja(
            tipo="gasto",
            monto=monto,
            descripcion=descripcion or "Gasto general",
            fecha=datetime.now()
        )
        db.session.add(mov)
        db.session.commit()
        actualizar_liquidacion_por_movimiento(date.today())
        flash(f"🧾 Gasto de ${monto:.2f} registrado correctamente.", "warning")
    else:
        flash("Debe ingresar un monto válido.", "danger")

    return redirect(url_for("liquidacion"))

# ---------------------------
# VERIFICACIÓN DE CAJA (evitar abonos mal clasificados)
# ---------------------------
@app.route('/verificar_caja')
@login_required
def verificar_caja():
    abonos_incorrectos = MovimientoCaja.query.filter(
        MovimientoCaja.tipo == 'entrada_manual',
        MovimientoCaja.descripcion.ilike('%abono%')
    ).count()

    if abonos_incorrectos == 0:
        mensaje = "✅ Caja limpia: no hay abonos mal clasificados en las entradas manuales."
        color = "success"
    else:
        mensaje = f"🚨 Atención: hay {abonos_incorrectos} abonos mal clasificados en 'entrada_manual'."
        color = "danger"

    flash(mensaje, color)
    return redirect(url_for('liquidacion'))

# ---------------------------
# RUTAS DE VERIFICACIÓN Y REPARACIÓN DE CAJA
# ---------------------------

@app.route('/revisar_caja_estado')
@login_required
def revisar_caja_estado():
    """Devuelve si hay abonos mal clasificados (para mostrar o no el botón)."""
    errores = MovimientoCaja.query.filter(
        MovimientoCaja.tipo == 'entrada_manual',
        MovimientoCaja.descripcion.ilike('%abono%')
    ).count()
    return jsonify({'errores': errores})


@app.route('/reparar_caja')
@login_required
def reparar_caja():
    """Corrige los registros de abonos mal clasificados y actualiza la liquidación."""
    from datetime import date

    abonos_erroneos = MovimientoCaja.query.filter(
        MovimientoCaja.tipo == 'entrada_manual',
        MovimientoCaja.descripcion.ilike('%abono%')
    ).all()

    if not abonos_erroneos:
        flash("✅ No se encontraron abonos mal clasificados. La caja ya está limpia.", "success")
        return redirect(url_for('liquidacion'))

    for m in abonos_erroneos:
        db.session.delete(m)
    db.session.commit()

    liq = actualizar_liquidacion_por_movimiento(date.today())

    flash(f"🧹 Se eliminaron {len(abonos_erroneos)} abonos mal clasificados y se recalculó la liquidación del {liq.fecha}.", "info")
    return redirect(url_for('liquidacion'))

# ---------------------------
# LIQUIDACIÓN
# ---------------------------

@app.route('/liquidacion')
@login_required
def liquidacion():
    hoy = date.today()
    liq = Liquidacion.query.filter_by(fecha=hoy).first()

    if not liq:
        liq = crear_liquidacion_para_fecha(hoy)

    # 🔹 Mostrar solo la liquidación del día actual
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
        resumen=resumen
    )

# ---------------------------
# HISTORIAL DE LIQUIDACIONES Y ABONOS POR DÍA
# ---------------------------
@app.route('/liquidaciones', methods=['GET', 'POST'])
@login_required
def liquidaciones():
    fecha_desde = request.args.get('desde')
    fecha_hasta = request.args.get('hasta')

    query = Liquidacion.query

    # Si el usuario busca por rango de fechas
    if fecha_desde and fecha_hasta:
        try:
            desde = datetime.strptime(fecha_desde, "%Y-%m-%d").date()
            hasta = datetime.strptime(fecha_hasta, "%Y-%m-%d").date()
            query = query.filter(Liquidacion.fecha >= desde, Liquidacion.fecha <= hasta)
        except ValueError:
            flash("Formato de fecha inválido. Use YYYY-MM-DD", "danger")
            return redirect(url_for('liquidaciones'))
    else:
        # ✅ Cambiamos el orden: primero ordenamos, luego limitamos
        query = query.order_by(Liquidacion.fecha.desc()).limit(10)

    # Si ya hay limit, no volvemos a hacer order_by
    if not fecha_desde or not fecha_hasta:
        liquidaciones = query.all()
    else:
        liquidaciones = query.order_by(Liquidacion.fecha.asc()).all()

    # ✅ Calcular totales del rango
    total_entradas = sum(l.entradas or 0 for l in liquidaciones)
    total_prestamos = sum(l.prestamos_hoy or 0 for l in liquidaciones)
    total_entradas_caja = sum(l.entradas_caja or 0 for l in liquidaciones)  # 💵 NUEVO
    total_salidas = sum(l.salidas or 0 for l in liquidaciones)
    total_gastos = sum(l.gastos or 0 for l in liquidaciones)
    total_caja = sum(l.caja or 0 for l in liquidaciones)

    resumen = obtener_resumen_total()

    # ✅ Agregamos total_entradas_caja al render_template()
    return render_template(
        'liquidaciones.html',
        liquidaciones=liquidaciones,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        total_entradas=total_entradas,
        total_prestamos=total_prestamos,
        total_entradas_caja=total_entradas_caja,  # 💵 NUEVO
        total_salidas=total_salidas,
        total_gastos=total_gastos,
        total_caja=total_caja,
        resumen=resumen
    )

# ---------------------------
# DETALLES DE MOVIMIENTOS POR DÍA
# ---------------------------
@app.route('/movimientos_por_dia/<tipo>/<fecha>')
@login_required
def movimientos_por_dia(tipo, fecha):
    fecha_obj = datetime.strptime(fecha, "%Y-%m-%d").date()
    start, end = day_range(fecha_obj)

    # 💵 Entradas manuales
    if tipo == 'entrada_manual':
        movimientos = (
            MovimientoCaja.query
            .filter(
                MovimientoCaja.tipo == 'entrada_manual',
                MovimientoCaja.fecha >= start,
                MovimientoCaja.fecha < end
            )
            .order_by(MovimientoCaja.fecha.desc())
            .all()
        )
        titulo = "💵 Entradas de Efectivo (Manual)"
        total = sum(m.monto for m in movimientos)

    # 💰 Abonos (ingresos de clientes)
    elif tipo == 'abono':
        from app import Abono, Prestamo, Cliente
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

    # 💸 Salidas o 🧾 Gastos
    elif tipo in ['salida', 'gasto']:
        movimientos = (
            MovimientoCaja.query
            .filter(
                MovimientoCaja.tipo == tipo,
                MovimientoCaja.fecha >= start,
                MovimientoCaja.fecha < end
            )
            .order_by(MovimientoCaja.fecha.desc())
            .all()
        )
        titulo = "💸 Salidas de Efectivo" if tipo == 'salida' else "🧾 Gastos"
        total = sum(m.monto for m in movimientos)

    else:
        flash('Tipo de movimiento no válido.', 'danger')
        return redirect(url_for('liquidacion'))

    # ✅ CORRECCIÓN: agregamos 'hoy'
    return render_template(
        'movimientos_por_dia.html',
        movimientos=movimientos,
        tipo=tipo,
        fecha=fecha_obj,
        total=total,
        titulo=titulo,
        hoy=date.today()  # 👈 Esta línea soluciona el error
    )


@app.route('/prestamos_por_dia/<fecha>')
@login_required
def prestamos_por_dia(fecha):
    fecha_obj = datetime.strptime(fecha, "%Y-%m-%d").date()
    start, end = day_range(fecha_obj)

    prestamos = (
        Prestamo.query
        .filter(Prestamo.fecha >= start, Prestamo.fecha < end)
        .join(Cliente, Prestamo.cliente_id == Cliente.id)
        .add_columns(Cliente.nombre, Prestamo.monto, Prestamo.fecha)
        .order_by(Prestamo.fecha.desc())
        .all()
    )

    total_prestamos = sum(p.monto for p in prestamos)

    return render_template('prestamos_por_dia.html', prestamos=prestamos, fecha=fecha_obj, total_prestamos=total_prestamos)


@app.route('/salidas_por_dia/<fecha>')
@login_required
def salidas_por_dia(fecha):
    fecha_obj = datetime.strptime(fecha, "%Y-%m-%d").date()
    start, end = day_range(fecha_obj)

    salidas = (
        MovimientoCaja.query
        .filter(MovimientoCaja.tipo == 'salida',
                MovimientoCaja.fecha >= start,
                MovimientoCaja.fecha < end)
        .order_by(MovimientoCaja.fecha.desc())
        .all()
    )

    total_salidas = sum(s.monto for s in salidas)

    return render_template('salidas_por_dia.html', salidas=salidas, fecha=fecha_obj, total_salidas=total_salidas)


@app.route('/gastos_por_dia/<fecha>')
@login_required
def gastos_por_dia(fecha):
    fecha_obj = datetime.strptime(fecha, "%Y-%m-%d").date()
    start, end = day_range(fecha_obj)

    gastos = (
        MovimientoCaja.query
        .filter(MovimientoCaja.tipo == 'gasto',
                MovimientoCaja.fecha >= start,
                MovimientoCaja.fecha < end)
        .order_by(MovimientoCaja.fecha.desc())
        .all()
    )

    total_gastos = sum(g.monto for g in gastos)

    return render_template('gastos_por_dia.html', gastos=gastos, fecha=fecha_obj, total_gastos=total_gastos)

# ---------------------------
# CRUD CLIENTE
# ---------------------------

@app.route('/nuevo_cliente', methods=['GET', 'POST'])
@login_required
def nuevo_cliente():
    if request.method == 'POST':
        nombre = request.form.get('nombre')
        codigo = request.form.get('codigo')
        direccion = request.form.get('direccion')
        telefono = request.form.get('telefono')
        monto = request.form.get('monto', type=float)
        interes = request.form.get('interes', type=float) or 0.0
        plazo = request.form.get('plazo', type=int)
        orden = request.form.get('orden', type=int)

        if not codigo:
            flash("Debe ingresar un código de cliente.", "warning")
            return redirect(url_for('nuevo_cliente'))

        # ¿Existe ya ese código?
        cliente_existente = Cliente.query.filter_by(codigo=codigo).first()

        # 👉 Caso 1: existía y estaba cancelado → reactivar y (opcional) dar nuevo préstamo
        if cliente_existente and cliente_existente.cancelado:
            # Reactivar y actualizar datos
            cliente_existente.cancelado = False
            if nombre:     cliente_existente.nombre = nombre
            if direccion:  cliente_existente.direccion = direccion
            if telefono:   cliente_existente.telefono = telefono
            if orden:      cliente_existente.orden = orden
            cliente_existente.fecha_creacion = date.today()

            # Si hay monto, crear préstamo con interés y registrar movimiento como "prestamo"
            if monto and monto > 0:
                saldo_total = monto + (monto * (interes / 100.0))
                nuevo_prestamo = Prestamo(
                    cliente_id=cliente_existente.id,
                    monto=monto,
                    saldo=saldo_total,
                    fecha=date.today()
                )
                db.session.add(nuevo_prestamo)

                # 🔹 Importante: registrar como PRÉSTAMO (no como salida)
                mov = MovimientoCaja(
                    tipo='prestamo',
                    monto=monto,
                    descripcion=f'Nuevo préstamo (reactivado) a {cliente_existente.nombre}',
                    fecha=datetime.now()
                )
                db.session.add(mov)

                # Actualizar saldo del cliente SOLO con este préstamo actual
                cliente_existente.saldo = saldo_total

            db.session.commit()
            actualizar_liquidacion_por_movimiento(date.today())
            flash(f"Cliente {cliente_existente.nombre} reactivado correctamente.", "success")
            return redirect(url_for('nuevo_cliente'))

        # 👉 Caso 2: el código ya existe y NO está cancelado → no crear otro cliente
        if cliente_existente and not cliente_existente.cancelado:
            flash("Ese código ya pertenece a un cliente activo. Use ese cliente o elija otro código.", "warning")
            return redirect(url_for('nuevo_cliente'))

        # 👉 Caso 3: no existe → crear cliente nuevo
        cliente = Cliente(
            nombre=nombre or '',
            codigo=codigo,
            direccion=direccion or '',
            telefono=telefono or '',
            orden=orden,
            fecha_creacion=date.today(),
            cancelado=False
        )
        db.session.add(cliente)
        db.session.commit()

        # Si hay monto, crear préstamo inicial + movimiento de caja tipo "prestamo"
        if monto and monto > 0:
            saldo_total = monto + (monto * (interes / 100.0))

            nuevo_prestamo = Prestamo(
                cliente_id=cliente.id,
                monto=monto,
                saldo=saldo_total,
                fecha=date.today()
            )
            db.session.add(nuevo_prestamo)

            # 🔹 Importante: registrar como PRÉSTAMO (no como salida)
            mov = MovimientoCaja(
                tipo='prestamo',
                monto=monto,
                descripcion=f'Préstamo inicial a {cliente.nombre or "cliente"}',
                fecha=datetime.now()
            )
            db.session.add(mov)

            # El saldo del cliente queda igual al préstamo actual (con interés)
            cliente.saldo = saldo_total

            db.session.commit()
            actualizar_liquidacion_por_movimiento(date.today())

        flash(f"Cliente {nombre or codigo} creado correctamente.", "success")
        return redirect(url_for('nuevo_cliente'))

    # Sugerir un código para el formulario
    codigo_sugerido = generar_codigo_cliente()
    return render_template("nuevo_cliente.html", codigo_sugerido=codigo_sugerido)


@app.route('/actualizar_orden/<int:cliente_id>', methods=['POST'])
@login_required
def actualizar_orden(cliente_id):
    nueva_orden = request.form.get('orden', type=int)
    if nueva_orden is None:
        flash("Debe ingresar un número de orden válido.", "warning")
        return redirect(url_for('index'))

    cliente = Cliente.query.get_or_404(cliente_id)
    cliente.orden = nueva_orden
    db.session.commit()

    flash(f"Orden del cliente {cliente.nombre} actualizada a {nueva_orden}.", "success")
    return redirect(url_for('index'))

@app.route('/eliminar_cliente/<int:cliente_id>', methods=['POST'])
@login_required
def eliminar_cliente(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    for p in cliente.prestamos:
        Abono.query.filter_by(prestamo_id=p.id).delete()
        db.session.delete(p)
    db.session.delete(cliente)
    db.session.commit()
    flash(f"Cliente {cliente.nombre} eliminado correctamente.", "success")
    return redirect(url_for('index'))

@app.route('/api/cliente/<codigo>')
@login_required
def api_cliente_por_codigo(codigo):
    cliente = Cliente.query.filter_by(codigo=codigo).first()
    if cliente:
        return jsonify({
            'existe': True,
            'nombre': cliente.nombre,
            'direccion': cliente.direccion or '',
            'telefono': cliente.telefono or '',
            'cancelado': cliente.cancelado
        })
    return jsonify({'existe': False})


# ---------------------------
# ERRORES E INICIALIZACIÓN
# ---------------------------
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True)
