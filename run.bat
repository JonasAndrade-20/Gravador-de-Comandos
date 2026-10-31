@echo off
setlocal
cd /d "%~dp0"

python -m streamlit --version >nul 2>nul
if errorlevel 1 (
    echo.
    echo Streamlit nao foi encontrado neste ambiente Python.
    echo Instale as dependencias com:
    echo     python -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo Iniciando o Gerador de Manuais...
echo Feche esta janela para encerrar o servidor.
python -m streamlit run app.py
if errorlevel 1 pause
