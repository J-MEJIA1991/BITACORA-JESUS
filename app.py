from flask import Flask, jsonify, render_template, request, redirect, url_for
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from datetime import datetime
import os
import json
import re

# ================== CONFIG ==================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
<<<<<<< HEAD
SPREADSHEET_ID = "1OzbbXYOoJbco7pM21ook6BSFs-gztSFocZBTip-D3KA"

# Leer credenciales desde variable de entorno o archivo local
creds_json = os.getenv("GOOGLE_CREDENTIALS")

if creds_json:
    # Render → lee desde variable de entorno
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
else:
    # Local → usa el archivo credentials.json
    if not os.path.exists("credentials.json"):
        raise Exception("❌ No se encontró GOOGLE_CREDENTIALS ni el archivo credentials.json")
    creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
=======
SPREADSHEET_ID = "1SDgZRJJZtpFIbinH8A85BIPM1y7sr4LbYbSkwcQ7QRE"  # <-- ID de la hoja de tu hermano

# Leer credenciales desde variable de entorno
creds_dict = json.loads(os.getenv("GOOGLE_CREDENTIALS"))
creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
>>>>>>> 1c874ed (Primer commit proyecto Bitácora Sofía)

# Crea la app de Flask
app = Flask(__name__)

# Crea el cliente de Google Sheets
service = build("sheets", "v4", credentials=creds)

# ================== HELPERS ==================
def obtener_ultima_hoja():
    """ Devuelve el título de la última hoja con formato YYYY-MM-DD. """
    spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    sheets = spreadsheet.get("sheets", [])
    fechas = []
    for s in sheets:
        title = s["properties"]["title"]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", title):
            fechas.append(title)
    if not fechas:
        return None
    fechas.sort(reverse=True)
    return fechas[0]

# ================== ROUTES ==================
@app.route("/")
def index():
    today = datetime.today().strftime("%Y-%m-%d")
    return render_template("index.html", today=today)

@app.route("/create_today", methods=["POST"])
def create_today():
    hoy = datetime.today().strftime("%Y-%m-%d")
    ultima_hoja = obtener_ultima_hoja()
    mes_actual = datetime.today().strftime("%Y-%m")

    if not ultima_hoja:
        return jsonify({"error": "No existe ninguna hoja anterior con datos."}), 400

    # 1) Crear nueva hoja
    requests = [{"addSheet": {"properties": {"title": hoy}}}]
    service.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID, body={"requests": requests}
    ).execute()

    # 2) Copiar encabezados (A-G)
    encabezados = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{ultima_hoja}!A1:G1"
    ).execute().get("values", [])

    if encabezados:
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{hoy}!A1",
            valueInputOption="USER_ENTERED",
            body={"values": encabezados}
        ).execute()

    # 3) Copiar base (A y B) dejando C, D, E vacías
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{ultima_hoja}!A2:B"
    ).execute()
    values = result.get("values", [])

    nueva_data = []   # A..E
    formulas_f = []  # F
    formulas_g = []  # G
    fila_excel = 2   # empezamos en la fila 2

    for fila in values:
        if len(fila) >= 2:
            nueva_data.append([
                hoy,      # A: fecha nueva
                fila[1],  # B: cliente
                "",       # C: préstamo
                "",       # D: interés
                ""        # E: abono
            ])
            formulas_f.append([f"='{ultima_hoja}'!F{fila_excel} + C{fila_excel}*(1+D{fila_excel}/100) - E{fila_excel}"])
            if mes_actual == ultima_hoja[:7]:
                formulas_g.append([f"='{ultima_hoja}'!G{fila_excel} + C{fila_excel}"])
            else:
                formulas_g.append([f"C{fila_excel}"])
            fila_excel += 1

    if nueva_data:
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{hoy}!A2",
            valueInputOption="USER_ENTERED",
            body={"values": nueva_data}
        ).execute()

    if formulas_f:
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{hoy}!F2",
            valueInputOption="USER_ENTERED",
            body={"values": formulas_f}
        ).execute()

    if formulas_g:
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID,
            range=f"{hoy}!G2",
            valueInputOption="USER_ENTERED",
            body={"values": formulas_g}
        ).execute()

    return redirect(url_for("index"))

# ================== MAIN ==================
if __name__ == "__main__":
<<<<<<< HEAD
    # Esto solo se usa en local. En Render se usará Gunicorn.
    app.run(debug=True, host="0.0.0.0", port=5000)

=======
    app.run(debug=True, host="0.0.0.0", port=5000)
>>>>>>> 1c874ed (Primer commit proyecto Bitácora Sofía)
