cd /workspace/desk
date +%T; tail -1 logs/variants.log | cut -c1-80
python3 -c "
import sys,time; sys.path.insert(0,'manual'); import run_variants as rv
with rv.cycle_lock('TEST holder'): time.sleep(3)
" &
sleep 1
manual/variants.sh prepare; echo "prepare-while-locked rc=$?"
manual/variants.sh finish meme-var-20261029-0850; echo "finish-while-locked rc=$?"
wait
python3 -c "
import sys,os,datetime; sys.path.insert(0,'manual'); import run_variants as rv
print('in_use 0849', rv.run_id_in_use('meme-var-20261029-0849'), 'in_use fake', rv.run_id_in_use('meme-var-20991231-000000'))
f=os.path.join(rv.CYCLES_DIR,'meme-var-20991231-000000.json'); open(f,'w').write('{}')
rv.kst=lambda: datetime.datetime(2099,12,31,0,0,0)
rv.bots.scan_once=lambda *a: (_ for _ in ()).throw(RuntimeError('SCAN SHOULD NOT RUN'))
try: rv.prepare()
except SystemExit as e: print('reuse ->', e)
finally: os.remove(f)
"
manual/variants.sh finish meme-var-20261029-0849; echo "finish-finished rc=$?"
cat state/variants.lock; echo "[lock content above, empty = released]"
