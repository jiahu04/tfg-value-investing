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
git clone https://github.com/<tu-usuario>/value-investing-tfg.git
cd value-investing-tfg
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
  contact_email: "tu@correo.com"   # ← cambia esto
```

### 2.6 Verificar que todo está bien

```bash
python scripts/verify_imports.py
```

Si termina con `✓ Todo correcto. El entorno está listo.` ya puedes trabajar.

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

# Solo los tests de integración (cuando existan)
pytest tests/integration/


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

> **Nota:** de momento está implementada la **Etapa 1 (adquisición de datos, paso 1.1)**. El resto de etapas (pipeline de selección, backtest y aportación) se irán añadiendo en las Fases 1–3 del plan.

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

### Resto del pipeline (aún no implementado)

```bash
python -m src.pipeline.run        # Etapas 2–5: lista priorizada (pendiente)
python -m src.backtest.run        # backtesting 2013–2025 (pendiente)
python -m src.contributions.run   # estrategias de aportación (pendiente)
```

Los resultados (tablas LaTeX y gráficas) se generarán en `outputs/`.

Para forzar una descarga limpia de datos:
```bash
rm -rf data/cache/ data/raw/     # macOS / Linux
rmdir /s data\cache & rmdir /s data\raw   # Windows
python -m src.ingest.run_ingest --step all
```

---

## 9. Estructura del proyecto

```
value-investing-tfg/
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
│   ├── backtest/                ← Módulo B1: motor de backtesting (2013–2025)
│   ├── contributions/           ← Módulo B2: simulación de estrategias de aportación
│   ├── reporting/               ← Gráficas y exportación de tablas a LaTeX
│   └── utils/
│       └── config_loader.py     ← cargador de config.yaml (implementado)
│
├── tests/
│   ├── unit/                    ← tests por módulo (rápidos, sin datos reales)
│   └── integration/             ← tests end-to-end (se añadirán en Fases 1–3)
│
├── data/                        ← excluido de Git, se regenera con el pipeline
│   ├── raw/                     ← datos crudos de SEC EDGAR y yfinance
│   └── cache/                   ← datos procesados en formato Parquet
│
├── docs/
│   ├── registro_decisiones.md   ← decisiones de diseño con justificación
│   ├── notas_memoria.md         ← contenido reutilizable para la memoria del TFG
│   └── dev_notes.md             ← log de sesiones de desarrollo
│
├── scripts/
│   └── verify_imports.py        ← comprueba que el entorno está bien instalado
│
├── outputs/                     ← excluido de Git, generado por reporting/
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

# ── Git ───────────────────────────────────────────────────────────────────────
git status                                    # ver estado del repo
git add .                                     # añadir todos los cambios
git commit -m "mensaje"                       # hacer commit
git push                                      # subir a GitHub
git log --oneline                             # ver historial resumido
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

**`FileNotFoundError: config/config.yaml`**
Estás ejecutando Python desde un directorio que no es la raíz del proyecto. Haz `cd` hasta la raíz (la carpeta que contiene `config/`, `src/`, `tests/`, etc.) y vuelve a ejecutar.

**Los tests fallan con `ImportError: No module named 'src'`**
Mismo problema: ejecuta `pytest` desde la raíz del proyecto, no desde dentro de `tests/` ni de `src/`.

**`data/` ocupa demasiado espacio y quiero liberarlo**
```bash
rm -rf data/raw/ data/cache/    # macOS/Linux
```
Los datos se vuelven a descargar la próxima vez que ejecutes el pipeline de ingesta.