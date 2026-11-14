"""Offline tests for care_send.py: temporary state dir and config, no real notification.
Run: python3 test_care_send.py
"""
import os, tempfile, pathlib, json
_TMP = pathlib.Path(tempfile.mkdtemp())
os.environ['CARE_STATE_DIR'] = str(_TMP / 'state')
os.environ['CARE_CONFIG'] = str(_TMP / 'config.json')
(_TMP / 'config.json').write_text(json.dumps({
    'timezone': 'America/New_York', 'prefix': 'Care: ',
    # A bedtime after midnight; test_bedtime_before_midnight... covers the other kind.
    'bedtime': {'wind_down': '02:15', 'firm': '03:30', 'end': '08:00'},
    'night': {'start_hour': 22, 'end_hour': 8},
    'notify': {'argv': ['fake-notify', '{text}'], 'receipt': 'queued'}}))
import importlib.util, time
from datetime import datetime, timezone
from unittest.mock import patch
import sys; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
spec = importlib.util.spec_from_file_location('cf', pathlib.Path(__file__).with_name('care_send.py'))
cf = importlib.util.module_from_spec(spec); spec.loader.exec_module(cf)
NOW = time.time()
iso = lambda d: datetime.fromtimestamp(NOW + d, timezone.utc).isoformat()
def st(**kw):
    s = {'cadence_started_at': iso(-3900), 'last_reminder': {'any': iso(-3600)}, 'postponed_until': None}
    s.update(kw)
    # Ordinary-cadence fixtures already received tonight's bedtime notices.
    s['last_reminder'].setdefault('wind_down', iso(0))
    s['last_reminder'].setdefault('firm', iso(0))
    return s
def d(state, own=None, running=False, hour=12, latest=None):
    return cf.decide(state, own or {}, NOW, running, hour, latest)
def test_send(): assert d(st()) == (None, ['break', 'zoom_out'])
def test_meal(): assert d(st(meal_next_due_at=iso(-60)))[1] == ['break', 'meal', 'zoom_out']
def test_skip(): assert d(st(meal_next_due_at=iso(-60), skips={'meal': iso(3600)}))[1] == ['break', 'zoom_out']
def test_spacing(): assert d(st(), own={'last_sent': NOW - 300})[0] == 'reminded recently'
def test_snooze(): assert d(st(postponed_until=iso(600)))[0] == 'snoozed'
def test_expired_snooze_overrides_spacing(): assert d(st(postponed_until=iso(-60), last_reminder={'any':iso(-300)}))[0] is None
def test_old_resume_not_duplicated(): assert d(st(postponed_until=iso(-60), last_reminder={'any':iso(-30)}))[0] == 'reminded recently'
def test_run(): assert d(st(), running=True)[0] == 'in run'
def test_sleep(): assert d(st(sleeping=True, sleeping_since=iso(-600)))[0] == 'sleeping'
def test_activity_does_not_wake(): assert d(st(sleeping=True, sleeping_since=iso(-3600)), latest=NOW - 60)[0] == 'sleeping'
def test_woke(): assert d(st(sleeping=True, sleeping_since=iso(-3600), awake_confirmed_at=iso(-60)))[0] is None
def test_night_unknown(): assert d(st(), hour=3)[0].startswith('night')
def test_night_idle(): assert d(st(), hour=3, latest=NOW-91*60)[0].startswith('night')
def test_night_active(): assert d(st(), hour=3, latest=NOW-10*60)[0] is None
def test_quiet(): assert d(st(personal_quiet=True))[0] == 'personal quiet'
def test_unreadable(): assert d(None)[0] == 'state unreadable'
def test_ack_waits_until_next_anchor():
    s=st(cadence_started_at=iso(-31*60), last_break_ack_at=iso(-30), last_zoom_out_ack_at=iso(-30))
    assert d(s)[0] == 'nothing due'
def test_unanswered_break_repeats_15m():
    s=st(cadence_started_at=iso(-46*60), last_reminder={'break':iso(-16*60), 'zoom_out':iso(-16*60), 'any':iso(-16*60)})
    assert d(s)[1] == ['break', 'zoom_out']
def test_30m_break_15m_zoom():
    s=st(cadence_started_at=iso(-16*60))
    assert d(s)[1] == ['zoom_out']
def test_legacy_backup_spacing():
    s=st(last_break_ack_at=iso(-7200), last_zoom_out_ack_at=iso(-7200))
    own={'last_sent':NOW-100,'history':[{'at':iso(-100),'kinds':['break','zoom_out'],'sent':True}]}
    assert d(s,own)[0] == 'nothing due'
def test_no_secondary_when_send_failed(tmp_path):
    calls=[]
    def fake_run(args,stdin=None):
        calls.append(args)
        return 0, 'skipped'
    with patch.multiple(cf, ROOT=tmp_path, OWN=tmp_path/'own.json'), patch.dict(cf.CFG, secondary={'argv':['second','{text}']}), patch.object(cf,'current',return_value=(st(),False,NOW)), patch.object(cf,'run',side_effect=fake_run):
        assert cf.tick() == 0
        assert len(calls)==1 and calls[0][0]=='fake-notify'
        first=json.loads(cf.OWN.read_text())['pending']['event_key']
        cf.tick()
        assert json.loads(cf.OWN.read_text())['pending']['event_key']==first

def test_state_read_after_slow_run_status():
    order=[]
    with patch.object(cf,'probe',side_effect=lambda *a:order.append('probe')), patch.object(cf,'in_run',side_effect=lambda:order.append('run')), patch.object(cf,'load_state',side_effect=lambda:order.append('state')):
        cf.current()
    assert order==['probe','run','state']
def test_queued_records_state_and_channels(tmp_path):
    from contextlib import nullcontext
    calls=[]
    state=st()
    def fake_run(args,stdin=None):
        calls.append(args)
        return 0,'queued' if args[0]=='fake-notify' else ''
    with patch.multiple(cf,ROOT=tmp_path,OWN=tmp_path/'own.json',STATE=tmp_path/'state.json'), patch.dict(cf.CFG, secondary={'argv':['second','{text}']}), patch.object(cf,'current',return_value=(state,False,NOW)), patch.object(cf,'load_state',side_effect=lambda:json.loads(cf.STATE.read_text())), patch.object(cf.care_wake,'state_lock',return_value=nullcontext()), patch.object(cf,'run',side_effect=fake_run):
        cf.STATE.write_text(json.dumps(state))
        assert cf.tick()==0
        saved=json.loads(cf.STATE.read_text())
        assert saved['last_reminder']['any'] and saved['last_reminder']['break']
        assert saved['delivery_history'][-1]['text'] == 'Care: Take a one-minute break, then zoom out and write down the top 1–2 things to do.'
        assert len(calls)==2 and calls[0][0]=='fake-notify' and calls[1][0]=='second'
        assert json.loads(cf.OWN.read_text())['current']['secondary'] is True

def test_dry_run_writes_nothing(tmp_path, capsys=None):
    import io, contextlib
    out = io.StringIO()
    with patch.multiple(cf, ROOT=tmp_path/'r', OWN=tmp_path/'r/own.json', STATE=tmp_path/'r/state.json'), patch.object(cf,'in_run',return_value=False), patch.object(cf,'load_state',return_value=st()), patch.object(cf,'local_hour',return_value=12), patch.object(cf,'run') as run, contextlib.redirect_stdout(out):
        assert cf.main(['--dry-run']) == 0
    assert out.getvalue().startswith('would send: Care: Take a one-minute break')
    run.assert_not_called()
    assert not (tmp_path/'r').exists()

def night_time(h, m=0, day=12, month=11):
    return datetime(2026,month,day,h,m,tzinfo=cf.C.zone()).timestamp()
def bed_state(**kw):
    value={'last_reminder':{},'cadence_started_at':None}
    value.update(kw);return value
def test_wind_down_boundaries_and_catchup():
    for h,m,expected in [(2,14,[]),(2,15,['wind_down']),(2,47,['wind_down']),(3,29,['wind_down']),(3,30,[])]:
        assert cf.bedtime_kinds(bed_state(),{},night_time(h,m))==expected
    assert cf.bedtime_kinds(bed_state(),{},night_time(12))==[]
def test_bedtime_once_per_night_and_next_night():
    s=bed_state(last_reminder={'wind_down':datetime.fromtimestamp(night_time(2,16),timezone.utc).isoformat()})
    assert cf.bedtime_kinds(s,{},night_time(2,47))==[]
    assert cf.bedtime_kinds(s,{},night_time(2,15,day=13))==['wind_down']
    own={'last_by_kind':{'firm':night_time(3,31)}}
    assert cf.bedtime_kinds(bed_state(),own,night_time(3,40),night_time(3,39))==[]
def test_firmer_requires_recent_main_activity():
    now=night_time(3,30)
    for activity in (None,now-901,now+1):
        assert cf.bedtime_kinds(bed_state(),{},now,activity)==[]
    assert cf.bedtime_kinds(bed_state(),{},now,now-60)==['firm']
    assert cf.bedtime_kinds(bed_state(),{},night_time(8),night_time(8))==[]
def test_bedtime_gates_and_skips():
    now=night_time(3,30)
    base=bed_state()
    for extra in ({'personal_quiet':True},{'sleeping':True,'sleeping_since':'2026-11-12T07:00:00Z'},{'postponed_until':'2026-11-12T09:00:00Z'}):
        assert cf.decide(bed_state(**extra),{},now,False,3,now)[0] is not None
    assert cf.decide(base,{},now,True,3,now)[0]=='in run'
    assert cf.decide(bed_state(skips={'firm':None}),{},now,False,3,now)[1] is None
    assert cf.decide(base,{},now,False,3,now)[1]==['firm']
def test_bedtime_shared_spacing_and_timezone():
    now=night_time(3,30)
    assert cf.decide(bed_state(),{'last_sent':now-60},now,False,3,now)[0]=='reminded recently'
    # July uses EDT: 02:15 local is 06:15 UTC, not the winter 07:15 UTC.
    summer=night_time(2,15,day=12,month=7)
    assert datetime.fromtimestamp(summer,timezone.utc).hour==6
    assert cf.bedtime_kinds(bed_state(),{},summer)==['wind_down']
def test_bedtime_before_midnight_with_end_after_midnight():
    with patch.dict(cf.CFG['bedtime'], {'wind_down': '22:30', 'firm': '23:30', 'end': '07:00'}):
        assert cf.bedtime_kinds(bed_state(),{},night_time(22,29))==[]
        assert cf.bedtime_kinds(bed_state(),{},night_time(22,30))==['wind_down']
        now=night_time(23,45)
        assert cf.bedtime_kinds(bed_state(),{},now,now-60)==['firm']
        after=night_time(1,0,day=13)   # past midnight, same night
        assert cf.bedtime_kinds(bed_state(),{},after,after-60)==['firm']
        own={'last_by_kind':{'firm':night_time(23,40)}}
        assert cf.bedtime_kinds(bed_state(),own,after,after-60)==[]
        assert cf.bedtime_kinds(bed_state(),{},night_time(7,0,day=13),night_time(7,0,day=13))==[]
        assert cf.bedtime_kinds(bed_state(),{},night_time(12),night_time(12))==[]
def test_night_hours_that_do_not_wrap_midnight():
    assert cf.in_night(3, 0, 6) and not cf.in_night(12, 0, 6) and not cf.in_night(6, 0, 6)
    assert cf.in_night(23, 22, 8) and cf.in_night(7, 22, 8) and not cf.in_night(8, 22, 8)
    assert not any(cf.in_night(h, 24, 0) for h in range(24))
    assert not any(cf.in_night(h, 5, 5) for h in range(24))
def test_notifier_without_stdin_spec_gets_dev_null():
    # Would block for the 60 s timeout if the notifier inherited an open stdin.
    code, out = cf.run([sys.executable, '-c', 'import sys; print(len(sys.stdin.read()))'])
    assert (code, out.strip()) == (0, '0')
    assert cf.run([sys.executable, '-c', 'import sys; print(sys.stdin.read())'], 'hi')[1].strip() == 'hi'
def test_unknown_arguments_refuse_without_sending():
    with patch.object(cf, 'tick') as tick:
        for argv in (['-n'], ['--dryrun'], ['--dry-run', 'x']):
            assert cf.main(argv) == 2
        tick.assert_not_called()

if __name__ == '__main__':
    import inspect, tempfile
    tests = [(name, fn) for name, fn in list(globals().items()) if name.startswith('test_') and callable(fn)]
    for name, test in tests:
        with tempfile.TemporaryDirectory() as tmp:
            test(pathlib.Path(tmp)) if inspect.signature(test).parameters else test()
    print(f'{len(tests)} tests passed; sandbox only')
    import shutil; shutil.rmtree(_TMP)
