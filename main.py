from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import sqlite3, os, datetime

app = FastAPI()

DB_PATH = os.environ.get("DB_PATH", "clientes.db")
PUNTOS_BENEFICIO = 10

# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre    TEXT NOT NULL,
            telefono  TEXT NOT NULL UNIQUE,
            fecha_reg TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS visitas (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL REFERENCES clientes(id),
            fecha      TEXT NOT NULL,
            sucursal   TEXT NOT NULL DEFAULT 'general',
            monto      INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS beneficios_usados (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL REFERENCES clientes(id),
            fecha      TEXT NOT NULL,
            sucursal   TEXT NOT NULL DEFAULT 'general'
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def hoy():
    return datetime.date.today().isoformat()

def cliente_dict(row, visitas, beneficios_usados_count):
    total_visitas = len(visitas)
    beneficios_ganados = total_visitas // PUNTOS_BENEFICIO
    pts_ciclo = total_visitas % PUNTOS_BENEFICIO
    tiene_beneficio = beneficios_ganados > beneficios_usados_count
    ultima = visitas[-1]["fecha"] if visitas else None
    gasto_total = sum(v["monto"] for v in visitas)

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
        "visitas": [dict(v) for v in visitas],
    }

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ClienteCreate(BaseModel):
    nombre: str
    telefono: str
    sucursal: Optional[str] = "general"

class VisitaCreate(BaseModel):
    sucursal: Optional[str] = "general"
    monto: Optional[int] = 0

class BeneficioUsar(BaseModel):
    sucursal: Optional[str] = "general"

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/clientes/buscar")
def buscar_cliente(telefono: str):
    tel = telefono.strip().replace(" ", "")
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM clientes WHERE REPLACE(telefono,' ','') = ?", (tel,)
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    visitas = conn.execute(
        "SELECT * FROM visitas WHERE cliente_id = ? ORDER BY fecha", (row["id"],)
    ).fetchall()
    bu = conn.execute(
        "SELECT COUNT(*) as n FROM beneficios_usados WHERE cliente_id = ?", (row["id"],)
    ).fetchone()["n"]
    conn.close()
    return cliente_dict(row, visitas, bu)


@app.post("/api/clientes", status_code=201)
def crear_cliente(data: ClienteCreate):
    tel = data.telefono.strip()
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM clientes WHERE REPLACE(telefono,' ','') = ?",
        (tel.replace(" ", ""),)
    ).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=409, detail="Teléfono ya registrado")
    cur = conn.execute(
        "INSERT INTO clientes (nombre, telefono, fecha_reg) VALUES (?,?,?)",
        (data.nombre.strip(), tel, hoy())
    )
    cliente_id = cur.lastrowid
    conn.execute(
        "INSERT INTO visitas (cliente_id, fecha, sucursal, monto) VALUES (?,?,?,?)",
        (cliente_id, hoy(), data.sucursal, 0)
    )
    conn.commit()
    row = conn.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    visitas = conn.execute(
        "SELECT * FROM visitas WHERE cliente_id = ? ORDER BY fecha", (cliente_id,)
    ).fetchall()
    conn.close()
    return cliente_dict(row, visitas, 0)


@app.post("/api/clientes/{cliente_id}/visita")
def registrar_visita(cliente_id: int, data: VisitaCreate):
    conn = get_db()
    row = conn.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    ultima = conn.execute(
        "SELECT fecha FROM visitas WHERE cliente_id = ? ORDER BY fecha DESC LIMIT 1",
        (cliente_id,)
    ).fetchone()
    if ultima and ultima["fecha"] == hoy():
        visitas = conn.execute(
            "SELECT * FROM visitas WHERE cliente_id = ? ORDER BY fecha", (cliente_id,)
        ).fetchall()
        bu = conn.execute(
            "SELECT COUNT(*) as n FROM beneficios_usados WHERE cliente_id = ?", (cliente_id,)
        ).fetchone()["n"]
        conn.close()
        result = cliente_dict(row, visitas, bu)
        result["nueva_visita"] = False
        return result
    conn.execute(
        "INSERT INTO visitas (cliente_id, fecha, sucursal, monto) VALUES (?,?,?,?)",
        (cliente_id, hoy(), data.sucursal, data.monto)
    )
    conn.commit()
    visitas = conn.execute(
        "SELECT * FROM visitas WHERE cliente_id = ? ORDER BY fecha", (cliente_id,)
    ).fetchall()
    bu = conn.execute(
        "SELECT COUNT(*) as n FROM beneficios_usados WHERE cliente_id = ?", (cliente_id,)
    ).fetchone()["n"]
    conn.close()
    result = cliente_dict(row, visitas, bu)
    result["nueva_visita"] = True
    return result


@app.post("/api/clientes/{cliente_id}/usar-beneficio")
def usar_beneficio(cliente_id: int, data: BeneficioUsar):
    conn = get_db()
    row = conn.execute("SELECT * FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    visitas = conn.execute(
        "SELECT * FROM visitas WHERE cliente_id = ? ORDER BY fecha", (cliente_id,)
    ).fetchall()
    bu = conn.execute(
        "SELECT COUNT(*) as n FROM beneficios_usados WHERE cliente_id = ?", (cliente_id,)
    ).fetchone()["n"]
    ganados = len(visitas) // PUNTOS_BENEFICIO
    if ganados <= bu:
        conn.close()
        raise HTTPException(status_code=400, detail="Sin beneficio disponible")
    conn.execute(
        "INSERT INTO beneficios_usados (cliente_id, fecha, sucursal) VALUES (?,?,?)",
        (cliente_id, hoy(), data.sucursal)
    )
    conn.commit()
    bu2 = conn.execute(
        "SELECT COUNT(*) as n FROM beneficios_usados WHERE cliente_id = ?", (cliente_id,)
    ).fetchone()["n"]
    conn.close()
    return cliente_dict(row, visitas, bu2)


@app.get("/api/admin/resumen")
def resumen():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) as n FROM clientes").fetchone()["n"]
    hoy_str = hoy()
    visitas_hoy = conn.execute(
        "SELECT COUNT(*) as n FROM visitas WHERE fecha = ?", (hoy_str,)
    ).fetchone()["n"]
    total_visitas = conn.execute("SELECT COUNT(*) as n FROM visitas").fetchone()["n"]
    top = conn.execute("""
        SELECT c.id, c.nombre, c.telefono, COUNT(v.id) as total_visitas
        FROM clientes c LEFT JOIN visitas v ON v.cliente_id = c.id
        GROUP BY c.id ORDER BY total_visitas DESC LIMIT 10
    """).fetchall()
    conn.close()
    return {
        "total_clientes": total,
        "visitas_hoy": visitas_hoy,
        "total_visitas": total_visitas,
        "top_clientes": [dict(r) for r in top],
    }


# Sirve el frontend
app.mount("/", StaticFiles(directory="static", html=True), name="static")
