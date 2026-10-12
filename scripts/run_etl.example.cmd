@echo off
REM Servidor Windows de Microsip. Mismo patron que la extraccion de DTODO:
REM   extrae Firebird (local) -> Parquet -> scp a la Mac -> rebuild en la Mac.
REM Copiar a scripts\run_etl.cmd. MAC = la Mac por ZeroTier (10.147.20.223), NO por su IP de LAN (192.168.1.x):
REM ese fue el fallo de DTODO desde el 8-oct (la Mac ya no esta en la LAN del servidor). Misma llave que DTODO.
REM Registrar la tarea con un usuario real (NO SYSTEM: no ve la llave ssh) y StartWhenAvailable (ver README).
setlocal
set EMP=korner
set MAC=dtodo-mac@10.147.20.223
set KEY=C:\microsip-etl\ssh\microsip_mac
set DEST=microsip-mcp
set SSH=ssh -n -i "%KEY%" -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=20
cd /d "%~dp0.."
echo %date% %time% INICIO > last_run.log

python etl\extract.py --config empresas\%EMP%.toml --queries etl\%EMP%\queries --ini etl\etl.ini --out data\%EMP%\parquet >> last_run.log 2>&1
if errorlevel 1 (echo ERROR extract >> last_run.log & exit /b 1)

%SSH% %MAC% "rm -rf %DEST%/data/%EMP%/parquet.new && mkdir -p %DEST%/data/%EMP%/parquet.new" >> last_run.log 2>&1
if errorlevel 1 (echo ERROR ssh-prep >> last_run.log & exit /b 1)
scp -i "%KEY%" -o StrictHostKeyChecking=accept-new -o BatchMode=yes data\%EMP%\parquet\*.parquet %MAC%:%DEST%/data/%EMP%/parquet.new/ >> last_run.log 2>&1
if errorlevel 1 (echo ERROR scp >> last_run.log & exit /b 1)
%SSH% %MAC% "%DEST%/scripts/rebuild.sh %EMP%" >> last_run.log 2>&1
if errorlevel 1 (echo ERROR rebuild >> last_run.log & exit /b 1)

echo FIN >> last_run.log
