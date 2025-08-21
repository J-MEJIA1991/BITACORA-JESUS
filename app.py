from flask import Flask, jsonify, render_template, request, redirect, url_for
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from datetime import datetime
import os
import re
import json

# ================== CONFIG ==================
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "TU_NUEVO_SPREADSHEET_ID_AQUI"  # Cambia por el ID de Bitácora Jesús

# ================== CREDENCIALES ==================
def cargar_credenciales():
    # 1) Archivo secreto en Render
    cred_file_path = "/etc/secrets/google-credentials.json"
    if os.path.exists(cred_file_path):
        return Credentials.from_service_account_file(cred_file_path, scopes=SCOPES)

    # 2) Variable de entorno GOOGLE_CREDENTIALS
    google_creds_env = os.getenv("GOOGLE_CREDENTIALS")
    if google_creds_env:
        try:
            creds_dict = json.loads(google_creds_env)
            return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        except json.JSONDecodeError:
            raise Exception("❌ La variable de entorno GOOGLE_CREDENTIALS no contiene un JSON válido")

    # 3) Archivo local credentials.json
    local_file = "credentials.json"
    if os.path.exists(local_file):
        return Credentials.from_service_account_file(local_file, scopes=SCOPES)

    # 4) Si nada funciona
    raise Exception("❌ No se encontró el archivo de credenciales ni la variable de entorno GOOGLE_CREDENTIALS")

creds = cargar_credenciales()

# Crea la app de Flask
app = Flask(__name__)

# Crea el cliente de Google Sheets
service = build("sheets", "v4", credentials=creds)

# ================== HELPERS ==================
def obtener_ultima_hoja():
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

    requests = [{"addSheet": {"properties": {"title": hoy}}}]
    service.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body={"requests": requests}).execute()

    encabezados = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{ultima_hoja}!A1:G1"
    ).execute().get("values", [])

    if encabezados:
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID, range=f"{hoy}!A1",
            valueInputOption="USER_ENTERED", body={"values": encabezados}
        ).execute()

    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{ultima_hoja}!A2:B"
    ).execute()
    values = result.get("values", [])

    nueva_data, formulas_f, formulas_g = [], [], []
    fila_excel = 2

    for fila in values:
        if len(fila) >= 2:
            nueva_data.append([hoy, fila[1], "", "", ""])
            formulas_f.append([f"='{ultima_hoja}'!F{fila_excel} + C{fila_excel}*(1+D{fila_excel}/100) - E{fila_excel}"])
            formulas_g.append([f"='{ultima_hoja}'!G{fila_excel} + C{fila_excel}" if mes_actual == ultima_hoja[:7] else f"C{fila_excel}"])
            fila_excel += 1

    if nueva_data:
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID, range=f"{hoy}!A2",
            valueInputOption="USER_ENTERED", body={"values": nueva_data}
        ).execute()

    if formulas_f:
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID, range=f"{hoy}!F2",
            valueInputOption="USER_ENTERED", body={"values": formulas_f}
        ).execute()

    if formulas_g:
        service.spreadsheets().values().update(
            spreadsheetId=SPREADSHEET_ID, range=f"{hoy}!G2",
            valueInputOption="USER_ENTERED", body={"values": formulas_g}
        ).execute()

    return redirect(url_for("index"))

# ================== MAIN ==================
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

