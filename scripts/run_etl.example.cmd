@echo off
REM Servidor Windows de Microsip. Mismo patron que la extraccion de DTODO:
REM   extrae Firebird (local) -> Parquet -> scp a la Mac -> rebuild en la Mac.
REM Copiar a scripts\run_etl.cmd y completar MAC con el MISMO usuario@direccion que usa el run.cmd de DTODO.
REM Registrar la tarea con un usuario real (NO SYSTEM: no ve la llave ssh) y StartWhenAvailable (ver README).
setlocal
set EMP=korner
set MAC=dtodo-mac@100.77.112.121
set DEST=microsip-mcp
set SSH=ssh -n -o BatchMode=yes -o ConnectTimeout=20
cd /d "%~dp0.."
echo %date% %time% INICIO > last_run.log

python etl\extract.py --config empresas\%EMP%.toml --queries etl\%EMP%\queries --ini etl\etl.ini --out data\%EMP%\parquet >> last_run.log 2>&1
if errorlevel 1 (echo ERROR extract >> last_run.log & exit /b 1)

%SSH% %MAC% "rm -rf %DEST%/data/%EMP%/parquet.new && mkdir -p %DEST%/data/%EMP%/parquet.new" >> last_run.log 2>&1
if errorlevel 1 (echo ERROR ssh-prep >> last_run.log & exit /b 1)
scp -o BatchMode=yes data\%EMP%\parquet\*.parquet %MAC%:%DEST%/data/%EMP%/parquet.new/ >> last_run.log 2>&1
if errorlevel 1 (echo ERROR scp >> last_run.log & exit /b 1)
%SSH% %MAC% "%DEST%/scripts/rebuild.sh %EMP%" >> last_run.log 2>&1
if errorlevel 1 (echo ERROR rebuild >> last_run.log & exit /b 1)

echo FIN >> last_run.log
