@echo off
rem Copie este arquivo para config_benef_inverno.bat e ajuste os dois caminhos.
rem Use o caminho de REDE (\\SERVIDOR\...), nao a letra da unidade (Z:\...):
rem o Agendador de Tarefas nao enxerga unidades mapeadas.

set BENEF_INVERNO_PLANILHA=\\SERVIDOR\PASTA\LOTES BENEFICIADOS INVERNO 26-26.xlsx
set SEEDMAX_CREDENCIAL=C:\SEEDMAX\credencial\seedmax-benef-inverno.json
set BENEF_INVERNO_LOGS=C:\SEEDMAX\logs
