# Value Investing TFG — Guía de referencia

Sistema de análisis fundamental automatizado sobre el S&P 500 aplicando criterios de *value investing*. Este README es la referencia completa para levantar el proyecto desde cero, ejecutar las herramientas y retomar el trabajo después de un tiempo.

---

## Índice

1. [Requisitos previos](#1-requisitos-previos)
2. [Levantar el proyecto desde cero](#2-levantar-el-proyecto-desde-cero)
3. [Activar el entorno de trabajo](#3-activar-el-entorno-de-trabajo)
4. [Configuración inicial](#4-configuración-inicial)
5. [Verificar que todo funciona](#5-verificar-que-todo-funciona)
6. [Tests](#6-tests)
7. [Linting con ruff](#7-linting-con-ruff)
8. [Ejecutar el pipeline](#8-ejecutar-el-pipeline)
9. [Estructura del proyecto](#9-estructura-del-proyecto)
10. [Referencia rápida de comandos](#10-referencia-rápida-de-comandos)
11. [Solución de problemas frecuentes](#11-solución-de-problemas-frecuentes)

---

## 1. Requisitos previos

Antes de empezar, necesitas tener instalado:

- **Python 3.11 o superior.** Compruébalo con:
  ```bash
  python --version
  # debe devolver Python 3.11.x o superior
  ```
- **Git.**
- **Conexión a internet** para la descarga inicial de datos (SEC EDGAR y yfinance).
- **Un correo de contacto** para identificar las peticiones a la SEC (no es una clave, solo un identificador que la SEC exige; se configura en el paso 4).

No se necesita ninguna base de datos ni clave de API de pago.

---

## 2. Levantar el proyecto desde cero

Ejecuta estos pasos en orden. Solo hay que hacerlos una vez.

### 2.1 Clonar el repositorio

```bash
git clone https://github.com/jiahu04/tfg-value-investing.git
cd tfg-value-investing
```

### 2.2 Crear el entorno virtual

El entorno virtual aísla las dependencias del proyecto del resto de Python instalado en el sistema.

```bash
python -m venv .venv
```

Esto crea la carpeta `.venv/` en la raíz del proyecto. Está en `.gitignore` y nunca se sube al repositorio.

### 2.3 Activar el entorno virtual

**Windows:**
```bash
.venv\Scripts\activate
```

**macOS / Linux:**
```bash
source .venv/bin/activate
```

Sabrás que está activo porque el prompt del terminal cambia y muestra `(.venv)` al principio.

> **Importante:** el entorno virtual hay que activarlo cada vez que abras una terminal nueva. Si los comandos de Python o pytest no funcionan, lo primero que hay que comprobar es que el entorno está activo.

### 2.4 Instalar las dependencias

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Esto instala todas las librerías del proyecto (`pandas`, `numpy`, `yfinance`, `pytest`, `ruff`, etc.) dentro del entorno virtual, sin afectar al Python del sistema.

### 2.5 Editar la configuración inicial

Abre `config/config.yaml` y cambia el correo de contacto de la SEC:

```yaml
sec:
  contact_email: "tu@correo.com"   
```

### 2.6 Verificar que todo está bien

```bash
python scripts/verify_imports.py
```

Si termina con `[OK] Todo correcto. El entorno está listo.` ya puedes trabajar.

---

## 3. Activar el entorno de trabajo

Cada vez que retomes el proyecto en una terminal nueva:

```bash
# Desde la raíz del proyecto
.venv\Scripts\activate    # Windows
source .venv/bin/activate # macOS / Linux
```

Para desactivarlo cuando termines:
```bash
deactivate
```

---

## 4. Configuración inicial

Todos los parámetros del sistema están en **`config/config.yaml`**. Es el único sitio donde hay que tocar números: umbrales de filtros, parámetros del DCF, ventana del backtest, etc.

El único cambio obligatorio antes de ejecutar el pipeline es el correo de la SEC (paso 2.5). El resto de valores son los defaults del TFG y reproducen los resultados de la memoria sin modificaciones.

Para cambiar un parámetro y probar un escenario alternativo, edita el valor en `config.yaml` y vuelve a ejecutar. No hay que tocar el código.

**Todos los umbrales están documentados *in situ*** (comentarios junto a cada valor en `config.yaml`); no se
repiten aquí para evitar que diverjan. Secciones principales:

| Sección | Qué controla |
|---|---|
| `sec` | SEC EDGAR: correo de contacto, rate-limit, reintentos y **conceptos XBRL** a extraer |
| `universe` / `constituents` / `sectors` | universo histórico del S&P, ventana, mapa SIC→sector |
| `prices` | tickers de índice (`^SP500TR`) y tipo libre (`^IRX`) |
| `fundamentals` | capa point-in-time: anclaje anual, `concept_map`, normalización de acciones |
| `filters` | Etapa 2: sectores excluidos, deuda, dilución, rentabilidad, calidad contable |
| `quality` | Etapa 3: F-Score y puntuación de calidad |
| `valuation` | Etapa 4: DCF (WACC/CAPM, crecimiento), Graham, múltiplos, integración |
| `portfolio` | Etapa 5: margen mínimo, tope de posiciones, pesos de priorización |
| `backtest` | cadencia, costes, calibración/validación, **barrido de sensibilidad** |
| `contributions` | estrategias de aportación (DCA, condicional, concentrada) |
| `outputs` | carpetas de tablas/figuras y formato de figura |

---

## 5. Verificar que todo funciona

### Verificar importaciones (entorno)

```bash
python scripts/verify_imports.py
```

Comprueba que todas las librerías se importan correctamente y que `config.yaml` se lee sin errores. Útil después de reinstalar el entorno o actualizar dependencias.

### Verificar el config loader

```bash
python -c "from src.utils.config_loader import get_config; print(get_config('portfolio.max_positions'))"
```

Debe imprimir `15` (o el valor que tengas en el config). Si imprime un número, el sistema de configuración funciona.

---

## 6. Tests

### Ejecutar todos los tests

```bash
pytest
```

pytest busca automáticamente en `tests/` (configurado en `pyproject.toml`).

### Opciones útiles

```bash
# Ver el nombre de cada test mientras corre (recomendado)
pytest -v

# Solo un fichero concreto
pytest tests/unit/test_config_loader.py

# Solo un fichero, con salida detallada
pytest tests/unit/test_config_loader.py -v

# Solo los tests unitarios
pytest tests/unit/

# Solo los tests de integración
pytest tests/integration/
```

### Cobertura de pruebas (lógica crítica)

La suite (**197 tests**) corre **sin red real** (datos sintéticos o *mocks*) y deja en verde, sobre todo, la
lógica metodológicamente crítica:

| Lógica crítica | Tests |
|---|---|
| **Anti-look-ahead** (en D solo datos con `filed ≤ D` y precios ≤ D) | `test_backtest_antilookahead.py`, `test_metrics.py`, `test_point_in_time.py` |
| **Universo point-in-time** (`members_on`, mitiga supervivencia) | `test_constituents.py` |
| **Reexpresiones y conservación de `filed`** | `test_sec_facts.py` |
| **Base de valoración** (deshacer splits, escala de acciones, margen) | `test_prices.py`, `test_metrics.py`, `test_valuation.py`, `test_backtest_engine.py` |
| **Motor de backtest** (altas/bajas, convergencia, costes) | `test_backtest_engine.py` |
| **Métricas** (CAGR, alpha/beta, Sharpe, drawdown) con valores de referencia | `test_backtest_metrics.py` |
| **Robustez de red** (reintentos ante 429/503 y cortes de conexión) | `test_http_client.py` |
| **Sensibilidad y `config_override`** | `test_sensitivity.py`, `test_config_override.py` |
| **Equivalencia de la optimización** (camino rápido == naive) | `test_valuation.py`, `test_filters.py` |
| **Aportación** (TIR/MWR, las 3 estrategias se diferencian) | `test_contributions_strategies.py`, `test_contributions_run.py` |

Regla del proyecto: **en los tests no se hace red**; la lógica pura (parseo, métricas, valoración) está
separada de la descarga para poder probarla con datos sintéticos.

---

## 7. Linting con ruff

`ruff` analiza el código en busca de errores, malas prácticas y problemas de estilo.

### Comprobar el código

```bash
# Analizar todo el proyecto
ruff check .

# Analizar solo el código fuente (ignorando tests y scripts)
ruff check src/

# Analizar un fichero concreto
ruff check src/utils/config_loader.py
```

Si no hay problemas, ruff no imprime nada y devuelve al prompt. Si encuentra algo:
```
src/utils/config_loader.py:17:8: F401 [*] `os` imported but unused
```
El formato es `fichero:línea:columna: código mensaje`. El `[*]` indica que ruff puede corregirlo automáticamente.

### Corregir automáticamente

```bash
# Corregir todo lo que ruff pueda corregir solo (imports sin usar, orden de imports, etc.)
ruff check --fix .

# Ver qué corregiría sin aplicarlo todavía
ruff check --diff .
```

### Cuándo ejecutar ruff

Antes de cada commit. Si ruff encuentra errores, el código no está listo para subir.

### Códigos de error frecuentes

| Código | Significado | Solución |
|---|---|---|
| `F401` | Import sin usar | Borrar la línea de import |
| `F841` | Variable asignada pero nunca usada | Borrar o usar la variable |
| `E501` | Línea demasiado larga | Ignorado en este proyecto (configurado en `pyproject.toml`) |
| `I001` | Imports desordenados | `ruff check --fix` lo corrige solo |
| `B006` | Mutable default en función | Cambiar `def f(x=[])` por `def f(x=None)` |

---

## 8. Ejecutar el pipeline

### Ingesta de datos (Etapa 1)

Descarga y cachea en local todos los datos: fundamentales de la SEC (conservando la fecha de publicación), precios de acciones, índice y tipo libre de riesgo, composición histórica del índice y sector por código SIC.

```bash
# Ingesta completa (primera vez): SEC + yfinance + constituyentes
python -m src.ingest.run_ingest --step all

# Prueba rápida acotada a N empresas (recomendado para validar el entorno)
python -m src.ingest.run_ingest --step all --limit 3

# Ejecutar solo un paso concreto
python -m src.ingest.run_ingest --step tickers        # mapa ticker<->CIK
python -m src.ingest.run_ingest --step constituents   # composición histórica
python -m src.ingest.run_ingest --step sectors        # SIC -> sector
python -m src.ingest.run_ingest --step fundamentals   # companyfacts (con `filed`)
python -m src.ingest.run_ingest --step prices         # precios, índice y tipo libre

# Forzar re-descarga aunque exista el crudo en data/raw
python -m src.ingest.run_ingest --step all --force
```

La ingesta es **reejecutable**: el crudo se guarda en `data/raw` y la caché se reconstruye desde ahí sin volver a descargar (salvo `--force`). Layout generado:

```
data/raw/sec/company_tickers.json          # mapa ticker -> CIK
data/raw/sec/companyfacts/CIK##########.json
data/raw/sec/submissions/CIK##########.json
data/raw/constituents/sp500_historical.csv
data/cache/tickers.parquet
data/cache/constituents.parquet            # date, ticker (point-in-time)
data/cache/sectors.csv                     # ticker, cik, sic, sector
data/cache/fundamentals.parquet            # tidy, con fecha de publicación `filed`
data/cache/prices.parquet                  # precios ajustados de las acciones
data/cache/index_prices.parquet            # ^SP500TR
data/cache/risk_free.parquet               # ^IRX
```

> **Nota (yfinance):** si la descarga de precios falla con `database is locked`, es la caché interna de yfinance; reintenta `--step prices --force`.

### Pipeline de selección (Etapas 1–5, Fase 1 completa)

Una sola orden ejecuta las cinco etapas (datos → filtros → calidad → valoración → margen de seguridad)
sobre una fecha y devuelve la **lista priorizada** point-in-time:

```bash
python -m src.pipeline.run --date 2019-06-01   # lista priorizada a esa fecha
python -m src.pipeline.run                      # fecha por defecto: hoy
python -m src.pipeline.run --date 2019-06-01 --limit 50   # acota el universo (prueba rápida)
```

Imprime el resumen (universo, supervivientes, seleccionadas) y la lista priorizada, y guarda la tabla
completa de candidatos en `outputs/tables/seleccion_<fecha>.csv`. Requiere la caché del paso de ingesta.

### Backtesting (Fase 2)

Simula la estrategia en el pasado sin información futura (revisión anual + vigilancia semanal de ventas
por convergencia, cartera equiponderada con liquidez remunerada y costes). Produce la serie de valor de la
cartera y del índice y el registro de operaciones:

```bash
python -m src.backtest.run                              # ventana por defecto (config)
python -m src.backtest.run --start 2013-01-01 --end 2025-12-31
python -m src.backtest.run --sensitivity                # además, el análisis de sensibilidad
```

Genera, en `outputs/tables/`: la serie de valor (`backtest_equity_curve.csv`), las operaciones
(`backtest_trades.csv`) y la **tabla de métricas** (CAGR, alpha de Jensen, beta, Sharpe, máximo drawdown,
tracking error) por periodo Total / Calibración / Validación (`backtest_metrics.csv` y `.tex`). Con
`--sensitivity` añade la **tabla de sensibilidad** (`backtest_sensitivity.csv` y `.tex`). Requiere la caché
de ingesta (idealmente la **ingesta completa**; con pocas empresas la cartera queda casi siempre en
liquidez).

### Simulación de estrategias de aportación (Fase 2)

Compara tres formas de aportar dinero nuevo a la estrategia value (sección 8.3): **DCA fijo** (aportación
constante), **DCA condicional al valor intrínseco** (la aportación sube al ampliarse el margen de seguridad
y baja o se suspende al estrecharse) y **aportación concentrada** en el máximo descuento. Las aportaciones
entran en un NAV construido a partir de la curva de valor del backtest:

```bash
python -m src.contributions.run                          # ventana por defecto (config)
python -m src.contributions.run --start 2013-01-01 --end 2025-12-31
```

Genera, en `outputs/tables/`, la **tabla comparativa** (`contributions_comparison.csv` y `.tex`) con la
rentabilidad ponderada por el dinero (**TIR/MWR**), el valor final, el total aportado, el número de
aportaciones y el **precio medio de adquisición** por estrategia. Los umbrales viven en
`config/config.yaml` (sección `contributions`). Resultados representativos requieren la **ingesta completa**.

### Gráficas de resultados (Fase 3)

Genera las figuras del capítulo de resultados a partir de los CSV ya producidos (backtest y aportación):
curva de capital cartera vs índice (con el corte calibración/validación), evolución del margen de seguridad
y comparación de estrategias de aportación.

```bash
python -m src.reporting.figures
```

Deja en `outputs/figures/` cada figura en **PDF** (vectorial, para LaTeX) y **PNG** (para verla al vuelo):
`equity_curve`, `margin_evolution`, `contributions`. Lee los CSV de `outputs/tables/`; si falta alguno
(p. ej. no se ha corrido el backtest), avisa y omite esa figura. La evolución del margen requiere
`backtest_reviews.csv`, que produce `src.backtest.run`.

Los resultados (tablas LaTeX y gráficas) quedan en `outputs/`.

### Ver los resultados en tabla (consola)

Para revisar de un vistazo **todos los datos comparativos** (rentabilidad cartera vs índice, métricas por
periodo, comparación de estrategias de aportación, selección y sensibilidad) **sin re-ejecutar** nada:

```bash
python -m src.reporting.report
```

Lee los CSV de `outputs/tables/` y los imprime formateados en segundos. Es el equivalente "en tabla" de
`src.reporting.figures` (lo mismo, pero en imagen). *(Alternativa: abrir los `.csv` de `outputs/tables/` en
Excel o en el Data Wrangler de VSCode.)*

Para forzar una descarga limpia de datos:
```bash
rm -rf data/cache/ data/raw/     # macOS / Linux
rmdir /s data\cache & rmdir /s data\raw   # Windows
python -m src.ingest.run_ingest --step all
```

### Reproducir todos los resultados de principio a fin

Secuencia completa desde cero (los comandos asumen Windows/PowerShell; en macOS/Linux usa el activador
equivalente). `data/` y `outputs/` se regeneran; no se versionan.

```powershell
# 1) Entorno
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# (editar el correo de la SEC en config/config.yaml -> sec.contact_email)

# 2) Ingesta COMPLETA del universo (larga, ~15-40 min). Si se corta, RELANZA el mismo
#    comando: reanuda desde data/raw (no re-descarga lo ya bajado).
python -m src.ingest.run_ingest --step all

# 3) Análisis (lee la caché; escribe en outputs/tables/)
python -m src.pipeline.run --date 2019-06-01      # lista priorizada a una fecha (~36 s)
python -m src.backtest.run                         # backtest 2013-2025 (~6-8 min)
python -m src.contributions.run                    # estrategias de aportación (~6-8 min)
# (opcional) python -m src.backtest.run --sensitivity   # robustez; ~40-50 min (10 backtests)

# 4) Figuras (segundos; lee outputs/tables/, escribe outputs/figures/)
python -m src.reporting.figures
```

**Resultados:** `outputs/tables/` (CSV + `.tex` para LaTeX) y `outputs/figures/` (PDF + PNG).

**Notas operativas importantes:**
- La ingesta es **reanudable**: cada empresa se guarda en `data/raw` justo tras descargarla; ante un corte de
  la SEC, `get_json` reintenta y, si aún así aborta, **relanzar reanuda**.
- Para refrescar **solo los precios** (sin re-bajar fundamentales): borra el parquet y reingesta —
  `Remove-Item data\cache\prices.parquet` + `python -m src.ingest.run_ingest --step prices`. La descarga de
  precios llega **hasta hoy** (no solo hasta `backtest_end`) para capturar splits recientes.
- **No uses `--force` en `--step all`**: re-dispara el descubrimiento de constituyentes en GitHub y
  re-descarga todo.
- Con una **caché parcial** (pocas empresas) los resultados son ilustrativos; los representativos requieren la
  ingesta completa.

---

## 9. Estructura del proyecto

```
tfg-value-investing/
│
├── config/
│   └── config.yaml              ← TODOS los parámetros del sistema (editar aquí)
│
├── src/
│   ├── ingest/                  ← Etapa 1: descarga y caché de datos (SEC + yfinance)
│   │   ├── cache_io.py          ← persistencia local (Parquet/CSV/JSON)
│   │   ├── http_client.py       ← sesión HTTP de la SEC (User-Agent, rate-limit, reintentos)
│   │   ├── sec_tickers.py       ← mapa ticker <-> CIK
│   │   ├── sec_facts.py         ← fundamentales (companyfacts) conservando `filed`
│   │   ├── sec_submissions.py   ← SIC y nombre por empresa
│   │   ├── sectors.py           ← agrupación de códigos SIC en sectores
│   │   ├── prices.py            ← precios, índice y tipo libre de riesgo (yfinance)
│   │   ├── constituents.py      ← composición histórica point-in-time
│   │   └── run_ingest.py        ← orquestador/CLI (--step / --limit / --force)
│   ├── pipeline/                ← Etapas 2–5: filtros, calidad, valoración, selección
│   ├── backtest/                ← Módulo B1: motor de backtesting (2013–2025) + métricas/sensibilidad
│   ├── contributions/           ← Módulo B2: simulación de estrategias de aportación
│   ├── reporting/               ← figuras (figures.py) y exportación de tablas a LaTeX (latex.py)
│   └── utils/
│       └── config_loader.py     ← cargador de config.yaml (con `config_override` para la sensibilidad)
│
├── tests/
│   ├── unit/                    ← tests por módulo (rápidos, sin datos reales)
│   └── integration/             ← end-to-end (anti-look-ahead, pipeline, ingesta, aportación)
│
├── data/                        ← excluido de Git, se regenera con el pipeline
│   ├── raw/                     ← datos crudos de SEC EDGAR y yfinance
│   └── cache/                   ← datos procesados en formato Parquet
│
├── docs/
│   ├── registro_decisiones.md   ← decisiones de diseño con justificación
│   ├── cuestiones_abiertas.md   ← backlog de cuestiones/mejoras (C-001…)
│   ├── notas_memoria.md         ← contenido reutilizable para la memoria del TFG
│   └── dev_notes.md             ← log de sesiones de desarrollo
│
├── scripts/
│   └── verify_imports.py        ← comprueba que el entorno está bien instalado
│
├── outputs/                     ← excluido de Git; tablas (.csv/.tex) y figuras (.pdf/.png)
│   ├── tables/                  ← generadas por el análisis (backtest, aportación, selección)
│   └── figures/                 ← generadas por reporting/figures.py
│
├── .gitignore
├── pyproject.toml               ← configuración de pytest y ruff
└── requirements.txt             ← dependencias del proyecto
```

---

## 10. Referencia rápida de comandos

```bash
# ── Entorno ───────────────────────────────────────────────────────────────────
.venv\Scripts\activate                        # activar (Windows)
source .venv/bin/activate                     # activar (macOS/Linux)
deactivate                                    # desactivar

# ── Dependencias ──────────────────────────────────────────────────────────────
pip install -r requirements.txt               # instalar todo
pip install nombre-paquete                    # añadir una librería
pip freeze > requirements.txt                 # actualizar requirements.txt

# ── Verificación ──────────────────────────────────────────────────────────────
python scripts/verify_imports.py              # verificar entorno completo
python --version                              # comprobar versión de Python

# ── Tests ─────────────────────────────────────────────────────────────────────
pytest                                        # todos los tests
pytest -v                                     # verbose
pytest tests/unit/test_config_loader.py -v   # un fichero concreto
pytest -x                                     # parar al primer fallo
pytest -xvs                                   # parar + verbose + prints

# ── Ruff ──────────────────────────────────────────────────────────────────────
ruff check .                                  # analizar todo
ruff check src/                               # solo el código fuente
ruff check --fix .                            # corregir automáticamente
ruff check --diff .                           # ver qué corregiría sin aplicar

# ── Análisis (resultados) ─────────────────────────────────────────────────────
python -m src.ingest.run_ingest --step all    # ingesta completa (larga; reanudable)
python -m src.ingest.run_ingest --step all --limit 30   # prueba rápida (30 empresas)
python -m src.pipeline.run --date 2019-06-01   # lista priorizada a una fecha
python -m src.backtest.run                     # backtest cartera vs índice + métricas
python -m src.backtest.run --sensitivity       # + análisis de sensibilidad (~40-50 min)
python -m src.contributions.run                # estrategias de aportación (TIR/MWR)
python -m src.reporting.report                 # resumen de TODOS los resultados en tabla (consola)
python -m src.reporting.figures                # figuras (PDF+PNG) en outputs/figures/

```

---

## 11. Solución de problemas frecuentes

**`python` no se reconoce como comando**
En Windows puede que el comando sea `python3` o que Python no esté en el PATH. Comprueba la instalación de Python.

**`pip install` da error en Windows al hacer upgrade de pip**
Es un aviso, no un error. Usa `python -m pip install --upgrade pip` en lugar de `pip install --upgrade pip`.

**`ModuleNotFoundError` al ejecutar tests o código**
El entorno virtual no está activo. Actívalo con `.venv\Scripts\activate` (Windows) o `source .venv/bin/activate` (macOS/Linux).

**`ruff` no se reconoce como comando**
El entorno virtual no está activo, o las dependencias no están instaladas. Activa el entorno y ejecuta `pip install -r requirements.txt`.

**La ingesta se corta con un error de conexión (`ConnectionResetError` / `WinError 10054`)**
La SEC cierra la conexión esporádicamente. `get_json` reintenta; si aun así aborta, **relanza el mismo comando**: reanuda desde `data/raw` (no re-descarga lo ya bajado).

**La ingesta falla en el paso `constituents` (`RuntimeError: No se encontró ningún CSV histórico…`)**
La composición histórica del S&P 500 se descarga del repo público `fja05680/sp500`, mantenido por terceros. Si su responsable **renombra o mueve el CSV**, el descubrimiento automático por patrón deja de encontrarlo (ocurrió en 2026: quitó la fecha del nombre del fichero). Dos formas de arreglarlo a mano:
1. **Fijar la URL directa** (recomendado): entra en `https://github.com/fja05680/sp500`, abre el fichero `S&P 500 Historical Components & Changes … .csv`, pulsa **Raw**, copia la URL y pégala en `config/config.yaml` → `constituents.url`. Relanza `python -m src.ingest.run_ingest --step constituents`.
2. **Descargar el CSV a mano**: guárdalo como `data/raw/constituents/sp500_historical.csv`; la ingesta usa ese crudo si existe, **sin descargar nada** de la red.

El CSV debe tener cabecera `date,tickers` (los tickers separados por comas dentro de una celda). El valor por defecto de `constituents.url` ya apunta al fichero estable actual, así que en condiciones normales no hay que hacer nada.

**Quiero refrescar solo los precios sin re-bajar los fundamentales**
Borra el parquet de precios y reingesta solo ese paso: `Remove-Item data\cache\prices.parquet` y luego `python -m src.ingest.run_ingest --step prices`. **No uses `--force`** en `--step all`/`--step prices`: re-dispara el descubrimiento de la URL de constituyentes en GitHub (puede fallar) y re-descarga todo.

**Una empresa sale con un valor por acción/margen disparado**
Casi siempre es un *split* muy reciente. Los precios se descargan **hasta hoy** para deshacer los splits; el único caso límite es una acción que parte **el mismo día** en que ejecutas (aún sin datos): se auto-corrige al día siguiente.

**El backtest o `pipeline.run` tardan varios minutos**
Es normal sobre el universo completo (~700 empresas): `pipeline.run` a una fecha ~36 s, el backtest ~6-8 min, `--sensitivity` ~40-50 min. Para una prueba rápida, usa una caché parcial (`--limit N` en la ingesta).

**`FileNotFoundError: config/config.yaml`**
Estás ejecutando Python desde un directorio que no es la raíz del proyecto. Haz `cd` hasta la raíz (la carpeta que contiene `config/`, `src/`, `tests/`, etc.) y vuelve a ejecutar.

**Los tests fallan con `ImportError: No module named 'src'`**
Mismo problema: ejecuta `pytest` desde la raíz del proyecto, no desde dentro de `tests/` ni de `src/`.

**`data/` ocupa demasiado espacio y quiero liberarlo**
```bash
rm -rf data/raw/ data/cache/    # macOS/Linux
```
Los datos se vuelven a descargar la próxima vez que ejecutes el pipeline de ingesta.