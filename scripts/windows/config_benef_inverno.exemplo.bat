@echo off
rem Copie este arquivo para config_benef_inverno.bat e ajuste.
rem Use o caminho de REDE (\\SERVIDOR\...), nao a letra da unidade (Z:\...):
rem o Agendador de Tarefas nao enxerga unidades mapeadas.
rem NENHUMA chave do Firebase fica neste computador: a senha da conta tecnica
rem fica no Gerenciador de Credenciais do Windows (sincronizar_benef_inverno.bat --guardar-senha).

set BENEF_INVERNO_PLANILHA=\\SERVIDOR\PASTA\LOTES BENEFICIADOS INVERNO 26-26.xlsx
set SEEDMAX_SYNC_EMAIL=sincronizador.inverno@sementescomvigor.com
set BENEF_INVERNO_LOGS=C:\SEEDMAX\logs
