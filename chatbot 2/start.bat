@echo off
setlocal
title Papo de Bola
cd /d "%~dp0"

set "PY=python"
%PY% --version >nul 2>nul || set "PY=py -3.13"
%PY% --version >nul 2>nul || set "PY=py"

if not exist ".venv\Scripts\python.exe" (
  echo [1/2] Criando ambiente virtual...
  %PY% -m venv .venv
  if errorlevel 1 goto erro

  echo [2/2] Instalando dependencias - pode demorar alguns minutos...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto erro
)

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo.
  echo ============================================================
  echo  Arquivo .env criado.
  echo  Abra o .env, preencha LLM_API_KEY e rode este start.bat
  echo  novamente.
  echo ============================================================
  echo.
  pause
  exit /b 1
)

echo.
findstr /R /C:"^LLM_API_KEY=." /C:"^GROQ_API_KEY=." ".env" >nul 2>nul
if errorlevel 1 (
  echo AVISO: LLM_API_KEY esta vazio no .env.
  echo Cole sua chave da Groq em https://console.groq.com/keys e rode novamente.
  echo.
)

echo  Papo de Bola: http://localhost:8000
echo  Pressione Ctrl+C para encerrar.
echo.
".venv\Scripts\python.exe" -m uvicorn server.main:app --host 127.0.0.1 --port 8000

echo.
echo O servidor foi encerrado.
pause
goto :eof

:erro
echo.
echo Falha na instalacao. Verifique a internet e se o Python 3.10 a 3.13 esta instalado.
pause
exit /b 1
