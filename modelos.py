# ======================================================
# modelos.py — versión FINAL (Créditos System, hora Chile 🇨🇱)
# ======================================================

from extensions import db
from tiempo import hora_actual, local_date  # ✅ Hora y fecha local chilena

# ---------------------------------------------------
# 🧍‍♂️ CLIENTE
# ---------------------------------------------------
class Cliente(db.Model):
    __tablename__ = "cliente"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    direccion = db.Column(db.String(255))
    telefono = db.Column(db.String(50))
    orden = db.Column(db.Integer)
    fecha_creacion = db.Column(db.Date, default=local_date)  # ✅ Fecha local
    cancelado = db.Column(db.Boolean, default=False)
    saldo = db.Column(db.Float, default=0.0)
    ultimo_abono_fecha = db.Column(db.Date)

    prestamos = db.relationship("Prestamo", backref="cliente", lazy=True)

    # ---------------------------------------------------
    # 🔹 FUNCIONES DE CÁLCULO Y ESTADO
    # ---------------------------------------------------
    def saldo_total(self):
        if not self.prestamos:
            return float(self.saldo or 0.0)
        ultimo = max(self.prestamos, key=lambda p: p.fecha)
        return float(ultimo.saldo or 0.0)

    def capital_total(self):
        if not self.prestamos:
            return 0.0
        u = max(self.prestamos, key=lambda p: p.fecha)
        total = u.monto + (u.monto * (u.interes or 0) / 100)
        return float(total)

    def capital_total_sin_interes(self):
        if not self.prestamos:
            return float(self.saldo or 0.0)
        u = max(self.prestamos, key=lambda p: p.fecha)
        return float(u.monto or 0.0)

    def cuota_total(self):
        if not self.prestamos:
            return 0.0

        u = max(self.prestamos, key=lambda p: p.fecha)
        if not u.plazo or u.plazo <= 0:
            return 0.0

        frecuencia = (u.frecuencia or "diario").lower()
        dias_por_periodo = {
            "diario": 1,
            "semanal": 7,
            "quincenal": 15,
            "mensual": 30,
        }.get(frecuencia, 1)

        numero_cuotas = max(1, u.plazo // dias_por_periodo)
        total_con_interes = u.monto + (u.monto * (u.interes or 0) / 100)
        return round(total_con_interes / numero_cuotas, 2)

    def valor_cuota(self):
        return self.cuota_total()

    def cuotas_atrasadas(self):
        if not self.prestamos:
            return 0

        u = max(self.prestamos, key=lambda p: p.fecha)
        if not u.plazo or not u.fecha:
            return 0

        from tiempo import local_date
        dias_pasados = (local_date() - u.fecha).days
        frecuencia = (u.frecuencia or "diario").lower()

        if frecuencia == "diario":
            cuotas = dias_pasados
        elif frecuencia == "semanal":
            cuotas = dias_pasados // 7
        elif frecuencia == "quincenal":
            cuotas = dias_pasados // 15
        elif frecuencia == "mensual":
            cuotas = dias_pasados // 30
        else:
            cuotas = 0

        return min(cuotas, u.plazo)

    def ultimo_abono_monto(self):
        if not self.prestamos:
            return 0.0

        u = max(self.prestamos, key=lambda p: p.fecha)
        if not u.abonos:
            return 0.0

        ultimo_abono = max(u.abonos, key=lambda a: a.fecha)
        return float(ultimo_abono.monto or 0.0)


class Prestamo(db.Model):
    __tablename__ = "prestamo"

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("cliente.id"), nullable=False)
    monto = db.Column(db.Float, nullable=False)
    interes = db.Column(db.Float, default=0.0)
    plazo = db.Column(db.Integer)
    fecha = db.Column(db.Date, default=local_date)  # ✅ Fecha local de Chile
    saldo = db.Column(db.Float, default=0.0)
    frecuencia = db.Column(db.String(20), default="diario")
    ultima_aplicacion_interes = db.Column(db.Date, default=local_date)  # 🕒 Nuevo

    # ✅ Relación corregida: elimina abonos al borrar préstamo
    abonos = db.relationship(
        "Abono",
        backref="prestamo",
        cascade="all, delete-orphan",
        lazy=True
    )

# ---------------------------------------------------
# 💰 ABONO
# ---------------------------------------------------
class Abono(db.Model):
    __tablename__ = "abono"

    id = db.Column(db.Integer, primary_key=True)
    prestamo_id = db.Column(db.Integer, db.ForeignKey("prestamo.id"), nullable=False)
    monto = db.Column(db.Float, nullable=False)
    fecha = db.Column(db.DateTime(timezone=False), default=hora_actual)  # ✅ Hora real de Chile sin tzinfo


# ---------------------------------------------------
# 🏦 MOVIMIENTO DE CAJA
# ---------------------------------------------------
class MovimientoCaja(db.Model):
    __tablename__ = "movimiento_caja"

    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(20), nullable=False)
    monto = db.Column(db.Float, nullable=False)
    descripcion = db.Column(db.String(255))
    fecha = db.Column(db.DateTime(timezone=False), default=hora_actual)  # ✅ Igual que Deicton


# ---------------------------------------------------
# 📊 LIQUIDACIÓN DIARIA
# ---------------------------------------------------
class Liquidacion(db.Model):
    __tablename__ = "liquidacion"

    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, unique=True, nullable=False)
    entradas = db.Column(db.Float, default=0.0)
    entradas_caja = db.Column(db.Float, default=0.0)
    salidas = db.Column(db.Float, default=0.0)
    gastos = db.Column(db.Float, default=0.0)
    caja = db.Column(db.Float, default=0.0)
    caja_manual = db.Column(db.Float, default=0.0)
    prestamos_hoy = db.Column(db.Float, default=0.0)

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
