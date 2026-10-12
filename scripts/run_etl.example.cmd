@echo off
REM Servidor Windows (tarea programada 02:00, usuario con contrasena guardada, StartWhenAvailable).
REM Copiar a scripts\run_etl.cmd y ajustar. Extrae Firebird -> Parquet, copia a la Mac y reconstruye.
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
