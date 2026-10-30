"""Reconstruct manuscript displays from individual decision and population ledgers."""
import csv,hashlib,json,sys,unicodedata
from decimal import Decimal,localcontext
from fractions import Fraction as Q
from pathlib import Path
from pypdf import PdfReader
if hasattr(sys,'set_int_max_str_digits'):sys.set_int_max_str_digits(0)
ROOT=Path(__file__).resolve().parents[1]
def rows(n):
 with (ROOT/'results'/n).open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))
def main():
 read=lambda n:json.loads((ROOT/n).read_text(encoding='utf-8'));choices=rows('development_choices.csv')+rows('held_choices.csv');diags=rows('development_model_diagnostics.csv')+rows('held_model_diagnostics.csv');models=rows('model_eligibility.csv');ledger=read('paper/TABLE_VALUES.json');reader=PdfReader(ROOT/'paper/manuscript.pdf');assert len(reader.pages)==6 and len(ledger)==103;checks=0
 texts=[' '.join(unicodedata.normalize('NFKC',p.extract_text()).split()) for p in reader.pages]
 for record in ledger:
  q=record['query']
  if q['kind']=='cohort':v=Q(sum(r['group']==q['group'] and (not q['eligible'] or r['eligible']=='True') for r in models))
  else:
   subset=[r for r in choices if r['role']==q['role'] and r['rule']==q['rule'] and (q['dimension']=='overall' or r[q['dimension']]==q['stratum'])];ids={r['model_id'] for r in subset};field=q['field']
   if field.startswith('mean_'):v=sum((Q(r[field[5:]+'_exact']) for r in subset),Q())/len(subset)
   elif field=='n':v=Q(len(subset))
   elif field=='different_from_nominal':v=Q(sum(r[field]=='True' for r in subset))
   else:
    col={'strict_unique_reversals':'strict_unique_reversal','top_set_changes':'top_set_changed','negative_action_case_cells':'negative_action_case_cells'}[field];v=Q(sum(int(r[col]) if field=='negative_action_case_cells' else r[col]=='True' for r in diags if r['model_id'] in ids))
  with localcontext() as ctx:ctx.prec=80;display=format(Decimal(v.numerator)/Decimal(v.denominator),record['fmt'])
  assert record['text']==display and display in texts[record['page']],record;checks+=2
 gate=read('results/source_gate.json');assert gate['source_rows']==28510 and gate['planned_models']==882 and gate['eligible_models']==535 and gate['source_key_groups']==8700 and gate['repeated_source_rows']==19810 and gate['conflicting_key_groups']==0;checks+=6
 assert sum('amy2012_missing_baseline' in r['reasons'] for r in models)==219;checks+=1
 for role,reverse,changed,negative in [('development',33,34,1),('held',17,17,0)]:
  subset=[r for r in diags if r['role']==role];assert sum(r['strict_unique_reversal']=='True' for r in subset)==reverse;assert sum(r['top_set_changed']=='True' for r in subset)==changed;assert sum(int(r['negative_action_case_cells']) for r in subset)==negative;checks+=3
 assert read('data/source_verification.json')['checks']==342144 and read('results/independent_inputs.json')['checks']==328115;checks+=2
 for role,n in [('development',87283),('held',23087)]:assert read('results/independent_'+role+'.json')['checks']==n;checks+=1
 replay=read('results/reproduction.json');assert replay['status']=='PASS' and replay['exact_csv_fields_including_headers']==447801 and replay['json_documents']==6 and replay['tests']==29 and replay['frozen_dependencies']==28 and replay['original_files_unchanged'] and not replay['network_during_replay'];checks+=7
 assert len(read('results/frozen_dependencies.json')['sha256'])==28;checks+=1
 joined=' '.join(texts)
 for phrase in ['not evidence of field savings','No new EnergyPlus simulation','Missing scenarios are unknown','not a random-sample','do not isolate a causal weather effect','not physically exact','not peer reviewed','including Azure optimization','default integer-to-string limit','29 fixtures','256 actual SVG coordinates','No endorsement is implied']:
  assert phrase.casefold() in joined.casefold(),phrase;checks+=1
 scope=read('paper/PUBLICATION_SCOPE.json');assert scope['scope']=='independent-program-study' and scope['formal_submission_target'] is False and len(scope['public_files'])==5
 for name,digest in scope['public_files'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest;checks+=1
 assert all(len(t)>1500 for t in texts) and not reader.get_fields();pdfroot=reader.trailer['/Root'];assert '/AA' not in pdfroot and '/JavaScript' not in str(pdfroot.get('/Names',''));checks+=3
 result=dict(status='PASS',checks=checks,displayed_values=len(ledger),pages=6,scope='Independent individual-ledger display arithmetic,source counts,claim qualifiers,scoped hashes and bounded PDF structure;rendering checked separately')
 (ROOT/'results/paper_verification.json').write_bytes((json.dumps(result,indent=2)+'\n').encode());print(json.dumps(result))
if __name__=='__main__':main()
