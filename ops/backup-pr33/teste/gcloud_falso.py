#!/usr/bin/env python3
"""gcloud FALSO para testar executar.sh (exportar/funcao). Cenário em $CENARIO: ok | falha | lento."""
import json, os, sys, pathlib, zipfile
a = sys.argv[1:]; st = pathlib.Path(os.environ["GSTATE"]); st.mkdir(exist_ok=True)
log = st / "chamadas.log"; log.open("a").write(" ".join(a) + "\n")
cen = os.environ.get("CENARIO", "ok"); j = lambda o: print(json.dumps(o))
cmd = " ".join(a[:3])
if a[:2] == ["config", "get-value"]: print("seedmax-4c755")
elif a[:3] == ["storage", "buckets", "describe"]: print("enforced\tTrue")
elif a[:2] == ["firestore", "export"]:
    if "--async" not in a: sys.exit("teste: export sem --async")
    (st / "dest").write_text(a[2]); j({"name": "projects/seedmax-4c755/databases/(default)/operations/OP1"})
elif a[:3] == ["firestore", "operations", "describe"]:
    n = int((st / "n").read_text()) + 1 if (st / "n").exists() else 1; (st / "n").write_text(str(n))
    dest = (st / "dest").read_text()
    if cen == "falha" and n >= 2: j({"name": a[3], "done": True, "error": {"code": 7, "message": "permission denied"}, "metadata": {"operationState": "FAILED"}})
    elif cen == "lento" or n < 3: j({"name": a[3], "done": False, "metadata": {"operationState": "PROCESSING", "progressDocuments": {"completedWork": str(n * 10)}}})
    else: j({"name": a[3], "done": True, "metadata": {"operationState": "SUCCESSFUL", "outputUriPrefix": dest, "progressDocuments": {"completedWork": "42"}}})
elif a[:3] == ["storage", "ls", "-r"]:
    d = a[3]; print(d + "/:"); print(d + "/x.overall_export_metadata"); print(d + "/all_namespaces/all_kinds/output-0")
elif a[:2] == ["storage", "ls"]: print(a[2] + "ROLLBACK.txt")
elif a[:2] == ["functions", "list"]: print("projects/seedmax-4c755/locations/southamerica-east1/functions/sincronizarBenefInverno")
elif a[:2] == ["functions", "describe"]:
    j({"name": "projects/seedmax-4c755/locations/southamerica-east1/functions/sincronizarBenefInverno", "environment": "GEN_2", "state": "ACTIVE", "updateTime": "2026-11-18T19:00:00Z",
       "buildConfig": {"runtime": "nodejs20", "entryPoint": "sincronizarBenefInverno", "source": {"storageSource": {"bucket": "gcf-v2-sources-1-southamerica-east1", "object": "sinc/function-source.zip", "generation": "123"}}},
       "serviceConfig": {"revision": "sincronizarbenefinverno-00003-abc", "service": "projects/seedmax-4c755/locations/southamerica-east1/services/sincronizarbenefinverno", "serviceAccountEmail": "sinc@x"}})
elif a[:3] == ["run", "services", "describe"]: j({"metadata": {"name": a[3]}})
elif a[:3] == ["run", "revisions", "describe"]: j({"spec": {"containers": [{"image": "img:latest"}]}, "status": {"imageDigest": "southamerica-east1-docker.pkg.dev/p/gcf-artifacts/s@sha256:ab"}})
elif a[:3] == ["artifacts", "docker", "images"]: sys.exit(1 if cen == "semimagem" else 0)
elif a[:2] == ["storage", "cp"]:
    src = [x for x in a[2:] if not x.startswith("-")]
    if src[0].startswith("gs://gcf"):
        with zipfile.ZipFile(src[-1], "w") as z: z.writestr("package.json", "{}"); z.writestr("index.js", "")
else: sys.exit("teste: comando inesperado: " + " ".join(a))
