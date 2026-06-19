# Schwencke Emporio — Sistema de Fidelización

App web que los clientes abren escaneando un QR. Registra visitas automáticamente y muestra tarjeta de puntos.

## Estructura

```
schwencke-fidelizacion/
├── main.py           ← API backend (FastAPI)
├── static/
│   └── index.html    ← App del cliente (pantalla QR)
├── requirements.txt
├── Procfile
└── README.md
```

## Deploy en Railway (paso a paso)

### 1. Subir el proyecto a GitHub
```bash
git init
git add .
git commit -m "primera versión"
# Crear repo en github.com y seguir instrucciones
git remote add origin https://github.com/TU_USUARIO/schwencke-fidelizacion.git
git push -u origin main
```

### 2. Crear servicio en Railway
1. Ir a railway.app → New Project → Deploy from GitHub repo
2. Seleccionar el repositorio
3. Railway detecta automáticamente el Procfile y despliega

### 3. Agregar base de datos persistente (importante)
Por defecto SQLite guarda en disco, que se reinicia con cada deploy.
Para producción, agregar un volumen:
1. En Railway → tu servicio → Volumes → Add Volume
2. Mount path: `/data`
3. En Variables de entorno agregar: `DB_PATH=/data/clientes.db`

### 4. URL y QR
Una vez deployado, Railway te da una URL como:
`https://schwencke-fidelizacion-production.up.railway.app`

Con esa URL:
- Generar QR en: https://qr.io o https://www.qr-code-generator.com
- Pegar la URL, descargar el QR como PNG o SVG
- Imprimir el afiche con ese QR

## Panel administrador

Disponible en: `https://TU-URL/admin`

Desde ahí el cajero puede:
- Buscar clientes por teléfono
- Registrar visitas manualmente
- Ver top de clientes frecuentes
- Marcar beneficios usados

## API endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/clientes/buscar?telefono=+569...` | Buscar cliente |
| POST | `/api/clientes` | Registrar cliente nuevo |
| POST | `/api/clientes/{id}/visita` | Registrar visita |
| POST | `/api/clientes/{id}/usar-beneficio` | Canjear beneficio |
| GET | `/api/admin/resumen` | Estadísticas generales |

## Lógica de puntos

- 1 visita = 1 punto
- 10 puntos = 1 beneficio (configurable en `main.py` → `PUNTOS_BENEFICIO`)
- Una sola visita por día por cliente
- Los beneficios se marcan manualmente desde el panel admin o la app del cajero

## Variables de entorno

| Variable | Descripción | Default |
|----------|-------------|---------|
| `DB_PATH` | Ruta de la base de datos SQLite | `clientes.db` |
| `PORT` | Puerto (Railway lo pone automático) | `8000` |
