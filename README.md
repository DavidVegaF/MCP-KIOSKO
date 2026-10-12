# MCP-KIOSKO — analítica Microsip por conector remoto (HTTP)

Un servidor MCP **de solo lectura** que se agrega a Claude pegando **solo un link**. Replica el diseño del MCP
analítico de DTODO (copia nocturna en DuckDB, ver `docs/CONTEXTO-MCP-ANALITICA.md`), pero por **HTTP con token**
en vez de stdio/SSH, y con **una instancia por empresa** (un conector cada una).

| Empresa | Perfil | Estado |
|---|---|---|
| **GRUPO COMERCIAL KORNER** (ruta: camionetas → kioscos) | `ruta` | Servidor, modelo y 11 herramientas listos y probados con datos sintéticos y con el catálogo/remisiones reales del Excel. **Falta validar contra Firebird** (ver "Pendiente"). |
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

## Herramientas del perfil `ruta` (11)

`diccionario` · `ventas` · `ranking_camionetas` · `ranking_vendedores` · `productos_ruta` · `devoluciones_ruta` ·
`kiosko_geolocalizar` · `visitas` · `articulo` · `calidad_datos` · `sql`

Reglas de negocio y supuestos: **`docs/DISENO-RUTA.md`**.

## Desarrollo y pruebas

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,etl]"
pytest                      # 37 pruebas: reglas, guardas SQL, herramientas, ETL y HTTP con cliente MCP real
```

## Puesta en marcha (por empresa; ejemplo `korner`)

1. **Catálogo de kioscos** (el Excel NO va al repo; es público):
   `python etl/load_kioscos.py DAVID_RUTAS.xlsx data/korner/parquet/dim_kiosko.parquet`
2. **Descubrir el esquema real** en el servidor Windows y confirmar nombres de columna:
   `python etl/discover_firebird.py --ini etl/etl.ini > discover_report.txt` (copiar `etl/etl.example.ini` → `etl/etl.ini`).
3. **Extraer y copiar**: `scripts/run_etl.example.cmd` (tarea programada 02:00) → Parquet → Mac.
4. **Configurar** `empresas/korner.toml` (desde `.example.toml`) y el token en la Mac:
   ```bash
   mkdir -p ~/.config/microsip-mcp
   echo "export MCP_TOKEN_KORNER=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')" > ~/.config/microsip-mcp/korner.env
   chmod 600 ~/.config/microsip-mcp/korner.env
   ```
5. **Arrancar** con `scripts/run_mcp.sh korner` (o launchd: `scripts/launchd/`).
6. **Publicar con el Cloudflare Tunnel que ya existe en la Mac** (el mismo que sirve `microsip.latienditarosa.mx` → `localhost:8899`).
   Se agrega un hostname más en `~/.cloudflared/config.yml`, **antes** de la regla final `http_status:404`:
   ```yaml
   ingress:
     - hostname: microsip.latienditarosa.mx
       service: http://localhost:8899
     - hostname: korner.latienditarosa.mx      # nuevo conector
       service: http://localhost:8101
     - service: http_status:404
   ```
   Luego `cloudflared tunnel route dns <ID-del-tunel> korner.latienditarosa.mx` y reiniciar cloudflared
   (haz respaldo de `config.yml` antes: un error aquí tumba también el conector de DTODO).
7. **Conector en Claude**: Ajustes → Conectores → *Agregar conector personalizado* → URL
   `https://korner.latienditarosa.mx/<TOKEN>/mcp`.

## Pendiente (honesto)

- **No probado contra Firebird real**: `etl/korner/queries/*.sql` usan nombres de columna conocidos (ARTICULOS, ALMACENES,
  CLAVES_ARTICULOS…) y otros por confirmar (`DOCTOS_VE.ORDEN_COMPRA`, `HORA`, `VENDEDOR_ID`, `DOCTOS_IN.CANCELADO`…).
  `etl/discover_firebird.py` existe para confirmarlos antes de extraer. El driver `firebirdsql` (el mismo que usa `grupo-korner` en la Mac) tampoco se probó contra el servidor desde aquí.
- launchd, tarea de Windows y cambios al túnel: plantillas sin probar en tu equipo.
- Importes **sin IVA** (el original reportaba con IVA); con IVA llega cuando se extraiga `IMPUESTOS_DOCTOS_VE_DET`.
- Herramientas del original (`abc`, `sin_movimiento`, `recomendacion_*`, `master`, `clasificadores`) y el perfil `dtodo`:
  se portan cuando esté el código original.
- La Mac Mini estaba **offline** (FileVault espera contraseña tras un reinicio) al escribir esto.
