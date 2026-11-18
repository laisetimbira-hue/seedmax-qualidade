@echo off
rem Cria a tarefa no Agendador do Windows: seg a sex, a cada 15 min, das 06:00 as 20:00.
rem Rode este arquivo UMA vez, como administrador, na conta que tem acesso ao servidor.
rem Ele pede a senha dessa conta para a tarefa rodar mesmo com ninguem logado.

setlocal
set TAREFA=SEEDMAX - Beneficiamento Inverno
set /p USUARIO=Conta do Windows que acessa o servidor (ex.: EMPRESA\qualidade): 
schtasks /Create /TN "%TAREFA%" /TR "\"%~dp0sincronizar_benef_inverno.bat\"" ^
  /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 06:00 /RI 15 /DU 14:00 ^
  /RU "%USUARIO%" /RP * /RL LIMITED /F
if errorlevel 1 (echo Nao consegui criar a tarefa. & exit /b 1)
echo.
echo Tarefa criada: "%TAREFA%". Para testar agora:
echo   schtasks /Run /TN "%TAREFA%"
