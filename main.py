import os
import time
from datetime import datetime
from typing import Any, Dict
import httpx
from mcp.server.fastmcp import FastMCP

# Variables de entorno
KIOSKERA_BASE_URL = os.getenv("KIOSKERA_BASE_URL", "https://test.api.kioskera.es:16980")
KIOSKERA_EMAIL = os.getenv("KIOSKERA_EMAIL", "system2pay@system2pay.com")
KIOSKERA_PASSWORD = os.getenv("KIOSKERA_PASSWORD", "system2pay1212!")

# Servidor MCP
mcp = FastMCP("Kioskera Completo MCP")

# Cache del token
token_cache = {"token": None, "expires_at": 0}

async def obtener_token_valido() -> str:
    """Obtiene o renueva el token Bearer de la API Kioskera."""
    ahora = time.time()
    if token_cache["token"] and token_cache["expires_at"] > ahora:
        return token_cache["token"]

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{KIOSKERA_BASE_URL}/api/login",
            json={"email": KIOSKERA_EMAIL, "password": KIOSKERA_PASSWORD},
            timeout=10.0,
        )
        response.raise_for_status()
        token = response.json().get("token")
        token_cache["token"] = token
        token_cache["expires_at"] = ahora + 3300 # Expiración en 55 mins
        return token

def normalizar_a_epoch(fecha_str: str) -> int:
    """Convierte fechas legibles a Unix Epoch."""
    if str(fecha_str).isdigit():
        return int(fecha_str)
    try:
        dt = datetime.strptime(fecha_str, "%Y-%m-%d")
        return int(dt.timestamp())
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(fecha_str)
        return int(dt.timestamp())
    except ValueError:
        raise ValueError(f"Formato no válido: '{fecha_str}'. Usa 'YYYY-MM-DD' o timestamp.")

# --- 1. MÁQUINAS ---

@mcp.tool()
async def listar_maquinas() -> Dict[str, Any]:
    """Obtiene la lista de todas las máquinas (id, name, serial) de la empresa."""
    token = await obtener_token_valido()
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{KIOSKERA_BASE_URL}/api/company/machines/get",
            headers={"Authorization": f"Bearer {token}"}
        )
        return res.json()

@mcp.tool()
async def estado_maquina(machine_id: int) -> Dict[str, Any]:
    """Consulta el estado técnico (powerOn, standby, outService) de una máquina."""
    token = await obtener_token_valido()
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{KIOSKERA_BASE_URL}/api/machine/status/get",
            params={"id": machine_id},
            headers={"Authorization": f"Bearer {token}"}
        )
        return res.json()

# --- 2. PRODUCTOS Y EJECUCIÓN ---

@mcp.tool()
async def productos_maquina(machine_id: int) -> Dict[str, Any]:
    """Obtiene los programas y servicios configurados para una máquina concreta."""
    token = await obtener_token_valido()
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{KIOSKERA_BASE_URL}/api/products/machine/get",
            params={"id": machine_id},
            headers={"Authorization": f"Bearer {token}"}
        )
        return res.json()

@mcp.tool()
async def ejecutar_accion_maquina(product_id: int, machine_id: int, cloud: int = 1) -> Dict[str, Any]:
    """Activa o ejecuta un producto/servicio en la lavadora o secadora objetivo."""
    token = await obtener_token_valido()
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{KIOSKERA_BASE_URL}/api/products/execute/postAction",
            json={"product_id": product_id, "machine_id": machine_id, "cloud": cloud},
            headers={"Authorization": f"Bearer {token}"}
        )
        # Gestionar errores controlados de la API (ej. 406 Not Possible)
        if res.status_code != 200:
            return {"error": True, "status": res.status_code, "detalle": res.text}
        return res.json()

# --- 3. FACTURACIÓN ---

@mcp.tool()
async def buscar_facturacion(
    machine_id: int, fecha_inicio: str, fecha_fin: str, limit: int = 100, offset: int = 0
) -> Dict[str, Any]:
    """Busca transacciones y facturación de una máquina entre dos fechas (YYYY-MM-DD o Epoch)."""
    token = await obtener_token_valido()
    start_epoch = normalizar_a_epoch(fecha_inicio)
    end_epoch = normalizar_a_epoch(fecha_fin)
    
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{KIOSKERA_BASE_URL}/api/transaction/get",
            params={
                "machine_id": machine_id,
                "start_date": start_epoch,
                "end_date": end_epoch,
                "limit": limit,
                "offset": offset,
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        return res.json()

# --- 4. GESTIÓN DE TARJETAS / MONEDERO ---

@mcp.tool()
async def crear_tarjeta(number_id: str, balance: int, begin_date: str = "0", end_date: str = "0") -> Dict[str, Any]:
    """Crea una tarjeta prepago nueva con un balance inicial (en céntimos). Usa '0' en fechas para sin caducidad."""
    token = await obtener_token_valido()
    b_epoch = 0 if begin_date == "0" else normalizar_a_epoch(begin_date)
    e_epoch = 0 if end_date == "0" else normalizar_a_epoch(end_date)
    
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{KIOSKERA_BASE_URL}/api/card/insertcard",
            json={
                "number_id": number_id,
                "balance": balance,
                "begin_date": b_epoch,
                "end_date": e_epoch
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        return res.json()

@mcp.tool()
async def obtener_info_tarjeta(number_id: str) -> Dict[str, Any]:
    """Obtiene el estado, saldo y detalles de una única tarjeta prepago por su number_id."""
    token = await obtener_token_valido()
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{KIOSKERA_BASE_URL}/api/card/getcard",
            params={"number_id": number_id},
            headers={"Authorization": f"Bearer {token}"}
        )
        if res.status_code == 404:
            return {"error": "Tarjeta no encontrada"}
        return res.json()

@mcp.tool()
async def listar_tarjetas(limit: int = 10, begin_date: str = "0", end_date: str = "0") -> Dict[str, Any]:
    """Lista de manera paginada las tarjetas prepago registradas en la empresa."""
    token = await obtener_token_valido()
    b_epoch = 0 if begin_date == "0" else normalizar_a_epoch(begin_date)
    e_epoch = 0 if end_date == "0" else normalizar_a_epoch(end_date)
    
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{KIOSKERA_BASE_URL}/api/card/getcards",
            params={"limit": limit, "begin_date": b_epoch, "end_date": e_epoch},
            headers={"Authorization": f"Bearer {token}"}
        )
        return res.json()

@mcp.tool()
async def eliminar_tarjeta(number_id: str) -> Dict[str, Any]:
    """Elimina permanentemente una tarjeta prepago dada su identificación."""
    token = await obtener_token_valido()
    async with httpx.AsyncClient() as client:
        res = await client.delete(
            f"{KIOSKERA_BASE_URL}/api/card/delete/{number_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        return res.json()


# Exposición de la aplicación ASGI/FastAPI para transporte SSE
app = mcp.sse_app()
