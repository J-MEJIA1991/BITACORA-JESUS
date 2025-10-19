# app.py
import os
from functools import wraps
from flask import Flask, session, redirect, url_for, flash
from flask_migrate import Migrate
from extensions import db
from rutas import bp as rutas_bp

# -------------------------------------------------
# ⚙️ CONFIGURACIÓN PRINCIPAL DE LA APLICACIÓN
# -------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET", "clave_secreta_local_cámbiala")

# -------------------------------------------------
# 🗄️ CONFIGURACIÓN DE BASE DE DATOS (Neon PostgreSQL)
# -------------------------------------------------
DB_DEFAULT = (
    "postgresql+psycopg2://neondb_owner:"
    "npg_cvzpsy7uDj5A@ep-holy-cherry-ad45d0mv-pooler.c-2.us-east-1.aws.neon.tech/"
    "neondb?sslmode=require&channel_binding=require"
)
DATABASE_URL = os.getenv("DATABASE_URL", DB_DEFAULT)

# ✅ Ajuste para compatibilidad (Render, Railway, etc.)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# -------------------------------------------------
# 🧩 INICIALIZAR EXTENSIONES
# -------------------------------------------------
db.init_app(app)
migrate = Migrate(app, db)

# -------------------------------------------------
# 🔐 LOGIN Y SESIÓN
# -------------------------------------------------
VALID_USER = "mjesus40"
VALID_PASS = "198409"

def login_required(f):
    """Decorador para proteger las rutas que requieren sesión activa."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "usuario" not in session:
            flash("Debes iniciar sesión primero.", "warning")
            return redirect(url_for("rutas.login"))
        return f(*args, **kwargs)
    return wrapper

# -------------------------------------------------
# 🔗 REGISTRO DE RUTAS
# -------------------------------------------------
app.register_blueprint(rutas_bp)

# -------------------------------------------------
# 🚀 INICIALIZACIÓN DE LA BASE DE DATOS Y EJECUCIÓN
# -------------------------------------------------
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True)

