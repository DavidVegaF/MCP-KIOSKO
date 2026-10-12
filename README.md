# MCP-KIOSKO — analítica Microsip por conector remoto (HTTP)

Un servidor MCP **de solo lectura** que se agrega a Claude pegando **solo un link**. Replica el diseño del MCP
analítico de DTODO (copia nocturna en DuckDB, ver `docs/CONTEXTO-MCP-ANALITICA.md`), pero por **HTTP con token**
en vez de stdio/SSH, y con **una instancia por empresa** (un conector cada una).

| Empresa | Perfil | Estado |
|---|---|---|
| **GRUPO COMERCIAL KORNER** (ruta: camionetas → kioscos) | `ruta` | Servidor, modelo y 16 herramientas listos y probados con datos sintéticos y con el catálogo/remisiones reales del Excel. **Falta validar contra Firebird** (ver "Pendiente"). |
| **DTODO NUEVA UNIFICADA** | `dtodo` | Pendiente: se adapta del código original (`mcp_server.py`, `build.sql`, …). |

## Arquitectura

```
Firebird (BI_READER, solo lectura)           Servidor Windows, 02:00
   └─ etl/extract.py ── Parquet ──scp──►  Mac Mini ── scripts/rebuild.sh ──► analitica.duckdb (reemplazo atómico)
                                              └─ microsip_mcp (HTTP, 127.0.0.1:8101) ◄── Cloudflare Tunnel ◄── Claude
                                                   https://<host>/<TOKEN>/mcp
```

- Una conexión DuckDB de solo lectura **por consulta**, con `enable_external_access=false` (el SQL no lee archivos).
- `sql` solo acepta `SELECT`/`WITH`, una sentencia, palabras peligrosas bloqueadas, tope 2,000 filas (200 visibles).
- El token va en la ruta (`/<TOKEN>/mcp`), se compara en tiempo constante, **no se escribe en logs** (`access_log` apagado).
- El servidor valida el header `Host` (`public_host`) contra DNS rebinding.
- Datos de ayer hacia atrás (fecha de corte = última remisión cargada). Nunca escribe en Microsip.

## Herramientas del perfil `ruta` (16)

`diccionario` · `ventas` · `ranking_camionetas` · `ranking_vendedores` · `productos_ruta` · `devoluciones_ruta` ·
`kiosko_geolocalizar` · `visitas` · `articulo` · `calidad_datos` · `sql` ·
**inventario y compras:** `existencias` · `sugerido_compra` · `sin_movimiento` · `stock_camioneta` · `cambios_ruta`

Reglas de negocio y supuestos: **`docs/DISENO-RUTA.md`**.

## Desarrollo y pruebas

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,etl]"
pytest                      # 52 pruebas: reglas, guardas SQL, herramientas, ETL y HTTP con cliente MCP real
```

## Puesta en marcha (réplica del flujo de DTODO; ejemplo `korner`)

El flujo es el mismo que el del conector de DTODO: **servidor Windows extrae → `scp` a la Mac → rebuild → servicio `launchd` → Cloudflare Tunnel**.

**A. En la Mac** (por SSH): instalar y arrancar el servicio. Crea el venv, el token (`~/.config/microsip-mcp/korner.env`, permisos 600) y el servicio `com.dtodo.mcp.korner`; no toca el de DTODO.
```bash
git clone -b ccr-9055e406-xveuq4 https://github.com/DavidVegaF/MCP-KIOSKO ~/microsip-mcp   # o git pull si ya existe
cd ~/microsip-mcp && scripts/instalar_mac.sh korner      # al final imprime la URL con el token: no la compartas
```
**B. Catálogo de kioscos** (fijo, no sale de Firebird; el Excel NO va al repo). En la Mac:
`.venv/bin/python etl/load_kioscos.py <ruta>/DAVID_RUTAS.xlsx data/korner/static/dim_kiosko.parquet`

**C. Túnel**: agregar el hostname al `config.yml` de cloudflared que ya sirve a DTODO (con respaldo y validación):
```bash
python3 scripts/cloudflared_agregar_host.py ~/.cloudflared/config.yml korner.latienditarosa.mx 8101            # simula
python3 scripts/cloudflared_agregar_host.py ~/.cloudflared/config.yml korner.latienditarosa.mx 8101 --aplicar
cloudflared tunnel route dns <ID-del-tunel> korner.latienditarosa.mx
# reiniciar cloudflared (según cómo se arrancó: brew services restart cloudflared, o launchctl)
```
**D. Servidor Windows** (Python 3.11+): `pip install firebirdsql pyarrow`; clonar el repo; copiar `etl\etl.example.ini` → `etl\etl.ini`
con `host = localhost`, la ruta del `.FDB` de Korner y `BI_READER`; copiar `scripts\run_etl.example.cmd` → `scripts\run_etl.cmd` y
poner el mismo `usuario@dirección` de la Mac que usa el `run.cmd` de DTODO. Probar a mano y registrar la tarea (02:30, para no empalmarse con DTODO):
```powershell
$c = Get-Credential
$a = New-ScheduledTaskAction -Execute "C:\ruta\MCP-KIOSKO\scripts\run_etl.cmd"
$t = New-ScheduledTaskTrigger -Daily -At 02:30
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName KornerETL -Action $a -Trigger $t -Settings $s -User $c.UserName -Password $c.GetNetworkCredential().Password
```
**E. Claude**: Ajustes → Conectores → *Agregar conector personalizado* → `https://korner.latienditarosa.mx/<TOKEN>/mcp`.

Para descubrir el esquema real antes de extraer: `python etl/discover_firebird.py --ini etl/etl.ini` (donde llegue a Firebird).

## Pendiente (honesto)

- **No probado contra Firebird real**: `etl/korner/queries/*.sql` usan nombres de columna conocidos (ARTICULOS, ALMACENES,
  CLAVES_ARTICULOS…) y otros por confirmar (`DOCTOS_VE.ORDEN_COMPRA`, `HORA`, `VENDEDOR_ID`, `DOCTOS_IN.CANCELADO`…).
  `etl/discover_firebird.py` existe para confirmarlos antes de extraer. El driver `firebirdsql` (el mismo que usa `grupo-korner` en la Mac) tampoco se probó contra el servidor desde aquí.
- launchd, tarea de Windows y cambios al túnel: plantillas sin probar en tu equipo.
- Importes **sin IVA** (el original reportaba con IVA); con IVA llega cuando se extraiga `IMPUESTOS_DOCTOS_VE_DET`.
- Herramientas del original (`abc`, `sin_movimiento`, `recomendacion_*`, `master`, `clasificadores`) y el perfil `dtodo`:
  se portan cuando esté el código original.
- La Mac Mini estaba **offline** (FileVault espera contraseña tras un reinicio) al escribir esto.
