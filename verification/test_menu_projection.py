"""Menu boundaries: executed faults must be detected before green is accepted."""
from __future__ import annotations
import dataclasses
import json
import plistlib
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
from tools import menu_snapshot as menus
from core.placement import NodeProfile
from core.hlc import HLC
from core.store import StoreSet
from core.bus import EventBus
from core.hlc import HybridLogicalClock
from core.capabilities import build_registry
from core.authorize import PolicyDecisionPoint,Grant
from core.reconcile import Reconciler,OutboxEntry
from core.executor import Executor


class Menus(unittest.TestCase):
    def test_catalogue_exact(self):
        text=(REPO/'docs/planning/CODEX-BRIEF-MENUS-v2.md').read_text()
        rows=[]
        for line in text.splitlines():
            if line.startswith('| **'):
                cells=[c.strip() for c in line.split('|')[1:-1]]
                if len(cells)==5 and cells[1][:1] in 'ABCD':rows.append((cells[0].strip('*'),cells[2]))
        self.assertEqual([(i['name'],i['what']) for i in menus.CATALOGUE],rows)
        self.assertEqual(len(set(i['id'] for i in menus.CATALOGUE)),68)
        self.assertEqual(sum(i['area']=='main' for i in menus.CATALOGUE),17)

    def test_missing_runtime_is_absent_not_zero(self):
        with tempfile.TemporaryDirectory() as d,patch.object(menus.platform,'system',return_value='fixture'):
            rows=menus.Collector(state=d).collect()
        self.assertEqual(len(rows),68)
        for name in ('Grants','Action outbox','Node profiles','Enrollment','Clock skew'):
            r=next(r for r in rows if r['label']==name)
            self.assertEqual(r['status'],'unavailable');self.assertEqual(r['at_ms'],0)
            self.assertTrue(r['reason']);self.assertGreater(r['ttl_ms'],0)

    def test_observation_and_absence_cannot_be_confused(self):
        item=menus.CATALOGUE[0]
        r=menus.observed(item,'0','real empty registry',100,ttl_ms=20)
        self.assertEqual(r['value'],'0');self.assertEqual(r['at_ms'],100)
        absent=menus.absent(item,checked_at=200)
        self.assertEqual(absent['at_ms'],0);self.assertEqual(absent['checked_at_ms'],200)

    def test_cached_observation_keeps_stamp(self):
        now=[1000];calls=[]
        def runner(argv,timeout):calls.append(argv);return b'data'
        c=menus.Collector(runner=runner,now_ms=lambda:now[0])
        self.assertEqual(c.command(['read'],slow=True)[0],1000)
        now[0]=2000
        self.assertEqual(c.command(['read'],slow=True)[0],1000)
        self.assertEqual(len(calls),1)

    def test_failed_probe_never_uses_previous_value(self):
        data=plistlib.dumps([dict(DesignCapacity=100,AppleRawMaxCapacity=83,CycleCount=1,Temperature=3010)])
        values=iter([data,ValueError('sensor gone')])
        def runner(argv,timeout):
            value=next(values)
            if isinstance(value,Exception):raise value
            return value
        c=menus.Collector(runner=runner)
        out={};c.battery(lambda n,v,s,**kw:out.update({n:(v,kw)}))
        self.assertIn('Battery health',out)
        with self.assertRaises(ValueError):c.battery(lambda *a,**k:None)

    def test_battery_is_raw_and_no_lifetime_prediction(self):
        fixture=[dict(DesignCapacity=8694,AppleRawMaxCapacity=7281,CycleCount=191,Temperature=3066,
                      Serial='DO_NOT_EXPORT',BatteryData={'DailyMaxSoc':79,'DailyMinSoc':12})]
        c=menus.Collector(runner=lambda argv,timeout:plistlib.dumps(fixture))
        out={};c.battery(lambda n,v,s,**kw:out.update({n:dict(value=v,**kw)}))
        self.assertEqual(out['Battery health']['data']['retained_percent'],7281/8694*100)
        self.assertIn('Remaining years UNAVAILABLE',out['Battery health']['details'])
        self.assertNotIn('DO_NOT_EXPORT',json.dumps(out))
        self.assertIn('not configured charge limits',out['Charge policy']['details'])

    def test_io_reset_is_not_negative_rate(self):
        samples=iter([100,10])
        c=menus.Collector(runner=lambda argv,timeout:plistlib.dumps([{'IORegistryEntryID':1,'Statistics':{'Bytes (Read)':next(samples),'Bytes (Write)':0}}]))
        with self.assertRaisesRegex(ValueError,'first sample'):c.io(lambda *a,**k:None)
        with self.assertRaisesRegex(ValueError,'reset'):c.io(lambda *a,**k:None)

    def test_zero_cumulative_drivers_do_not_establish_host_idle(self):
        c=menus.Collector(runner=lambda argv,timeout:plistlib.dumps([{'IORegistryEntryID':1,'Statistics':{'Bytes (Read)':0,'Bytes (Write)':0}}]))
        with self.assertRaisesRegex(ValueError,'coverage is unverified'):c.io(lambda *a,**k:None)
        self.assertIsNone(c.previous_io)

    def test_io_uses_counter_delta_and_measured_duration(self):
        samples=iter([100,300])
        c=menus.Collector(runner=lambda argv,timeout:plistlib.dumps([{'IORegistryEntryID':1,'Statistics':{'Bytes (Read)':next(samples),'Bytes (Write)':0}}]))
        with patch.object(menus.time,'monotonic',side_effect=[5.,7.]):
            with self.assertRaises(ValueError):c.io(lambda *a,**k:None)
            out={};c.io(lambda n,v,s,**kw:out.update(kw))
        self.assertEqual(out['data']['read_bytes_per_s'],100)

    def test_db_readonly_and_hlc_order(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with StoreSet(root/'bus',node_id='fixture') as store:
                store.append('log','a',{'type':'a'},HLC(10,2,'z'))
                store.append('log','b',{'type':'b'},HLC(10,3,'a'))
                c=menus.Collector(state=root)
                self.assertEqual([e['event'] for e in c.events()],['b','a'])
                with self.assertRaises(sqlite3.OperationalError):c.db('state','DELETE FROM leased_domain')
            missing=menus.Collector(state=root/'absent')
            with self.assertRaises(ValueError):missing.db('state','SELECT 1')
            self.assertFalse((root/'absent').exists())

    def test_live_empty_registries_are_real_zero(self):
        with tempfile.TemporaryDirectory() as d:
            with StoreSet(Path(d)/'bus',node_id='fixture') as store:
                bus=EventBus(HybridLogicalClock('fixture'),store,component='fixture')
                reg=build_registry();pdp=PolicyDecisionPoint(bus,reg,now_ms=lambda:100)
                cid=reg.ids()[0]
                pdp.issue(Grant('g','owner',cid,('workspace',),'L2',1234,0))
                rec=Reconciler(bus)
                actor=SimpleNamespace(_registry=reg,_pdp=pdp,_reconciler=rec,_executor=Executor(bus,reg,pdp))
                c=menus.Collector(state=d,context={'actor':actor},now_ms=lambda:100)
                with patch.object(menus.platform,'system',return_value='fixture'):rows=c.collect()
                out={r['label']:r for r in rows}
                self.assertEqual(out['Action outbox']['value'],'0 runtime outbox records')
                self.assertEqual(out['Grants']['data'][0]['expiry_ms'],1234)
                self.assertEqual(out['Capability registry']['status'],'available')

    def test_simulation_is_readonly_and_unknown_stays_unknown(self):
        p=NodeProfile('one','Z1','on_demand',ram_gb=8,storage_gb=40,
                      sustained_tokens_per_sec=999,measured=False,survival_capable=True)
        original=dataclasses.asdict(p)
        result=menus.simulate({'one':p},{'memory':['one']})
        self.assertIsNone(result['comparison'][0]['sustained_tokens_per_sec'])
        self.assertEqual(result['blast'][0]['outcome'],'SurvivalImpossible')
        self.assertEqual(result['blast'][0]['affected_domains'],['memory'])
        self.assertEqual(dataclasses.asdict(p),original)

    def test_clock_interval_reports_uncertainty(self):
        result=menus.clock_interval(dict(node='b',local_send_ms=0,remote_receive_ms=15,remote_send_ms=20,local_receive_ms=25))
        self.assertEqual(result['offset_ms'],5)
        self.assertEqual(result['uncertainty_ms'],10)
        with self.assertRaises(ValueError):menus.clock_interval(dict(node='b',local_send_ms=0,remote_receive_ms=15,remote_send_ms=100,local_receive_ms=25))


if __name__=='__main__':
    if '--negative-control-zero-counters' in sys.argv:
        sys.argv.remove('--negative-control-zero-counters')
        real_io=menus.Collector.io
        def broken_io(self,put):
            try:return real_io(self,put)
            except ValueError as exc:
                if 'coverage is unverified' not in str(exc):raise
                return put('Disk I/O rate','0 MiB/s','unverified driver')
        menus.Collector.io=broken_io
    if '--negative-control' in sys.argv:
        sys.argv.remove('--negative-control')
        real=menus.simulate
        def broken(profiles,assignments):
            out=real(profiles,assignments)
            # Deliberate fault: declared throughput is rendered as measured.
            out['comparison'][0]['sustained_tokens_per_sec']=999
            return out
        menus.simulate=broken
    unittest.main()
