import os
import sqlite3
from pathlib import Path

# Usar el directorio de datos de Render si está disponible, si no, el directorio local.
DATA_DIR = Path(os.getenv("RENDER_DATA_DIR", Path(__file__).parent))
DB_PATH = str(DATA_DIR / "lavanderia.db")

def _conn():
    return sqlite3.connect(DB_PATH)

def crear_bd():
    """Crea la BD original (boletas) y además el nuevo esquema (boleta + boleta_items)."""
    with _conn() as conn:
        cur = conn.cursor()

        # ===== Esquema ORIGINAL (lo mantenemos para compatibilidad) =====
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS boletas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente TEXT NOT NULL,
                tipo_item TEXT NOT NULL,
                kilos REAL DEFAULT 0,
                cantidad INTEGER DEFAULT 0,
                servicio TEXT DEFAULT 'normal',
                perfumado INTEGER DEFAULT 0,
                precio REAL NOT NULL,
                fecha TEXT NOT NULL,
                metodo_pago TEXT DEFAULT 'efectivo',
                estado TEXT DEFAULT 'registrado'
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_boletas_fecha ON boletas(fecha)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_boletas_cliente ON boletas(cliente)")

        # ===== NUEVO ESQUEMA (Cabecera + Items) =====
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS boleta (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero TEXT,                  -- opcional: correlativo impreso (N° 007601)
                cliente TEXT NOT NULL,
                direccion TEXT,
                telefono TEXT,
                fecha TEXT NOT NULL,          -- fecha de emisión
                entrega_fecha TEXT,           -- fecha prometida
                entrega_hora TEXT,            -- hora prometida (ej. '17:00')
                metodo_pago TEXT DEFAULT 'efectivo',
                estado TEXT DEFAULT 'registrado',
                a_cuenta REAL DEFAULT 0,      -- pago parcial
                saldo REAL DEFAULT 0,
                total REAL DEFAULT 0,         -- total de la boleta (suma items)
                notas TEXT                    -- observaciones (ej. 'Martes 5 pm')
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_boleta_fecha ON boleta(fecha)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_boleta_cliente ON boleta(cliente)")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS boleta_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                boleta_id INTEGER NOT NULL REFERENCES boleta(id) ON DELETE CASCADE,
                descripcion TEXT,             -- 'Frazadas', 'Edredón', 'Kilos', etc.
                tipo TEXT,                    -- kilos | edredon | terno | otro
                prendas INTEGER DEFAULT 0,    -- nº de prendas (para terno/edredón)
                kilos REAL DEFAULT 0,         -- para servicio por kilos
                lavado TEXT,                  -- 'Normal', 'Seco', 'A mano'...
                secado TEXT,                  -- 'Secadora', 'Tendedero'...
                p_unit REAL DEFAULT 0,        -- precio unitario (por kilo o por prenda)
                importe REAL DEFAULT 0        -- subtotal del item
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_bitems_boleta ON boleta_items(boleta_id)")

        # ===== TABLA DE CONFIGURACIÓN =====
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        # Insertar contraseñas por defecto si no existen
        cur.execute("INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", ('USER_PASSWORD', 'Rios123'))
        cur.execute("INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", ('ADMIN_PASSWORD', 'Cris123'))

        conn.commit()

# ====== NUEVA API (Boleta con múltiples items) ======
def insertar_boleta_compuesta(cabecera: dict, items: list[dict]) -> int:
    """
    Inserta una boleta (cabecera) + sus items.
    cabecera: dict con keys: numero, cliente, direccion, telefono, fecha, entrega_fecha, entrega_hora,
                             metodo_pago, estado, a_cuenta, saldo, total, notas
    items: lista de dicts con keys: descripcion, tipo, prendas, kilos, lavado, secado, p_unit, importe
    Return: boleta_id (int)
    """
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO boleta (numero, cliente, direccion, telefono, fecha, entrega_fecha, entrega_hora,
                                metodo_pago, estado, a_cuenta, saldo, total, notas)
            VALUES (:numero, :cliente, :direccion, :telefono, :fecha, :entrega_fecha, :entrega_hora,
                    :metodo_pago, :estado, :a_cuenta, :saldo, :total, :notas)
            """,
            cabecera
        )
        boleta_id = cur.lastrowid

        for it in items:
            it = {**it, "boleta_id": boleta_id}
            cur.execute(
                """
                INSERT INTO boleta_items (boleta_id, descripcion, tipo, prendas, kilos, lavado, secado, p_unit, importe)
                VALUES (:boleta_id, :descripcion, :tipo, :prendas, :kilos, :lavado, :secado, :p_unit, :importe)
                """,
                it
            )
        conn.commit()
        return boleta_id

def obtener_boletas_paginado(limit=20, offset=0, cliente=None, fecha_desde=None, fecha_hasta=None):
    """Obtiene boletas paginadas y el conteo total. Usa el nuevo esquema."""
    with _conn() as conn:
        conn.row_factory = sqlite3.Row  # Devolver resultados como diccionarios
        cur = conn.cursor()
        
        base_q = "FROM boleta"
        params, conds = [], []
        if cliente:
            conds.append("cliente LIKE ?"); params.append(f"%{cliente}%")
        if fecha_desde:
            conds.append("date(fecha) >= date(?)"); params.append(fecha_desde)
        if fecha_hasta:
            conds.append("date(fecha) <= date(?)"); params.append(fecha_hasta)
        
        where_clause = " WHERE " + " AND ".join(conds) if conds else ""

        # Contar total de registros
        cur.execute(f"SELECT COUNT(1) {base_q}{where_clause}", params)
        total_registros = cur.fetchone()[0]

        # Obtener filas paginadas
        q_filas = (f"SELECT * {base_q}{where_clause} "
                   "ORDER BY fecha DESC, id DESC LIMIT ? OFFSET ?")
        cur.execute(q_filas, params + [limit, offset])
        filas = cur.fetchall()
        
        return filas, total_registros

def total_periodo(cliente=None, fecha_desde=None, fecha_hasta=None):
    """Calcula el SUM(total) del nuevo esquema de boletas."""
    with _conn() as conn:
        cur = conn.cursor()
        q = "SELECT COALESCE(SUM(total), 0) FROM boleta"
        params, conds = [], []
        if cliente:
            conds.append("cliente LIKE ?"); params.append(f"%{cliente}%")
        if fecha_desde:
            conds.append("date(fecha) >= date(?)"); params.append(fecha_desde)
        if fecha_hasta:
            conds.append("date(fecha) <= date(?)"); params.append(fecha_hasta)
        if conds: q += " WHERE " + " AND ".join(conds)
        cur.execute(q, params)
        return float(cur.fetchone()[0])

def obtener_boleta_detalle(boleta_id: int):
    """Devuelve (cabecera, items[])"""
    with _conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT id, numero, cliente, direccion, telefono, fecha, entrega_fecha, entrega_hora, "
            "metodo_pago, estado, a_cuenta, saldo, total, notas "
            "FROM boleta WHERE id = ?",
            (boleta_id,)
        )
        cab = cur.fetchone()

        cur.execute(
            "SELECT id, descripcion, tipo, prendas, kilos, lavado, secado, p_unit, importe "
            "FROM boleta_items WHERE boleta_id = ? ORDER BY id ASC",
            (boleta_id,)
        )
        items = cur.fetchall()
        return cab, items

def obtener_boletas_todas():
    """Obtiene todas las boletas del nuevo esquema para exportación."""
    with _conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM boleta ORDER BY fecha DESC, id DESC")
        return cur.fetchall()

# ====== API DE CONFIGURACIÓN ======
def get_config(key: str, default: str = None) -> str:
    """Obtiene un valor de la tabla de configuración."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM config WHERE key = ?", (key,))
        res = cur.fetchone()
        return res[0] if res else default

def set_config(key: str, value: str):
    """Establece un valor en la tabla de configuración."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
        conn.commit()

def eliminar_boleta(boleta_id: int):
    """Elimina una boleta y sus items asociados."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM boleta WHERE id = ?", (boleta_id,))
        conn.commit()

def actualizar_estado_boleta(boleta_id: int, nuevo_estado: str):
    """Actualiza el estado de una boleta específica."""
    with _conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE boleta SET estado = ? WHERE id = ?", (nuevo_estado, boleta_id))
        conn.commit()
