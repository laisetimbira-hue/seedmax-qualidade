#!/usr/bin/env bash
# Testa seedmax-backup.cjs contra um Firestore FALSO (dados fictícios). Não usa rede nem credenciais.
set -euo pipefail
cd "$(dirname "$0")"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
python3 teste/gerar_dados.py "$T/db" >/dev/null
export SEEDMAX_NODE_MODULES="$PWD/teste/stub" FAKE_DB="$T/db"
S=seedmax-backup.cjs
node $S backup "$T/bk" | tail -1
node $S verificar "$T/bk" | tail -1 | grep -qx BACKUP_OK
grep -q '"__tipo":"timestamp"' "$T/bk/users.json"
test -f "$T/bk/sincronizacoes__BENEF_INVERNO__historico.json"
node $S totais firestore "$T/vivo.json" >/dev/null
node $S totais "$T/bk" "$T/copia.json" >/dev/null
node $S comparar "$T/vivo.json" "$T/copia.json" | grep -qx SEM_DIFERENCA
python3 - "$T" <<'P'
import json,sys; t=sys.argv[1]; c=json.load(open(t+"/copia.json"))["conjuntos"]
assert c["LOTS"]["itens"]==5000 and c["LOTS"]["somas"]["kg"]==3002500.0, c["LOTS"]["somas"]
assert c["LOTS_SERVICO_INVERNO"]["lotes"]==["AMBEV|Cevada|AMBTESTE1","PGW|Aveia Branca|PGWTESTE1"]
assert c["BENEF_INVERNO.aveia"]["somas"]=={"kg_benef":300}
P
# hash adulterado -> verificar tem de falhar
sed -i 's/PGWTESTE1/PGWTESTE9/' "$T/bk/qualidade.json"
if node $S verificar "$T/bk" >/dev/null 2>&1; then echo "FALHA: adulteração não detectada"; exit 1; fi
# lote sumido -> comparar tem de apontar
python3 - "$T" <<'P'
import json,sys; t=sys.argv[1]; d=json.load(open(t+"/copia.json"))
d["conjuntos"]["LOTS_SERVICO_INVERNO"]["lotes"].pop(); d["conjuntos"]["LOTS_SERVICO_INVERNO"]["itens"]=1; d["conjuntos"]["LOTS_SERVICO_INVERNO"]["hash"]="x"
json.dump(d,open(t+"/depois.json","w"))
P
set +e; OUT=$(node $S comparar "$T/copia.json" "$T/depois.json"); RC=$?; set -e
[ "$RC" = 3 ] && grep -q "SUMIRAM: PGW|Aveia Branca|PGWTESTE1" <<<"$OUT" || { echo "FALHA: lote sumido não apontado"; exit 1; }
# ---- executar.sh: exportar e funcao com gcloud FALSO
roda() { HOME="$T/h" PATH="$T/bin:$PATH" GSTATE="$T/g-$CENARIO" EXPORT_INTERVALO_S=0 bash executar.sh "$@"; }
mkdir -p "$T/bin" "$T/h/seedmax-ponte/functions" && ln -sf "$PWD/teste/gcloud_falso.py" "$T/bin/gcloud" && echo '{}' > "$T/h/seedmax-ponte/firebase.json"
D="$T/h/seedmax-backups/pr33-teste"; mkdir -p "$D"; echo "$D" > "$T/h/seedmax-backups/ATUAL"; echo gs://x > "$D/guardado.txt"
CENARIO=ok roda exportar | tail -2 | grep -q "exportação oficial concluída (42 documentos)" || { echo "FALHA: exportar ok"; exit 1; }
CENARIO=ok roda exportar | grep -q "já concluída" || { echo "FALHA: exportar repetido"; exit 1; }
rm -f "$D"/export*; set +e; CENARIO=falha roda exportar >"$T/o" 2>&1; RC=$?; set -e
[ $RC = 1 ] && grep -q "FAILED permission denied" "$T/o" && [ ! -e "$D/exportado.txt" ] || { echo "FALHA: exportar com falha"; cat "$T/o"; exit 1; }
rm -f "$D"/export*; set +e; CENARIO=lento EXPORT_LIMITE_MIN=0 roda exportar >"$T/o" 2>&1; RC=$?; set -e
[ $RC = 4 ] && grep -q "NÃO foi cancelada" "$T/o" && ! grep -q "operations cancel" "$T"/g-lento/chamadas.log || { echo "FALHA: limite de espera"; cat "$T/o"; exit 1; }
CENARIO=ok roda funcao >"$T/o" 2>&1 || { echo "FALHA: funcao"; cat "$T/o"; exit 1; }
grep -q "to-revisions=sincronizarbenefinverno-00003-abc=100" "$D/funcao/ROLLBACK.txt" && test -s "$D/funcao/fonte-publicada.zip" && tar -tzf "$D/funcao/seedmax-ponte-antes.tgz" | grep -q firebase.json || { echo "FALHA: arquivos da função"; exit 1; }
grep -q "(ainda existe no Artifact Registry: sim)" "$D/funcao/ROLLBACK.txt" || { echo "FALHA: imagem"; exit 1; }
echo "TESTES_OK"
