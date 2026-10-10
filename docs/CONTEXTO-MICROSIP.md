# Contexto Microsip / Firebird (DTODO NUEVA UNIFICADA)

Extraído de `DavidVegaF/TRASPASOS-APP` → `firebird-central/` (servicio Node.js que hoy centraliza
el acceso a Firebird). Sirve de base para el MCP que conectará Microsip con Claude.

## 1. Infraestructura

| Dato | Valor |
|---|---|
| Motor | Firebird 3+ (`SEC$USERS`, IDENTITY, `UPDATE OR INSERT`, BOOLEAN `TRUE/FALSE`) |
| Base | `C:\Microsip datos unificada\DTODO NUEVA UNIFICADA.FDB` (empresa unificada) |
| Host / puerto Firebird | `localhost:3050` (en el servidor de producción `SERVIDOR-DTODO`) |
| Usuario servicio | `SYSDBA` (password solo en `.env`, nunca en git) |
| Driver | `node-firebird` **1.1.10** (fijo), `wireCrypt: 'disabled'`, `lowercase_keys:false` |
| Servicio central actual | `firebird-central`, puerto **4790**, expuesto en `https://central.latienditarosa.mx` (Cloudflare Tunnel) |
| Servicios Windows (NSSM) | `DVF MicrosipAPI` (4785), `DVF PedidosDTODO` (42000), `DVF SuiteDTODO` (5445), `DVF Checador`, `AgenteServidorDatosMicrosip`, `MicrosipGuardianServicios`, `Microsip SiCS - Agente de sincronización matriz` |
| Imágenes de producto | `C:\IMAGENES\1 Imagen principal\<SKU>.(jpg|jpeg|png|webp|bmp|gif)` |

> Firebird corre en la red del negocio. Para que Claude lo alcance con "solo un link" el MCP debe ser
> **remoto (Streamable HTTP/SSE)** y publicado por túnel (Cloudflare Tunnel, igual que `central.*`).

## 2. Lecciones de producción (reutilizar tal cual)

- **Pool único** (LIFO, min 5 / max 40) con watchdog: conexión atorada >40 min se cierra, libres idle >10 min se cierran, vida máx 60 min. Verificar con `SELECT 1 FROM RDB$DATABASE` antes de reusar.
- **Timeout 15 s por query** y `detach(force=true)` al vencer (un `detach()` normal es no-op si hay queries pendientes). Tras timeout la conexión se **descarta**, no se devuelve al pool.
- **`uncaughtException`** del driver (bug `readUInt16LE`): `process.exit(1)` y dejar que NSSM reinicie.
- **Lecturas sin bloqueo**: transacción `READ COMMITTED + REC_VERSION (isolation [15,17]) + readOnly + wait:false`. Así una sesión atorada de Microsip Desktop nunca tumba una consulta.
- Escrituras: `WAIT` con `waitTimeout` 10 s.
- Shutdown limpio (SIGTERM/SIGINT) drenando el pool.
- Auth de 2 niveles: `X-API-Key` por app cliente (+ límite de concurrencia por cliente, 8) y login real contra Firebird (si el `attach` con usuario/contraseña conecta, es válido).
- Caché del catálogo en RAM (refresh 10 min) porque `exival_art` x10 almacenes por artículo es caro.

## 3. IDs de almacén (hardcodeados en producción)

| ALMACEN_ID | Alias en el código |
|---|---|
| 397456 | M90 |
| 441735 | M128 |
| 1048428 | M179 |
| 458781 | WEB / CAJAS ABIERTAS |
| 536234 | BODEGA E |
| 2698112 | MAYOREO |
| 6395300 | CAJAS CERRADAS |
| 6371646 | CONTENEDOR |

Excluidos de listados: `441734, 640698` (ocultos), `445051` FRANQUICIA, `4374363` FACTURACION WEB,
`5907421` MARKETING, `457364`. Sucursales excluidas: `640697, 441876`.
Constantes de precio usadas en `PRECIOS_ART(...)`: `(articulo_id,'S',42,0,0,0,0,284)`.
Rol de clave principal en `CLAVES_ARTICULOS`: `ROL_CLAVE_ART_ID = 17`.

## 4. Tablas Microsip usadas (estructura inferida de las queries)

**Catálogo**
- `ARTICULOS` — `ARTICULO_ID, NOMBRE, ESTATUS('A'), ES_JUEGO('S'/'N'), UNIDAD_VENTA, CONTENIDO_UNIDAD_COMPRA, LINEA_ARTICULO_ID`
- `CLAVES_ARTICULOS` — `CLAVE_ARTICULO_ID, ARTICULO_ID, CLAVE_ARTICULO, ROL_CLAVE_ART_ID` (17 = principal; otros roles = claves alternas / códigos de barras)
- `JUEGOS_DET` — kits/paquetes: `ARTICULO_ID` (paquete), `COMPONENTE_ID` (pieza), `UNIDADES`, `CLAVE_ARTICULO_ID`
- `LINEAS_ARTICULOS` (`LINEA_ARTICULO_ID, NOMBRE, GRUPO_LINEA_ID`) → `GRUPOS_LINEAS` (`GRUPO_LINEA_ID, NOMBRE` = categoría)
- `ALMACENES` — `ALMACEN_ID, NOMBRE, NOMBRE_ABREV, OCULTO('N')`
- `SUCURSALES` — `SUCURSAL_ID, NOMBRE`; `SUCURSALES_CATALOGOS` (`NOM_TABLA='ALMACENES'`) + `SUCURSALES_CATALOGOS_DET` (`ELEMENTO_ID` = almacén) mapea almacén→sucursal
- `COMPROM_ARTICULOS` — `ARTICULO_ID, ALMACEN_ID, UNIDADES_COMPROM` (stock comprometido)

**Traspasos**
- `TRASPASOS_IN` — `TRASPASO_IN_ID, FOLIO(CHAR 9, unique), FECHA, FECHA_ENTREGA, SUCURSAL_ORIGEN_ID, ALMACEN_ORIGEN_ID, SUCURSAL_DESTINO_ID, ALMACEN_DESTINO_ID, DESCRIPCION, ESTATUS, APLICADO(bool), FORMA_EMITIDA, USUARIO_CREADOR, FECHA_HORA_CREACION, USUARIO_ULT_MODIF, FECHA_HORA_ULT_MODIF, USUARIO_CANCELACION`
  - ESTATUS: `P` pendiente, `E` enviado, `R` recibido, `C` cancelado, `V` verificado (pendiente de implementar)
- `TRASPASOS_IN_DET` — `TRASPASO_IN_DET_ID, TRASPASO_IN_ID, CLAVE_ARTICULO, ARTICULO_ID, UNIDADES, POSICION`
- `FOLIOS_VENTAS` — `FOLIO_VENTAS_ID, SISTEMA('IN'), TIPO_DOCTO('t'), SUCURSAL_ID, SERIE, CONSECUTIVO`; folio = SERIE + consecutivo con ceros hasta 9 chars
- Generador de IDs: `GEN_ID(ID_DOCTOS, 1)`

**Seguridad**: `SEC$USERS` (`SEC$USER_NAME`, `SEC$ADMIN`).

**Tabla propia (no es de Microsip)** — `CTI_TRASPASOS_NEGADOS`: `NEGADO_ID` (identity), `TRASPASO_IN_ID, FOLIO, ALMACEN_ORIGEN, ALMACEN_DESTINO, ARTICULO_ID, SKU, NOMBRE, PIEZAS_PEDIDAS, PIEZAS_SURTIDAS, PIEZAS_NEGADAS, OPERADOR, AUTORIZO, FECHA_HORA, FECHA_REGISTRO`; único `(TRASPASO_IN_ID, ARTICULO_ID)`. Prefijo `CTI_` = objetos propios.

## 5. Procedimientos / funciones de Firebird usados

| Objeto | Uso |
|---|---|
| `EXIVAL_ART(articulo_id, almacen_id, CURRENT_DATE, 'S', 0)` → `EXISTENCIA` | Existencia por almacén |
| `PRECIOS_ART(articulo_id,'S',42,0,0,0,0,284)` → `PRECIO1..PRECIO5` | Listas de precio (5) |
| `CALC_DISP_ARTALM(articulo_id, almacen_id, 0)` → `EXIS_DISP` | Disponible = existencia − comprometido |
| `CTI_CALC_DISP_ARTALM_SEL(articulo_id, almacen_id, 0)` → `EXIS_DISP` | Versión propia (SELECT) para el catálogo |
| Triggers `AFTUPD_0 → APLICA_TRASPASO_IN → AFECTA_UNID_COMPROM` | Al pasar `APLICADO=TRUE` se compromete stock |

## 6. Consultas de referencia (lectura)

```sql
-- Producto por clave (cualquier rol de clave) con existencias
SELECT art.nombre, principal.clave_articulo, pp.precio1,
       (SELECT EXISTENCIA FROM exival_art(art.articulo_id, 397456, CURRENT_DATE,'S',0)) AS EXISTENCIA_M90
FROM articulos art
JOIN claves_articulos ca ON ca.articulo_id = art.articulo_id
LEFT JOIN claves_articulos principal ON principal.articulo_id = art.articulo_id AND principal.rol_clave_art_id = 17
LEFT JOIN precios_art(art.articulo_id,'S',42,0,0,0,0,284) pp ON 1=1
WHERE art.estatus='A' AND art.es_juego='N' AND ca.clave_articulo = ?;

-- Catálogo con categoría/línea
SELECT ca.CLAVE_ARTICULO, art.NOMBRE, gl.NOMBRE AS CATEGORIA, la.NOMBRE AS LINEA, pp.PRECIO1
FROM ARTICULOS art
LEFT JOIN CLAVES_ARTICULOS ca ON ca.ARTICULO_ID=art.ARTICULO_ID AND ca.ROL_CLAVE_ART_ID=17
LEFT JOIN PRECIOS_ART(art.ARTICULO_ID,'S',42,0,0,0,0,284) pp ON 1=1
LEFT JOIN LINEAS_ARTICULOS la ON art.LINEA_ARTICULO_ID=la.LINEA_ARTICULO_ID
LEFT JOIN GRUPOS_LINEAS gl ON la.GRUPO_LINEA_ID=gl.GRUPO_LINEA_ID
WHERE TRIM(art.ESTATUS)='A' AND TRIM(art.ES_JUEGO)='N';

-- Historial de traspasos
SELECT t.TRASPASO_IN_ID, t.FOLIO, t.FECHA, t.ESTATUS, t.APLICADO, ao.NOMBRE ORIGEN, ad.NOMBRE DESTINO
FROM TRASPASOS_IN t
JOIN ALMACENES ao ON t.ALMACEN_ORIGEN_ID=ao.ALMACEN_ID
JOIN ALMACENES ad ON t.ALMACEN_DESTINO_ID=ad.ALMACEN_ID
ORDER BY t.TRASPASO_IN_ID DESC;

-- Metadatos (para que el MCP descubra el esquema real)
SELECT TRIM(RDB$RELATION_NAME) FROM RDB$RELATIONS WHERE RDB$SYSTEM_FLAG=0 AND RDB$VIEW_BLR IS NULL;
SELECT TRIM(RDB$FIELD_NAME), RDB$FIELD_TYPE FROM RDB$RELATION_FIELDS WHERE RDB$RELATION_NAME = ?;
```

## 7. Reglas de negocio de traspasos (solo si algún día se habilita escritura)

- Creación en **2 fases**: (1) INSERT `TRASPASOS_IN`+`_DET` con `APLICADO=FALSE` y COMMIT; (2) `UPDATE ... SET APLICADO=TRUE` (dispara el compromiso de stock; puede fallar por lock de Microsip Desktop → queda pendiente).
- Mutex por almacén origen para no sobre-comprometer stock.
- Ruta especial: CAJAS CERRADAS (6395300) → WEB (458781) → DESTINO (dos traspasos).
- Surtido parcial permitido; solo se rechaza si nada tiene disponible.
- Enviar requiere verificación de un 2º usuario; cancelar solo si `ESTATUS='P'`; recibir solo si `ESTATUS='E'`. "Editar" = cancelar + crear nuevo.
- Operaciones que auditan usuario (enviar/cancelar/recibir) se ejecutan con **credenciales reales del operador** (`queryAsUser`, rol `USUARIO_MICROSIP`) para que Microsip registre al usuario y no a SYSDBA.

## 8. Endpoints del servicio actual (referencia de herramientas MCP)

`GET /producto/:clave`, `/juego/:clave`, `/articulo/:clave/:almacenId`, `/almacenes`, `/sucursales`,
`/precio/:sku`, `/imagen/:sku`, `/health`; `POST /api/auth/login`; `GET /api/articulos` (+`/categorias`,`/status`,`/refresh`);
`GET /api/almacenes`; `/api/pedidos` (POST crear, GET historial, `/:id`, `/:id/status`, `/folio/:folio`, `/disponible/:articuloId/:almacenId`, `/usuarios-firebird`, POST `/:id/enviar|cancelar|recibir`); `/api/negados` (GET, POST, POST `/limpiar`).

## 9. Propuesta de herramientas para el MCP (solo lectura primero)

`buscar_producto(texto|clave)`, `existencias(clave, almacen?)`, `precios(clave)`, `detalle_juego(clave)`,
`listar_almacenes`, `listar_sucursales`, `historial_traspasos(filtros)`, `traspaso_por_folio(folio)`,
`productos_negados(rango)`, `listar_tablas`, `describir_tabla(nombre)`, `consulta_sql(sql)` (solo `SELECT`, validada, con `FIRST n`).
