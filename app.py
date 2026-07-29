import os
import time
from datetime import datetime
import requests
from dotenv import load_dotenv
from fastmcp import FastMCP

# 1. Cargar variables de entorno locales
load_dotenv()

# 2. Configuración de credenciales y URL base oficial
KIOSKERA_EMAIL = os.getenv("KIOSKERA_EMAIL", "system2pay@system2pay.com")
KIOSKERA_PASSWORD = os.getenv("KIOSKERA_PASSWORD", "system2pay1212!")
BASE_URL = os.getenv("KIOSKERA_BASE_URL", "https://test.api.kioskera.es:16980")

# 3. Inicializar el servidor FastMCP
mcp = FastMCP("Kioskera")

# Cache de token
_TOKEN_CACHE = {"token": None, "expires_at": 0}


def obtener_token() -> str:
    """Obtiene o renueva el token Bearer para la API de Kioskera."""
    ahora = time.time()
    if _TOKEN_CACHE["token"] and _TOKEN_CACHE["expires_at"] > ahora:
        return _TOKEN_CACHE["token"]

    url = f"{BASE_URL.rstrip('/')}/api/login"
    payload = {"email": KIOSKERA_EMAIL, "password": KIOSKERA_PASSWORD}

    response = requests.post(url, json=payload, timeout=10)
    response.raise_for_status()
    data = response.json()

    token = data.get("token")
    _TOKEN_CACHE["token"] = token
    _TOKEN_CACHE["expires_at"] = ahora + 3300  # Válido ~55 minutos
    return token


def normalizar_a_epoch(fecha_str: str) -> int:
    """Convierte cadenas de fecha (YYYY-MM-DD) o timestamps a Unix Epoch."""
    if not fecha_str or str(fecha_str) == "0":
        return 0
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
        raise ValueError(f"Formato de fecha no válido: '{fecha_str}'. Usa 'YYYY-MM-DD' o Epoch.")


def call_kioskera(method: str, endpoint: str, **kwargs) -> dict | list:
    """
    Función centralizada para realizar peticiones a Kioskera
    inyectando automáticamente la autenticación Bearer.
    """
    try:
        token = obtener_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        url = f"{BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
        response = requests.request(method=method, url=url, headers=headers, timeout=15, **kwargs)

        if response.status_code == 404:
            return {"es_exitosa": False, "error": "Recurso no encontrado (404)"}

        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as e:
        return {"es_exitosa": False, "error": f"Error de comunicación/red: {str(e)}"}
    except Exception as e:
        return {"es_exitosa": False, "error": str(e)}


# ==============================================================================
# HERRAMIENTAS MCP (TOOLS)
# ==============================================================================

# --- 1. MÁQUINAS ---

@mcp.tool()
def listar_maquinas() -> dict | list:
    """Obtiene la lista de todas las máquinas (ID, nombre, número de serie) de la empresa."""
    return call_kioskera("GET", "/api/company/machines/get")


@mcp.tool()
def estado_maquina(machine_id: int) -> dict | list:
    """Consulta el estado técnico (powerOn, standby, outService) de una máquina por su ID."""
    return call_kioskera("GET", "/api/machine/status/get", params={"id": machine_id})


# --- 2. PRODUCTOS Y EJECUCIÓN ---

@mcp.tool()
def productos_maquina(machine_id: int) -> dict | list:
    """Obtiene los programas y servicios configurados para una máquina concreta."""
    return call_kioskera("GET", "/api/products/machine/get", params={"id": machine_id})


@mcp.tool()
def ejecutar_accion_maquina(product_id: int, machine_id: int, cloud: int = 1) -> dict | list:
    """Activa o ejecuta un producto/servicio en la lavadora o secadora objetivo."""
    payload = {"product_id": product_id, "machine_id": machine_id, "cloud": cloud}
    return call_kioskera("POST", "/api/products/execute/postAction", json=payload)


# --- 3. FACTURACIÓN ---

@mcp.tool()
def buscar_facturacion(
    machine_id: int, fecha_inicio: str, fecha_fin: str, limit: int = 100, offset: int = 0
) -> dict | list:
    """Busca transacciones y facturación de una máquina entre dos fechas (YYYY-MM-DD o Epoch)."""
    params = {
        "machine_id": machine_id,
        "start_date": normalizar_a_epoch(fecha_inicio),
        "end_date": normalizar_a_epoch(fecha_fin),
        "limit": limit,
        "offset": offset,
    }
    return call_kioskera("GET", "/api/transaction/get", params=params)


# --- 4. GESTIÓN DE TARJETAS / MONEDERO ---

@mcp.tool()
def crear_tarjeta(
    number_id: str, balance: int, begin_date: str = "0", end_date: str = "0"
) -> dict | list:
    """Crea una tarjeta prepago nueva con saldo inicial en céntimos. Usa '0' en fechas para sin caducidad."""
    payload = {
        "number_id": number_id,
        "balance": balance,
        "begin_date": normalizar_a_epoch(begin_date),
        "end_date": normalizar_a_epoch(end_date),
    }
    return call_kioskera("POST", "/api/card/insertcard", json=payload)


@mcp.tool()
def obtener_info_tarjeta(number_id: str) -> dict | list:
    """Obtiene el estado, saldo y detalles de una única tarjeta prepago por su number_id."""
    return call_kioskera("GET", "/api/card/getcard", params={"number_id": number_id})


@mcp.tool()
def listar_tarjetas(
    limit: int = 10, begin_date: str = "0", end_date: str = "0"
) -> dict | list:
    """Lista de manera paginada las tarjetas prepago registradas en la empresa."""
    params = {
        "limit": limit,
        "begin_date": normalizar_a_epoch(begin_date),
        "end_date": normalizar_a_epoch(end_date),
    }
    return call_kioskera("GET", "/api/card/getcards", params=params)


@mcp.tool()
def eliminar_tarjeta(number_id: str) -> dict | list:
    """Elimina permanentemente una tarjeta prepago dada su identificación."""
    return call_kioskera("DELETE", f"/api/card/delete/{number_id}")


# ==============================================================================
# PUNTO DE ENTRADA (Modo SSE nativo)
# ==============================================================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    mcp.run(transport="sse", host="0.0.0.0", port=port)
