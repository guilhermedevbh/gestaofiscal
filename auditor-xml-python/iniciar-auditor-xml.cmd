@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.9 ou superior nao foi encontrado.
  echo Instale em https://www.python.org/downloads/ marcando "Add python.exe to PATH" e execute novamente.
  pause
  exit /b 1
)
if not exist "data\auditoria_xml.db" (
  echo Primeira execucao: criando o banco e o usuario administrador.
  python gerenciar.py inicializar
)
echo.
echo Auditoria Fiscal de XML em http://127.0.0.1:8765
echo Mantenha esta janela aberta durante o uso.
python gerenciar.py servidor
pause
