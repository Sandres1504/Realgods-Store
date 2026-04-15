from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
import psycopg2
from psycopg2.extras import RealDictCursor
import shutil
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_CONFIG = {
    "host": "localhost",
    "database": "tienda_ropa",
    "user": "postgres",
    "password": "123",
    "port": "5432"
}

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

def get_db_connection():
    try:
        return psycopg2.connect(**DB_CONFIG)
    except Exception as e:
        print(f"❌ Error de conexión: {e}")
        return None

class Producto(BaseModel):
    nombre: str
    categoria: str
    precio: float
    precio_costo: float
    stock: int
    imagen_url: Optional[str] = None

# 🔹 INVENTARIO
@app.get("/inventario")
async def obtener_inventario():
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Error conectando a la BD")
    
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute('SELECT * FROM inventario ORDER BY id ASC;')
        productos = cur.fetchall()

        for p in productos:
            p["alerta_stock"] = p["stock"] <= 5

        cur.close()
        conn.close()
        return productos

    except Exception as e:
        print("ERROR SQL:", e)
        raise HTTPException(status_code=500, detail=str(e))


# 🔥 COMPRAR (ARREGLADO)
@app.post("/comprar")
async def comprar(productos: List[dict]):
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        total = sum(float(p["precio"]) for p in productos)

        cur.execute(
            "INSERT INTO pedidos (total) VALUES (%s) RETURNING id;",
            (total,)
        )
        pedido_id = cur.fetchone()[0]

        for p in productos:
            cur.execute("""
                INSERT INTO detalle_pedido (pedido_id, producto_id, cantidad, precio)
                VALUES (%s, %s, %s, %s)
            """, (pedido_id, p["id"], 1, p["precio"]))

            cur.execute("""
                UPDATE inventario
                SET stock = stock - 1
                WHERE id = %s
            """, (p["id"],))

        conn.commit()
        return {"message": "Compra registrada"}

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))

    finally:
        cur.close()
        conn.close()


# 🔹 SUBIR PRODUCTO
@app.post("/productos/upload")
async def agregar_producto(
    nombre: str = Form(...),
    categoria: str = Form(...),
    precio: float = Form(...),
    precio_costo: float = Form(...),
    stock: int = Form(...),
    imagen: UploadFile = File(...)
):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500)

    file_path = f"{UPLOAD_DIR}/{imagen.filename}"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(imagen.file, buffer)

    cur = conn.cursor()
    cur.execute("""
        INSERT INTO inventario (nombre, categoria, precio, precio_costo, stock, imagen_url)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (nombre, categoria, precio, precio_costo, stock, file_path))

    conn.commit()
    cur.close()
    conn.close()

    return {"message": "ok"}


# 🔹 ESTADÍSTICAS
@app.get("/estadisticas")
async def estadisticas():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT 
            COUNT(*) as pedidos,
            SUM(total) as ganancias
        FROM pedidos
    """)
    resumen = cur.fetchone()

    cur.execute("""
        SELECT DATE_TRUNC('month', fecha) as mes,
                SUM(total) as total
        FROM pedidos
        GROUP BY mes
        ORDER BY total DESC
        LIMIT 1
    """)
    mejor_mes = cur.fetchone()

    return {
        "resumen": resumen,
        "mejor_mes": mejor_mes
    }


@app.delete("/productos/{producto_id}")
async def eliminar_producto(producto_id: int):
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Error de conexión")

    try:
        cur = conn.cursor()

        # 🔥 BORRAR RELACIONES PRIMERO
        cur.execute("DELETE FROM detalle_pedido WHERE producto_id = %s;", (producto_id,))

        # 🔥 LUEGO BORRAR PRODUCTO
        cur.execute("DELETE FROM inventario WHERE id = %s;", (producto_id,))

        conn.commit()
        return {"message": "Producto eliminado correctamente"}

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        cur.close()
        conn.close()