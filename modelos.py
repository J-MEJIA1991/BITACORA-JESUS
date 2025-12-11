# ======================================================
# modelos.py — versión FINAL (Créditos System, hora Chile 🇨🇱)
# ======================================================

from datetime import date
from extensions import db
from tiempo import hora_actual, local_date  # ✅ Hora y fecha local chilena


# ---------------------------------------------------
# 🧍‍♂️ CLIENTE
# ---------------------------------------------------
class Cliente(db.Model):
    __tablename__ = "cliente"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), nullable=False, index=True)
    nombre = db.Column(db.String(200), nullable=False)
    direccion = db.Column(db.String(255))
    telefono = db.Column(db.String(50))
    orden = db.Column(db.Integer)
    fecha_creacion = db.Column(db.Date, default=local_date)  # ✅ Fecha local
    cancelado = db.Column(db.Boolean, default=False)
    saldo = db.Column(db.Float, default=0.0)
    ultimo_abono_fecha = db.Column(db.Date)

    # ⚠️ IMPORTANTE: usar selectin para evitar N+1 queries
    prestamos = db.relationship(
        "Prestamo",
        backref="cliente",
        lazy="selectin",          # 👈 antes estaba lazy=True
        cascade="all, delete-orphan"
    )

    # ---------------------------------------------------
    # 🔹 FUNCIONES DE CÁLCULO Y ESTADO
    # ---------------------------------------------------
    def saldo_total(self):
        if not self.prestamos:
            return float(self.saldo or 0.0)
        u = max(self.prestamos, key=lambda p: p.fecha or date.min)
        return float(u.saldo or 0.0)

    def capital_total(self):
        if not self.prestamos:
            return 0.0
        u = max(self.prestamos, key=lambda p: p.fecha or date.min)
        total = u.monto + (u.monto * (u.interes or 0) / 100)
        return float(total)

    def capital_total_sin_interes(self):
        if not self.prestamos:
            return float(self.saldo or 0.0)
        u = max(self.prestamos, key=lambda p: p.fecha or date.min)
        return float(u.monto or 0.0)

    def cuota_total(self):
        if not self.prestamos:
            return 0.0

        u = max(self.prestamos, key=lambda p: p.fecha or date.min)
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

        u = max(self.prestamos, key=lambda p: p.fecha or date.min)
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
        """
        Devuelve el monto del último abono del último préstamo,
        o 0.0 si no hay préstamos o abonos.
        IMPORTANTE: asume que prestamos y abonos ya vienen cargados
        (gracias a lazy='selectin' en las relaciones y selectinload en la vista).
        """
        if not self.prestamos:
            return 0.0

        # Último préstamo por fecha
        u = max(self.prestamos, key=lambda p: p.fecha or date.min)

        # Si no hay abonos en ese préstamo → 0
        if not u.abonos:
            return 0.0

        # Último abono por fecha
        ultimo_abono = max(u.abonos, key=lambda a: a.fecha or date.min)
        return float(ultimo_abono.monto or 0.0)

    # ---------------------------------------------------
    # 🎨 CLASES CSS PARA LA FILA (COLORES EN EL INDEX)
    # ---------------------------------------------------
    def clases_estado(self, hoy=None):
        """
        Devuelve un string con las clases CSS que debe tener la fila del cliente,
        similar a estado_class(p) en Finanzas Aitana.
        Ejemplo: "plazo-vencido interes-vencido"
        """
        if hoy is None:
            hoy = local_date()

        clases = []

        # 1) Si está cancelado, manda primero
        if self.cancelado:
            clases.append("cancelado")
            # Si quisieras que un cancelado ignore otros estados, podrías:
            # return " ".join(clases)

        # 2) Colores según cuotas atrasadas (tu lógica de negocio)
        atrasadas = 0
        try:
            atrasadas = self.cuotas_atrasadas() or 0
        except Exception:
            atrasadas = 0

        if atrasadas >= 30:
            clases.append("plazo-moroso")   # 🔴 rojo fuerte
        elif atrasadas >= 1:
            clases.append("plazo-vencido")  # 🟠 amarillo

        # 3) Interés mensual vencido en préstamos MENSUALES con 30+ días
        ultimo_prestamo = None
        if self.prestamos:
            ultimo_prestamo = max(self.prestamos, key=lambda p: p.fecha or date.min)

        if ultimo_prestamo and not self.cancelado:
            freq = (ultimo_prestamo.frecuencia or "diario").lower()
            if freq == "mensual" and ultimo_prestamo.fecha:
                f = ultimo_prestamo.fecha
                # por si es datetime
                if hasattr(f, "date"):
                    f = f.date()
                dias_desde = (hoy - f).days
                if dias_desde >= 30:
                    clases.append("interes-vencido")

        return " ".join(clases)


# ---------------------------------------------------
# 💳 PRÉSTAMO
# ---------------------------------------------------
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

    # ✅ Relación: elimina abonos al borrar préstamo
    # ⚠️ También aquí usamos selectin para evitar N+1
    abonos = db.relationship(
        "Abono",
        backref="prestamo",
        cascade="all, delete-orphan",
        lazy="selectin"   # 👈 antes era lazy=True
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
