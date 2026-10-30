"""Bind the descriptive held application to a prior committed dependency list."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def verify():
 path="results/frozen_dependencies.json"
 commit=subprocess.check_output(["git","log","-1","--format=%H","--",path],cwd=ROOT,text=True).strip()
 assert commit,"Dependency freeze must be committed before held summaries"
 manifest=json.loads((ROOT/path).read_text(encoding="utf-8"))
 assert json.loads(subprocess.check_output(["git","show",commit+":"+path],cwd=ROOT))==manifest
 for name,digest in manifest["sha256"].items():
  assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,("Changed frozen dependency",name)
  assert hashlib.sha256(subprocess.check_output(["git","show",commit+":"+name],cwd=ROOT)).hexdigest()==digest,("Freeze-commit byte mismatch",name)
 return commit,len(manifest["sha256"])
if __name__=="__main__":print(verify())
