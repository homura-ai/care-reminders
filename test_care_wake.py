"""Offline tests for the sleep rule in care_wake.py. Run: python3 test_care_wake.py"""
import json, os, pathlib, sys, tempfile, time
_TMP = tempfile.mkdtemp()
os.environ['CARE_STATE_DIR'] = _TMP
os.environ['CARE_CONFIG'] = os.path.join(_TMP, 'none.json')
sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import care_wake as cw

S = {'sleeping': True, 'sleep_state': 'sleeping', 'sleeping_since': '2026-11-11T16:55:37+00:00'}
def test_rule():
    assert cw.asleep(S, None)
    assert cw.asleep(S, cw.ts('2026-11-11T16:55:37.250Z'))      # the declaration itself
    assert cw.asleep(S, cw.ts('2026-11-11T18:55:38Z'))          # later activity does NOT wake
    assert not cw.asleep(dict(S, awake_confirmed_at='2026-11-11T18:00:00+00:00'), None)
    assert not cw.asleep({}, None)
def test_store_latest():
    cw.store_latest('2026-11-11T18:00:00Z')
    assert cw.stored_latest() == cw.ts('2026-11-11T18:00:00Z')
def test_reconcile():
    p = pathlib.Path(tempfile.mkdtemp())/'state.json'
    p.write_text(json.dumps(dict(S)))
    assert cw.reconcile(p, cw.ts('2026-11-11T17:30:00Z')) is False and json.loads(p.read_text())['sleeping']
    p.write_text(json.dumps(dict(S, awake_confirmed_at='2026-11-11T17:30:00+00:00')))
    assert cw.reconcile(p, None) is True
    s = json.loads(p.read_text()); assert not s['sleeping'] and not s['sleep_state'] and s['wake_history'][-1]['woke_at'].startswith('2026-11-11T17:30')
    assert cw.reconcile(p, None) is False
def test_reconcile_lock():
    import fcntl, threading
    p = pathlib.Path(tempfile.mkdtemp())/'state.json'; p.write_text(json.dumps(dict(S)))
    done = []
    with open(cw.LOCK, 'a') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        p.write_text(json.dumps(dict(S, awake_confirmed_at='2026-11-11T18:00:00+00:00')))
        th = threading.Thread(target=lambda: done.append(cw.reconcile(p, None))); th.start()
        time.sleep(0.3); assert not done                      # waits for the holder
        p.write_text(json.dumps(dict(S, sleeping_since='2026-11-11T19:00:00+00:00')))  # newer sleep under lock
    th.join(2); assert done == [False]                        # re-reads and keeps the newer sleep
    assert json.loads(p.read_text())['sleeping']
def test_same_second_stays_asleep():
    assert cw.asleep(dict(S, awake_confirmed_at=S['sleeping_since']), None)
def test_naive_never_wakes():
    assert cw.asleep(dict(S, awake_confirmed_at='2026-11-11T19:00:00'), None)
    assert cw.asleep(dict(S, sleeping_since='2026-11-11T16:55:37', awake_confirmed_at='2026-11-11T19:00:00+00:00'), None)

if __name__ == '__main__':
    tests = [f for n, f in list(globals().items()) if n.startswith('test_')]
    for t in tests:
        t()
    import shutil; shutil.rmtree(_TMP)
    print(f'{len(tests)} tests passed')
