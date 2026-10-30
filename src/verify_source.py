"""Decode original Parquet independently through DuckDB and verify every projection cell."""
import argparse,csv,gzip,hashlib,json,math
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--private-dir',type=Path);a=p.parse_args();m=json.loads((ROOT/'data/source_manifest.json').read_text(encoding='utf-8'));checks=0
 for name,digest in m['files'].items():assert hashlib.sha256((ROOT/'data'/name).read_bytes()).hexdigest()==digest;checks+=1
 with gzip.open(ROOT/'data/records.csv.gz','rt',encoding='utf-8',newline='') as f:rows=list(csv.DictReader(f))
 assert len(rows)==m['source_rows'];checks+=1;grouped=defaultdict(list)
 for r in rows:grouped[r['source_file']].append(r)
 assert {k:len(v) for k,v in grouped.items()}==m['rows_by_source'];checks+=1
 if a.private_dir:
  import duckdb
  connection=duckdb.connect()
  for receipt in m['requests']:
   path=a.private_dir/receipt['file'];assert hashlib.sha256(path.read_bytes()).hexdigest()==receipt['sha256'];checks+=1;schema=m['schemas'][receipt['file']]
   columns=','.join('"'+schema['fields'][field].replace('"','""')+'"' for field in m['fields']);originals=connection.execute('SELECT '+columns+' FROM read_parquet(?)',[str(path)]).fetchall();items=grouped[receipt['file']];assert len(originals)==len(items)==schema['rows'];checks+=1
   for i,(native,record) in enumerate(zip(originals,items,strict=True),1):
    assert record['source_row']==str(i) and record['weather']==receipt['weather'];checks+=2
    for field,value in zip(m['fields'],native,strict=True):
     kind=record[field+'__type'];text=record[field]
     if value is None:assert kind=='null' and text==''
     elif type(value)is bool:assert kind=='bool' and text==('true' if value else 'false')
     elif type(value)is int:assert kind=='int' and str(value)==text
     elif type(value)is float:
      assert kind=='float'
      if math.isfinite(value):
       x=Decimal(str(value));assert abs(Decimal(text)-x)<=max(Decimal('1e-9'),abs(x)*Decimal('2e-16'))
      else:assert str(value)==text
     else:assert kind=='text' and str(value)==text
     checks+=1
 result=dict(status='PASS',mode='PRIVATE_ORIGINALS_DUCKDB_PASS' if a.private_dir else 'PUBLIC_HASH_SCHEMA_ONLY',checks=checks,source_rows=len(rows),scope='All selected private-original cells and typed source-row bindings when originals supplied;not simulation-physics,model-independence or field-savings validation')
 if a.private_dir:(ROOT/'data/source_verification.json').write_bytes((json.dumps(result,indent=2)+'\n').encode())
 print(json.dumps(result))
if __name__=='__main__':main()
