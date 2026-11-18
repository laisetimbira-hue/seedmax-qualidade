@echo off
rem SEEDMAX - sincroniza a planilha de Beneficiados do Inverno com o SEEDMAX.
rem E este arquivo que o Agendador de Tarefas do Windows executa.
rem Configuracao (caminho da planilha e da credencial): config_benef_inverno.bat
rem na mesma pasta (copie de config_benef_inverno.exemplo.bat).

setlocal
cd /d "%~dp0"
if not exist "config_benef_inverno.bat" (
  echo Falta o arquivo config_benef_inverno.bat nesta pasta.
  exit /b 1
)
call "config_benef_inverno.bat"
set PYTHONUTF8=1
py -3 "%~dp0..\sincronizar_benef_inverno.py" %*
exit /b %ERRORLEVEL%
