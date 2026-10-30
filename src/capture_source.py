"""Capture the ten declared annual Parquet files once,with receipts before parsing."""
import argparse,hashlib,json,platform,subprocess,urllib.request
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('private_dir',type=Path);a=p.parse_args();a.private_dir.mkdir(parents=True,exist_ok=False)
 assert not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip(),'Commit protocol and capture list before retrieval'
 commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip();requests=json.loads((ROOT/'data/source_requests.json').read_text(encoding='utf-8'));assert len(requests)==10;receipts=[]
 for item in requests:
  start=datetime.now(timezone.utc).isoformat();target=a.private_dir/item['file']
  try:
   with urllib.request.urlopen(item['url'],timeout=60) as response:
    status=response.status;headers={k:response.headers.get(k) for k in ['Content-Type','Content-Length','ETag','Last-Modified']};digest=hashlib.sha256();size=0
    with target.open('xb') as stream:
     while chunk:=response.read(1024*1024):stream.write(chunk);digest.update(chunk);size+=len(chunk)
    record=dict(**item,start_utc=start,end_utc=datetime.now(timezone.utc).isoformat(),status=status,headers=headers,bytes=size,sha256=digest.hexdigest(),protocol_commit=commit,python=platform.python_version())
   receipts.append(record);(a.private_dir/'requests.json').write_bytes((json.dumps(receipts,indent=2)+'\n').encode());print(json.dumps({k:record[k] for k in ['file','status','bytes','sha256']}),flush=True)
   assert status==200 and size==item['bytes_from_listing'],'Preserve source mismatch before models'
  except Exception as error:
   receipts.append(dict(file=item['file'],url=item['url'],start_utc=start,end_utc=datetime.now(timezone.utc).isoformat(),error=type(error).__name__,protocol_commit=commit));(a.private_dir/'requests.json').write_bytes((json.dumps(receipts,indent=2)+'\n').encode());raise
 print('TEN_SOURCE_FILES_CAPTURED_NO_RANKING_SCORES')
if __name__=='__main__':main()
