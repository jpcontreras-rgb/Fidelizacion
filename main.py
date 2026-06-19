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
DATABASE_URL = os.environ.get("DATABASE_URL", "")
SECRET = os.environ.get("CODIGO_SECRET", "schwencke2025")

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
            sucursal   TEXT NOT NULL DEFAULT 'general',
            monto      INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS beneficios_usados (
            id         SERIAL PRIMARY KEY,
            cliente_id INTEGER NOT NULL REFERENCES clientes(id),
            fecha      TEXT NOT NULL,
            sucursal   TEXT NOT NULL DEFAULT 'general'
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

if DATABASE_URL:
    init_db()

def hoy():
    return datetime.date.today().isoformat()

def generar_codigo_dia():
    """Genera un código de 4 dígitos basado en la fecha + secret. Cambia cada día."""
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

def cliente_dict(row, visitas, beneficios_usados_count):
    total_visitas = len(visitas)
    beneficios_ganados = total_visitas // PUNTOS_BENEFICIO
    pts_ciclo = total_visitas % PUNTOS_BENEFICIO
    tiene_beneficio = beneficios_ganados > beneficios_usados_count
    ultima = visitas[-1]["fecha"] if visitas else None
    gasto_total = sum(v["monto"] or 0 for v in visitas)
    return {
        "id": row["id"],
        "nombre": row["nombre"],
        "telefono": row["telefono"],
        "fecha_reg": row["fecha_reg"],
        "total_visitas": total_visitas,
        "pts_ciclo": pts_ciclo,
        "puntos_para_beneficio": PUNTOS_BENEFICIO,
        "beneficios_ganados": beneficios_ganados,
        "beneficios_usados": beneficios_usados_count,
        "tiene_beneficio": tiene_beneficio,
        "ultima_visita": ultima,
        "gasto_total": gasto_total,
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

@app.get("/api/codigo-hoy")
def codigo_hoy():
    """Solo para el panel del cajero"""
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
    cur.execute("SELECT * FROM visitas WHERE cliente_id = %s ORDER BY fecha", (row["id"],))
    visitas = fetch_all(cur)
    cur.execute("SELECT COUNT(*) as n FROM beneficios_usados WHERE cliente_id = %s", (row["id"],))
    bu = cur.fetchone()[0]
    cur.close(); conn.close()
    return cliente_dict(row, visitas, bu)

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
    cur.execute(
        "INSERT INTO visitas (cliente_id, fecha, sucursal, monto) VALUES (%s,%s,%s,%s)",
        (cliente_id, hoy(), data.sucursal, 0)
    )
    conn.commit()
    cur.execute("SELECT * FROM clientes WHERE id = %s", (cliente_id,))
    row = fetch_one(cur)
    cur.execute("SELECT * FROM visitas WHERE cliente_id = %s ORDER BY fecha", (cliente_id,))
    visitas = fetch_all(cur)
    cur.close(); conn.close()
    return cliente_dict(row, visitas, 0)

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
    cur.execute(
        "SELECT fecha FROM visitas WHERE cliente_id = %s ORDER BY fecha DESC LIMIT 1", (cliente_id,)
    )
    ultima = cur.fetchone()
    if ultima and ultima[0] == hoy():
        cur.execute("SELECT * FROM visitas WHERE cliente_id = %s ORDER BY fecha", (cliente_id,))
        visitas = fetch_all(cur)
        cur.execute("SELECT COUNT(*) FROM beneficios_usados WHERE cliente_id = %s", (cliente_id,))
        bu = cur.fetchone()[0]
        cur.close(); conn.close()
        result = cliente_dict(row, visitas, bu)
        result["nueva_visita"] = False
        return result
    cur.execute(
        "INSERT INTO visitas (cliente_id, fecha, sucursal, monto) VALUES (%s,%s,%s,%s)",
        (cliente_id, hoy(), data.sucursal, data.monto)
    )
    conn.commit()
    cur.execute("SELECT * FROM visitas WHERE cliente_id = %s ORDER BY fecha", (cliente_id,))
    visitas = fetch_all(cur)
    cur.execute("SELECT COUNT(*) FROM beneficios_usados WHERE cliente_id = %s", (cliente_id,))
    bu = cur.fetchone()[0]
    cur.close(); conn.close()
    result = cliente_dict(row, visitas, bu)
    result["nueva_visita"] = True
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
    cur.execute("SELECT * FROM visitas WHERE cliente_id = %s ORDER BY fecha", (cliente_id,))
    visitas = fetch_all(cur)
    cur.execute("SELECT COUNT(*) FROM beneficios_usados WHERE cliente_id = %s", (cliente_id,))
    bu = cur.fetchone()[0]
    ganados = len(visitas) // PUNTOS_BENEFICIO
    if ganados <= bu:
        cur.close(); conn.close()
        raise HTTPException(status_code=400, detail="Sin beneficio disponible")
    cur.execute(
        "INSERT INTO beneficios_usados (cliente_id, fecha, sucursal) VALUES (%s,%s,%s)",
        (cliente_id, hoy(), data.sucursal)
    )
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM beneficios_usados WHERE cliente_id = %s", (cliente_id,))
    bu2 = cur.fetchone()[0]
    cur.close(); conn.close()
    return cliente_dict(row, visitas, bu2)

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
    return {
        "total_clientes": total,
        "visitas_hoy": visitas_hoy,
        "total_visitas": total_visitas,
        "top_clientes": top,
    }

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
