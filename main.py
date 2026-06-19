from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional
import os, datetime, hashlib

app = FastAPI()

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
INDEX_PATH = os.path.join(STATIC_DIR, "index.html")
CAJERO_PATH = os.path.join(STATIC_DIR, "cajero.html")
os.makedirs(STATIC_DIR, exist_ok=True)

PUNTOS_BENEFICIO = 10
PUNTOS_POSTRE = 5
DATABASE_URL = os.environ.get("DATABASE_URL", "")
SECRET = os.environ.get("CODIGO_SECRET", "schwencke2025")
MINUTOS_ENTRE_VISITAS = 60

def get_db():
    import psycopg2
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id        SERIAL PRIMARY KEY,
            nombre    TEXT NOT NULL,
            telefono  TEXT NOT NULL UNIQUE,
            fecha_reg TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS visitas (
            id         SERIAL PRIMARY KEY,
            cliente_id INTEGER NOT NULL REFERENCES clientes(id),
            fecha      TEXT NOT NULL,
            hora       TEXT NOT NULL DEFAULT '00:00',
            sucursal   TEXT NOT NULL DEFAULT 'general',
            monto      INTEGER DEFAULT 0
        )
    """)
    # Agregar columna hora si no existe (para bases de datos existentes)
    try:
        cur.execute("ALTER TABLE visitas ADD COLUMN IF NOT EXISTS hora TEXT NOT NULL DEFAULT '00:00'")
    except:
        pass
    cur.execute("""
        CREATE TABLE IF NOT EXISTS beneficios_usados (
            id         SERIAL PRIMARY KEY,
            cliente_id INTEGER NOT NULL REFERENCES clientes(id),
            fecha      TEXT NOT NULL,
            tipo       TEXT NOT NULL DEFAULT 'promocion',
            sucursal   TEXT NOT NULL DEFAULT 'general'
        )
    """)
    try:
        cur.execute("ALTER TABLE beneficios_usados ADD COLUMN IF NOT EXISTS tipo TEXT NOT NULL DEFAULT 'promocion'")
    except:
        pass
    conn.commit()
    cur.close()
    conn.close()

if DATABASE_URL:
    init_db()

def hoy():
    return datetime.date.today().isoformat()

def ahora():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

def generar_codigo_dia():
    base = f"{hoy()}-{SECRET}"
    hash_val = hashlib.sha256(base.encode()).hexdigest()
    numero = int(hash_val[:8], 16) % 10000
    return f"{numero:04d}"

def fetch_all(cur):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]

def fetch_one(cur):
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else None

def minutos_desde(fecha_hora_str):
    try:
        dt = datetime.datetime.strptime(fecha_hora_str, "%Y-%m-%d %H:%M")
        diff = datetime.datetime.now() - dt
        return diff.total_seconds() / 60
    except:
        return 999

def calcular_premios(total_visitas, beneficios_usados_list):
    """Calcula postres y promociones ganadas vs usadas."""
    postres_ganados = total_visitas // PUNTOS_POSTRE
    promociones_ganadas = total_visitas // PUNTOS_BENEFICIO

    postres_usados = sum(1 for b in beneficios_usados_list if b.get("tipo") == "postre")
    promociones_usadas = sum(1 for b in beneficios_usados_list if b.get("tipo") == "promocion")

    # Descontar postres de los que serían promociones
    # Cada 10 visitas: 1 postre (en visita 5) + 1 promoción (en visita 10)
    # Pero en visita 10 ya se ganó el postre de visita 5, así que:
    postres_netos = postres_ganados - (promociones_ganadas)  # en cada ciclo de 10, visita 5 da postre
    postres_netos = max(postres_netos, 0)

    tiene_postre = (postres_ganados - postres_usados - promociones_ganadas) > 0
    tiene_promocion = (promociones_ganadas - promociones_usadas) > 0

    pts_en_ciclo = total_visitas % PUNTOS_BENEFICIO

    return {
        "pts_ciclo": pts_en_ciclo,
        "puntos_para_beneficio": PUNTOS_BENEFICIO,
        "postres_ganados": postres_ganados,
        "postres_usados": postres_usados,
        "promociones_ganadas": promociones_ganadas,
        "promociones_usadas": promociones_usadas,
        "tiene_postre": tiene_postre,
        "tiene_promocion": tiene_promocion,
    }

def cliente_dict(row, visitas, beneficios_list):
    total_visitas = len(visitas)
    ultima = None
    if visitas:
        v = visitas[-1]
        ultima = f"{v['fecha']} {v.get('hora','00:00')}"
    premios = calcular_premios(total_visitas, beneficios_list)
    return {
        "id": row["id"],
        "nombre": row["nombre"],
        "telefono": row["telefono"],
        "fecha_reg": row["fecha_reg"],
        "total_visitas": total_visitas,
        "ultima_visita": ultima,
        **premios,
        "visitas": visitas,
    }

class ClienteCreate(BaseModel):
    nombre: str
    telefono: str
    sucursal: Optional[str] = "general"
    codigo: str

class VisitaCreate(BaseModel):
    sucursal: Optional[str] = "general"
    monto: Optional[int] = 0
    codigo: str

class BeneficioUsar(BaseModel):
    sucursal: Optional[str] = "general"
    tipo: Optional[str] = "promocion"

@app.get("/api/codigo-hoy")
def codigo_hoy():
    return {"codigo": generar_codigo_dia(), "fecha": hoy()}

@app.get("/api/clientes/buscar")
def buscar_cliente(telefono: str):
    tel = telefono.strip().replace(" ", "")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM clientes WHERE REPLACE(telefono,' ','') = %s", (tel,))
    row = fetch_one(cur)
    if not row:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    cur.execute("SELECT id, fecha, hora, sucursal, monto FROM visitas WHERE cliente_id = %s ORDER BY fecha, hora", (row["id"],))
    visitas = fetch_all(cur)
    cur.execute("SELECT tipo FROM beneficios_usados WHERE cliente_id = %s", (row["id"],))
    rows = cur.fetchall()
    beneficios_list = [{"tipo": r[0]} for r in rows]
    cur.close(); conn.close()
    return cliente_dict(row, visitas, beneficios_list)

@app.post("/api/clientes", status_code=201)
def crear_cliente(data: ClienteCreate):
    if data.codigo != generar_codigo_dia():
        raise HTTPException(status_code=403, detail="Código incorrecto")
    tel = data.telefono.strip()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM clientes WHERE REPLACE(telefono,' ','') = %s", (tel.replace(" ", ""),))
    if cur.fetchone():
        cur.close(); conn.close()
        raise HTTPException(status_code=409, detail="Telefono ya registrado")
    cur.execute(
        "INSERT INTO clientes (nombre, telefono, fecha_reg) VALUES (%s,%s,%s) RETURNING id",
        (data.nombre.strip(), tel, hoy())
    )
    cliente_id = cur.fetchone()[0]
    hora_actual = datetime.datetime.now().strftime("%H:%M")
    cur.execute(
        "INSERT INTO visitas (cliente_id, fecha, hora, sucursal, monto) VALUES (%s,%s,%s,%s,%s)",
        (cliente_id, hoy(), hora_actual, data.sucursal, 0)
    )
    conn.commit()
    cur.execute("SELECT * FROM clientes WHERE id = %s", (cliente_id,))
    row = fetch_one(cur)
    cur.execute("SELECT id, fecha, hora, sucursal, monto FROM visitas WHERE cliente_id = %s ORDER BY fecha, hora", (cliente_id,))
    visitas = fetch_all(cur)
    cur.close(); conn.close()
    return cliente_dict(row, visitas, [])

@app.post("/api/clientes/{cliente_id}/visita")
def registrar_visita(cliente_id: int, data: VisitaCreate):
    if data.codigo != generar_codigo_dia():
        raise HTTPException(status_code=403, detail="Código incorrecto")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM clientes WHERE id = %s", (cliente_id,))
    row = fetch_one(cur)
    if not row:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    # Verificar última visita — mínimo 60 minutos
    cur.execute(
        "SELECT fecha, hora FROM visitas WHERE cliente_id = %s ORDER BY fecha DESC, hora DESC LIMIT 1",
        (cliente_id,)
    )
    ultima = cur.fetchone()
    nueva_visita = True
    if ultima:
        ultima_str = f"{ultima[0]} {ultima[1]}"
        mins = minutos_desde(ultima_str)
        if mins < MINUTOS_ENTRE_VISITAS:
            nueva_visita = False

    if nueva_visita:
        hora_actual = datetime.datetime.now().strftime("%H:%M")
        cur.execute(
            "INSERT INTO visitas (cliente_id, fecha, hora, sucursal, monto) VALUES (%s,%s,%s,%s,%s)",
            (cliente_id, hoy(), hora_actual, data.sucursal, data.monto)
        )
        conn.commit()

    cur.execute("SELECT id, fecha, hora, sucursal, monto FROM visitas WHERE cliente_id = %s ORDER BY fecha, hora", (cliente_id,))
    visitas = fetch_all(cur)
    cur.execute("SELECT tipo FROM beneficios_usados WHERE cliente_id = %s", (cliente_id,))
    rows = cur.fetchall()
    beneficios_list = [{"tipo": r[0]} for r in rows]
    cur.close(); conn.close()
    result = cliente_dict(row, visitas, beneficios_list)
    result["nueva_visita"] = nueva_visita
    return result

@app.post("/api/clientes/{cliente_id}/usar-beneficio")
def usar_beneficio(cliente_id: int, data: BeneficioUsar):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM clientes WHERE id = %s", (cliente_id,))
    row = fetch_one(cur)
    if not row:
        cur.close(); conn.close()
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    cur.execute("SELECT id, fecha, hora, sucursal, monto FROM visitas WHERE cliente_id = %s ORDER BY fecha, hora", (cliente_id,))
    visitas = fetch_all(cur)
    cur.execute("SELECT tipo FROM beneficios_usados WHERE cliente_id = %s", (cliente_id,))
    rows = cur.fetchall()
    beneficios_list = [{"tipo": r[0]} for r in rows]
    premios = calcular_premios(len(visitas), beneficios_list)
    if data.tipo == "postre" and not premios["tiene_postre"]:
        cur.close(); conn.close()
        raise HTTPException(status_code=400, detail="Sin postre disponible")
    if data.tipo == "promocion" and not premios["tiene_promocion"]:
        cur.close(); conn.close()
        raise HTTPException(status_code=400, detail="Sin promoción disponible")
    cur.execute(
        "INSERT INTO beneficios_usados (cliente_id, fecha, tipo, sucursal) VALUES (%s,%s,%s,%s)",
        (cliente_id, hoy(), data.tipo, data.sucursal)
    )
    conn.commit()
    cur.execute("SELECT tipo FROM beneficios_usados WHERE cliente_id = %s", (cliente_id,))
    rows2 = cur.fetchall()
    beneficios_list2 = [{"tipo": r[0]} for r in rows2]
    cur.close(); conn.close()
    return cliente_dict(row, visitas, beneficios_list2)

@app.get("/api/admin/resumen")
def resumen():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM clientes")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM visitas WHERE fecha = %s", (hoy(),))
    visitas_hoy = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM visitas")
    total_visitas = cur.fetchone()[0]
    cur.execute("""
        SELECT c.id, c.nombre, c.telefono, COUNT(v.id) as total_visitas
        FROM clientes c LEFT JOIN visitas v ON v.cliente_id = c.id
        GROUP BY c.id ORDER BY total_visitas DESC LIMIT 10
    """)
    top = fetch_all(cur)
    cur.close(); conn.close()
    return {"total_clientes": total, "visitas_hoy": visitas_hoy, "total_visitas": total_visitas, "top_clientes": top}

@app.get("/cajero", response_class=HTMLResponse)
def serve_cajero():
    if os.path.exists(CAJERO_PATH):
        with open(CAJERO_PATH, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h2>Falta static/cajero.html</h2>")

@app.get("/", response_class=HTMLResponse)
def serve_index():
    if not DATABASE_URL:
        return HTMLResponse(content="<h2>Falta variable DATABASE_URL</h2>")
    if os.path.exists(INDEX_PATH):
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Schwencke Fidelizacion OK</h1>")
