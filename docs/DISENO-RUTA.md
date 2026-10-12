# Diseño del conector RUTA (GRUPO COMERCIAL KORNER)

## Negocio
Vendedores **en ruta** venden desde **camionetas** (cada camioneta es un almacén de Microsip) a **kioscos/tiendas**.
El **almacén general** surte a las camionetas con traspasos. El canal de venta son **únicamente las camionetas**.

## Reglas implementadas (`sql/korner/build.sql`)
| Tema | Regla |
|---|---|
| Venta | Solo **remisiones (DOCTOS_VE tipo R)**; las facturas no se cuentan. Se excluyen los estatus de `reglas.estatus_excluidos` (por defecto `C`). Importe = `PRECIO_TOTAL_NETO` (**sin IVA**). |
| Camioneta | `DOCTOS_VE.ALMACEN_ID` de la remisión (ej. "Camioneta 4"). |
| Vendedor | `DOCTOS_VE.VENDEDOR_ID`. Una camioneta la usan varios vendedores y un vendedor varias camionetas (en la muestra real: un mismo vendedor aparece en 2 camionetas y una camioneta tiene 2 vendedores) → se analizan por separado. |
| Kiosko | Texto de `ORDEN_COMPRA` **antes del primer guion** (`14109-1-3-2236` → `14109`). Es el **ID NUEVO** (5 dígitos) o el **ID VIEJO** (4–5); se cruza contra el catálogo del Excel y gana el ID NUEVO. En la muestra de 727 remisiones: 126 vienen con ID nuevo, 601 con viejo, **100 % resuelven**. |
| Visita | Una remisión = una visita (`fact_visita`). |
| Devolución | `DOCTOS_IN` con `CONCEPTO_IN_ID = 7972` (devolución del kiosko a la camioneta, `reglas.conceptos_devolucion`), no cancelada. |
| Vendedor de una devolución | La devolución no trae vendedor: se usa el que **más vendió ese día en esa camioneta**; si no hubo venta ese día → `SIN VENDEDOR (ese dia)`. |
| Coordenadas | Del Excel (`Latitud`/`Longitud`). `0,0` (cafetería 17005) = desconocida. |

## Calidad detectada en el Excel (no es error del código)
- `ID VIEJO` **54059 repetido** (lo comparten dos tiendas distintas): al ser ambiguo **no se usa para cruzar**; esas remisiones saldrían como `SIN KIOSKO (54059)` (herramienta `calidad_datos`) salvo que traigan el ID nuevo.
- 6 filas sin zona (5 "Punto Fiesta" y 1 "Café") — no afecta el cruce.
- La hoja `Hoja5` es una muestra de **remisiones pendientes** (727, abril–mayo); en Microsip habrá más estatus.

## Supuestos a confirmar (con `etl/discover_firebird.py`)
1. Nombre real de las columnas: `DOCTOS_VE.ORDEN_COMPRA`, `HORA`, `VENDEDOR_ID`; `DOCTOS_IN.CANCELADO`, `DESCRIPCION`.
2. Qué estatus de remisión hay (en pantalla aparece "Pendiente") y cuáles no deben contar (`estatus_excluidos`).
3. Si las remisiones facturadas después siguen contando (aquí **sí**, porque las facturas no se cuentan y no hay doble conteo).
4. Qué significa el 2.º segmento de la orden de compra (`1`/`2`; se guarda como `oc_seg2`) y el 3.º (siempre `3`).
5. Si la `DESCRIPCION` de la devolución trae el kiosko (permitiría `devoluciones por kiosko`).
6. Cambios: si un cambio genera salida+entrada con otro concepto, hoy no se cuenta (solo 7972).

## Fuera de alcance por ahora
Importes con IVA, costos/márgenes, traspasos almacén general → camionetas, ABC/inventario/compras (se portan del original).
