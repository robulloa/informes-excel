import time
import pandas as pd
import io
from flask import Flask, request, jsonify, render_template, redirect, url_for, send_file
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)
app.secret_key = "super_secret_key"  # Cambiar en producción


# Configuración BD desde variables de entorno
DB_USER = os.getenv("POSTGRES_USER")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")
DB_HOST = os.getenv("POSTGRES_HOST")
DB_PORT = os.getenv("POSTGRES_PORT")
DB_NAME = os.getenv("POSTGRES_DB")

engine = create_engine(
    f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

##engine = create_engine(f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}")

login_manager = LoginManager(app)
login_manager.login_view = "login"

# =========================
# ESPERAR BASE DE DATOS
# =========================
for i in range(10):
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("✅ Base de datos lista")
        break
    except Exception:
        print(f"⏳ Esperando a la base de datos... ({i+1}/10)")
        time.sleep(3)
else:
    print("❌ No se pudo conectar a la base de datos")
    exit(1)

# =========================
# CREAR TABLAS Y USUARIOS
# =========================
def init_db():
    with engine.connect() as conn:
        # Crear tablas si no existen
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS registros (
                id SERIAL PRIMARY KEY,
                nombre VARCHAR(100),
                email VARCHAR(100),
                puntaje INT
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE,
                password VARCHAR(200),
                role VARCHAR(20)
            );
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS eventos (
                id SERIAL PRIMARY KEY,
                usuario VARCHAR(50),
                accion VARCHAR(50),
                fecha TIMESTAMPTZ DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'America/Santiago')
            );
        """))

        # Insertar usuarios por defecto
        admin_exists = conn.execute(text("SELECT 1 FROM usuarios WHERE username='admin'")).fetchone()
        if not admin_exists:
            conn.execute(
                text("INSERT INTO usuarios (username, password, role) VALUES (:u, :p, :r)"),
                {"u": "admin", "p": generate_password_hash("admin123"), "r": "uploader"}
            )
        viewer_exists = conn.execute(text("SELECT 1 FROM usuarios WHERE username='viewer'")).fetchone()
        if not viewer_exists:
            conn.execute(
                text("INSERT INTO usuarios (username, password, role) VALUES (:u, :p, :r)"),
                {"u": "viewer", "p": generate_password_hash("viewer123"), "r": "viewer"}
            )

# Inicializar BD al arranque
init_db()
# Registrar evento
def registrar_evento(usuario, accion):
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO eventos (usuario, accion) VALUES (:usuario, :accion)"),
            {"usuario": usuario, "accion": accion}
        )

# =========================
# CLASE USER PARA FLASK-LOGIN
# =========================
class User(UserMixin):
    def __init__(self, id, username, password, role):
        self.id = id
        self.username = username
        self.password = password
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    try:
        init_db()  # Garantizar tablas
        with engine.connect() as conn:
            user = conn.execute(text("SELECT * FROM usuarios WHERE id=:id"), {"id": user_id}).fetchone()
            if user:
                return User(*user)
    except ProgrammingError:
        init_db()
    return None

# =========================
# RUTAS
# =========================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        init_db()  # Garantizar tablas
        username = request.form["username"]
        password = request.form["password"]

        with engine.connect() as conn:
            user = conn.execute(text("SELECT * FROM usuarios WHERE username=:u"), {"u": username}).fetchone()

        if user and check_password_hash(user.password, password):
            login_user(User(*user))
            registrar_evento(username, "login")
            return redirect(url_for("index"))
        return render_template("login.html", error="Usuario o contraseña incorrectos")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    registrar_evento(current_user.username, "logout")
    logout_user()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    return render_template("index.html", role=current_user.role, username=current_user.username)

@app.route("/upload", methods=["POST"])
@login_required
def upload_excel():
    if current_user.role != "uploader":
        return jsonify({"error": "No tienes permisos para subir archivos"}), 403

    file = request.files.get("file")
    if not file:
        return jsonify({"error": "No se envió ningún archivo"}), 400

    df = pd.read_excel(file)
    df.to_sql("registros", engine, if_exists="append", index=False)
    registrar_evento(current_user.username, "subir_archivo")
    return jsonify({"message": "Datos insertados correctamente"})

@app.route("/data", methods=["GET"])
@login_required
def get_data():
    init_db()  # Garantizar tablas
    query = "SELECT * FROM registros ORDER BY id DESC"
    df = pd.read_sql(query, engine)
    return jsonify(df.to_dict(orient="records"))

@app.route("/download", methods=["GET"])
@login_required
def download_excel():
    try:
        query = "SELECT * FROM registros ORDER BY id DESC"
        df = pd.read_sql(query, engine)

        if df.empty:
            # Si no hay datos, crear un Excel vacío con encabezados
            df = pd.DataFrame(columns=["id", "nombre", "email", "puntaje"])

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="Registros")

        output.seek(0)

        registrar_evento(current_user.username, "descargar_archivo")
        return send_file(
            output,
            download_name="registros.xlsx",
            as_attachment=True,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        return f"Error generando Excel: {str(e)}", 500

@app.route("/eventos", methods=["GET"])
@login_required
def ver_eventos():
    if current_user.role != "uploader":
        return jsonify({"error": "No tienes permisos"}), 403

    registrar_evento(current_user.username, "ver_eventos")
    query = """
        SELECT id, usuario, accion,
               to_char(fecha, 'YYYY-MM-DD HH24:MI:SS') as fecha
        FROM eventos
        ORDER BY id DESC
    """
    df = pd.read_sql(query, engine)
    return render_template("eventos.html", eventos=df.to_dict(orient="records"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
