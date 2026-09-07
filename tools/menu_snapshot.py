"""Read-only menu projection. Never instantiate a substitute live registry.

The catalogue is complete even when the fabric is not. Missing runtime objects
produce explicit absence; a fresh empty registry would manufacture a healthy
zero. Sample acquisition runs off the conversation thread. All history is
bounded and identified as a tail; reading a tail cannot prove an event never
happened. No model, network scan, privileged probe, or policy mutation lives here.
"""
from __future__ import annotations

import concurrent.futures
import dataclasses
import json
import math
import platform
import plistlib
import re
import sqlite3
import subprocess
import threading
import tempfile
import time
import tomllib
from collections import deque
from pathlib import Path

from core.hlc import HLC
from core.projection import Reading

REPO = Path(__file__).resolve().parents[1]
CATALOGUE = json.loads((Path(__file__).with_name('menu_catalogue.json')).read_text())
MAX_ITEMS = 68
MAX_RECORDS = 100
MAX_FIELDS = 40
MAX_TEXT = 6000
MAX_COMMAND_BYTES = 2_000_000
MAX_LOG_BYTES = 256_000
MAX_HISTORY = 120
MAX_DB_STEPS = 2000
TTL_MS = 120_000
SLOW_TTL_MS = 600_000
STATE = Path.home() / 'Library' / 'Application Support' / 'VESPER'


def run(argv, timeout=5):
    """Exact argv, checked exit, bounded duration and retained output."""
    if argv == ['/usr/bin/pmset', '-g', 'log']:
        # The public log may exceed the in-memory cap. Spool only command
        # output, then retain its tail; never copy or modify a live store.
        with tempfile.TemporaryFile() as output:
            proc = subprocess.run(argv, stdout=output, stderr=subprocess.DEVNULL,
                                  timeout=timeout, check=False)
            if proc.returncode:
                raise ValueError(f'pmset exited {proc.returncode}')
            size=output.tell();start=max(0,size-MAX_LOG_BYTES);output.seek(start)
            tail=output.read(MAX_LOG_BYTES)
            return tail.split(b'\n',1)[-1] if start else tail
    out = subprocess.run(argv, capture_output=True, timeout=timeout, check=False)
    if out.returncode:
        raise ValueError(f'{Path(argv[0]).name} exited {out.returncode}')
    if len(out.stdout) > MAX_COMMAND_BYTES:
        raise ValueError(f'{Path(argv[0]).name} exceeded the {MAX_COMMAND_BYTES}-byte output limit')
    return out.stdout


def clean(value, depth=0):
    """A closed, small JSON shape. No arbitrary object reprs or credentials."""
    if depth > 5:
        return '… depth limit'
    if value is None or isinstance(value, (str, int, bool)):
        return value[:MAX_TEXT] if isinstance(value, str) else value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (list, tuple)):
        result = [clean(v, depth+1) for v in value[:MAX_RECORDS]]
        if len(value) > MAX_RECORDS:
            result.append(f'… limited to {MAX_RECORDS} of {len(value)} records')
        return result
    if isinstance(value, dict):
        return {str(k)[:200]: clean(v, depth+1) for k, v in list(value.items())[:MAX_FIELDS]}
    return None


def absent(item, reason=None, checked_at=0):
    reading = Reading.unavailable(item['id'], 'menu projection', reason or item['reason'])
    return dict(label=item['name'], id=item['id'], area=item['area'],
                value='UNAVAILABLE', status='unavailable', reason=reading.unavailable_reason,
                source=reading.source, at_ms=0, ttl_ms=TTL_MS, checked_at_ms=checked_at,
                details='', data=None)


def observed(item, value, source, at_ms, *, details='', data=None, ttl_ms=TTL_MS):
    reading = Reading(item['id'], source, value=value,
                      observed_at=HLC(at_ms, 0, 'menu-observer'), ttl_ms=ttl_ms)
    return dict(label=item['name'], id=item['id'], area=item['area'], value=str(reading.value),
                status='available', reason='', source=reading.source,
                at_ms=reading.observed_at.physical_ms, ttl_ms=reading.ttl_ms,
                details=details[:MAX_TEXT], data=clean(data))


class Collector:
    def __init__(self, *, context=None, state=STATE, runner=run, now_ms=None):
        self.context = context or {}
        self.state = Path(state)
        self.runner = runner
        self.now_ms = now_ms or (lambda: int(time.time()*1000))
        self.history = deque(maxlen=MAX_HISTORY)
        self.previous_io = None
        self.cache = {}
        self.previous_work = None

    def command(self, argv, *, slow=False):
        key = tuple(argv)
        stamp = self.now_ms()
        old = self.cache.get(key)
        # The original observation stamp travels with a cached result.
        if slow and old and stamp-old[0] < SLOW_TTL_MS//2:
            if isinstance(old[1], Exception):
                raise old[1]
            return old
        try:
            data = self.runner(argv, timeout=8 if slow else 5)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            if slow:
                self.cache[key] = (stamp, exc)
            raise
        if slow:
            self.cache[key] = (stamp, data)
        return stamp, data

    def db(self, store, query, args=()):
        path = self.state / 'bus' / (store+'.db')
        if not path.is_file():
            raise ValueError(f'{store} store is absent; no empty replacement was created')
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=.2) as conn:
            conn.execute('PRAGMA query_only=ON')
            steps = [0]
            def budget():
                steps[0] += 1
                return int(steps[0] > MAX_DB_STEPS)
            conn.set_progress_handler(budget, 1000)
            return conn.execute(query, args).fetchall()

    def events(self, prefix=''):
        # Full HLC tuple, never just a wall-clock timestamp. Only event metadata
        # is exported; tool arguments, conversation and credential data stay out.
        rows = self.db('log', '''SELECT body, hlc_physical_ms, hlc_logical, hlc_node_id
            FROM records
            ORDER BY hlc_physical_ms DESC, hlc_logical DESC, hlc_node_id DESC LIMIT ?''', (MAX_RECORDS,))
        out=[]
        for body,p,l,n in rows:
            obj=json.loads(body)
            kind=obj.get('type', '')
            if kind.startswith(prefix):
                out.append(dict(event=kind, event_id=obj.get('event_id'), subject=str(obj.get('subject',''))[:120],
                                hlc=dict(physical_ms=p,logical=l,node_id=n)))
        return out

    def collect(self):
        checked=self.now_ms()
        result={i['name']:absent(i,checked_at=checked) for i in CATALOGUE}
        items={i['name']:i for i in CATALOGUE}
        def put(name, value, source, *, at=None, details='', data=None, ttl=TTL_MS):
            result[name]=observed(items[name],value,source,self.now_ms() if at is None else at,
                                  details=details,data=data,ttl_ms=ttl)
        def fail(names, exc):
            for name in names:
                result[name]=absent(items[name],items[name]['reason']+' Probe: '+type(exc).__name__+': '+str(exc)[:300],checked)
        def attempt(names, fn):
            try: fn()
            except (OSError, ValueError, KeyError, TypeError, AttributeError,
                    sqlite3.Error, subprocess.SubprocessError, plistlib.InvalidFileException) as exc:
                fail(names,exc)

        def fabric():
            from core.fabric import load_contract, segments
            contract=load_contract()
            seg=segments(contract)
            put('Attestation state',str(contract.get('attested') is True).lower(),
                'core.fabric.load_contract',details='Governed attestation flag, not a new network attestation. Full-host admission remains fail-closed while false.')
            put('Network segments',f'{len(seg)} declared segment classes','core.fabric.segments',
                data=[dataclasses.asdict(s) for s in seg.values()],details='Declared classes and trust ceilings; no addresses and no claim of observed link quality.')
        attempt(['Attestation state','Network segments'],fabric)

        def contracts():
            from core.placement import load_capability_requirements
            req=load_capability_requirements()
            put('Degradation ladder',f'{len(req)} capability requirements','core.placement.load_capability_requirements',
                data={k:{a:v.get(a) for a in ('survival_core','min_memory_gb','min_storage_gb','min_trust_zone')} for k,v in req.items()},
                details='Governed survival-core and optional-capability requirements in contract order; these are requirements, not measured node capacities.')
            path=REPO/'contracts/policy/governed_surfaces.toml'
            surfaces=tomllib.loads(path.read_text())['surfaces']
            put('Governed surfaces',f'{len(surfaces)} governed surfaces',str(path.relative_to(REPO)),
                data=surfaces,details='Runtime changes require owner review before merge; reviewer enforcement also depends on repository protection.')
        attempt(['Degradation ladder','Governed surfaces'],contracts)

        if platform.system() == 'Darwin':
            attempt(['Battery health','Charge policy','Thermal history'],lambda:self.battery(put))
            attempt(['Memory headroom','Memory pressure band','Platform adapters'],lambda:self.pressure(put))
            attempt(['Compressor & swap'],lambda:self.memory(put))
            attempt(['Owner working set'],lambda:self.processes(put))
            attempt(['Storage & SSD'],lambda:self.storage(put))
            attempt(['Disk I/O rate'],lambda:self.io(put))
            attempt(['Sleep & wake log'],lambda:self.sleep_log(put))
            attempt(['Throttle events'],lambda:self.throttle(put))
            attempt(['Radio state'],lambda:self.radio(put))
            attempt(['Peripherals'],lambda:self.peripherals(put))
        else:
            for name in ('Battery health','Charge policy','Thermal history','Compressor & swap',
                         'Disk I/O rate','Sleep & wake log','Throttle events','Radio state','Peripherals'):
                result[name]=absent(items[name],'This OS adapter does not expose the required observation.',checked)

        attempt(['Control-plane lease'],lambda:self.leases(put))
        attempt(['Live activity stream','Relocation history','Approval history'],lambda:self.logs(put))
        self.live(put,attempt)
        profiles=self.context.get('placement_profiles')
        if profiles:
            attempt(['Survival profile','Blast radius','Migration dry-run','Node comparison'],
                    lambda:self.simulations(put,profiles))
        clock_samples=self.context.get('clock_samples')
        if clock_samples:
            attempt(['Clock skew'],lambda:put('Clock skew','Bounded clock-offset intervals','clock request/response observations',
                data=[clock_interval(s) for s in clock_samples[:MAX_RECORDS]],details='Intervals include round-trip uncertainty. HLC still decides order.'))
        # Palette and comparisons execute in the display; they are not fake OS readings.
        put('Command palette','Command-K · search all 68 surfaces','local menu catalogue',
            details='Opens the selected surface. It never sends terminal commands.')
        return [result[i['name']] for i in CATALOGUE]

    def battery(self,put):
        at,raw=self.command(['/usr/sbin/ioreg','-ar','-c','AppleSmartBattery'])
        entries=plistlib.loads(raw)
        if not entries: raise ValueError('no battery service returned')
        b=entries[0];data=b.get('BatteryData') or {}
        design=b.get('DesignCapacity');full=b.get('AppleRawMaxCapacity');cycles=b.get('CycleCount')
        if not all(isinstance(v,(int,float)) and v>=0 for v in (design,full,cycles)) or not design:
            raise ValueError('missing capacity or cycle counters')
        retained=100*full/design
        put('Battery health',f'{retained:.2f}% raw/design · {cycles} cycles','ioreg AppleSmartBattery',at=at,
            data=dict(raw_full_capacity=full,design_capacity=design,retained_percent=retained,cycles=cycles),
            details='Capacity retention = raw full capacity / design capacity × 100. This differs from the OS health algorithm. Remaining years UNAVAILABLE: a single sample cannot establish a degradation rate.')
        charge={k:b.get(k) for k in ('CurrentCapacity','IsCharging','ExternalConnected')}
        charge.update({k:data.get(k) for k in ('DailyMinSoc','DailyMaxSoc')})
        put('Charge policy',f"charge {b.get('CurrentCapacity','UNAVAILABLE')}%",'ioreg AppleSmartBattery',at=at,data=charge,
            details='DailyMinSoc and DailyMaxSoc are observed charge extrema, not configured charge limits. Configured limit and charging control UNAVAILABLE.')
        # Preserve the raw field until its unit is established by this adapter's
        # evidence. A plausible conversion to degrees is not unit provenance.
        temperature=b.get('Temperature')
        if not isinstance(temperature,(int,float)):raise ValueError('no temperature counter')
        self.history.append(dict(at_ms=at,temperature_raw=temperature))
        put('Thermal history',f'{len(self.history)} raw battery-temperature samples','ioreg AppleSmartBattery.Temperature',at=at,
            data=list(self.history),details=f'Latest {MAX_HISTORY} samples in this publisher session. Raw sensor units retained; Celsius conversion and ambient comparison UNAVAILABLE until the unit is verified. Not CPU temperature.')

    def pressure(self,put):
        from core.host import adapter_for_host
        adapter=adapter_for_host();at=self.now_ms();p=adapter.read_pressure()
        put('Platform adapters',type(adapter).__name__,'core.host.adapter_for_host',at=at,
            details='Signals are translated by the platform adapter. Errors are not nominal.',data=dataclasses.asdict(p))
        if p.memory_available_gb is not None:
            put('Memory headroom',f'{p.memory_available_gb} GiB','core.host.read_pressure',at=at,
                data={'reclaimable_gib':p.memory_available_gb},details='Adapter estimate: free + inactive + speculative pages. Purgeable pages are not added again.')
        if p.memory_pressure_band is not None:
            put('Memory pressure band',str(p.memory_pressure_band),'core.host.read_pressure',at=at,
                data={'band':p.memory_pressure_band},details='Kernel band only. Never multiplied by memory size or converted to gigabytes.')

    def memory(self,put):
        at,raw=self.command(['/usr/bin/vm_stat'])
        text=raw.decode();page=int(re.search(r'page size of (\d+) bytes',text)[1])
        match=re.search(r'Pages occupied by compressor:\s*(\d+)',text)
        if not match:raise ValueError('compressor count missing')
        _,swap=self.command(['/usr/sbin/sysctl','-n','vm.swapusage'])
        sm=re.search(r'used\s*=\s*([\d.]+)([KMG])',swap.decode())
        if not sm:raise ValueError('swap accounting missing')
        compressed=int(match[1])*page;swap_bytes=float(sm[1])*{'K':1024,'M':1024**2,'G':1024**3}[sm[2]]
        put('Compressor & swap',f'{compressed/1024**3:.2f} GiB compressed · {swap_bytes/1024**3:.2f} GiB swap',
            'vm_stat; sysctl vm.swapusage',at=at,data=dict(compressor_bytes=compressed,swap_bytes=swap_bytes),
            details='Resident compressor footprint and allocated swap. Neither is cumulative SSD wear.')

    def processes(self,put):
        at,raw=self.command(['/bin/ps','-axo','pid=,rss=,comm='])
        processes=[]
        for line in raw.decode(errors='replace').splitlines():
            parts=line.strip().split(None,2)
            if len(parts)==3 and parts[0].isdigit() and parts[1].isdigit():
                # Basename only: no argument vectors, private paths or document names.
                processes.append(dict(pid=int(parts[0]),rss_bytes=int(parts[1])*1024,process=Path(parts[2]).name))
        processes.sort(key=lambda p:p['rss_bytes'],reverse=True)
        put('Owner working set',f'{len(processes)} processes observed','ps resident set size',at=at,
            data=processes[:20],details='Top 20 RSS values across host processes. Shared pages can be counted in multiple processes; this is not unique physical memory or energy attribution.')

    def storage(self,put):
        at,raw=self.command(['/usr/sbin/diskutil','info','-plist','/'],slow=True)
        d=plistlib.loads(raw)
        fields={k:d.get(k,'UNAVAILABLE') for k in ('APFSContainerSize','APFSContainerFree','SMARTStatus','SolidState','TRIMSupport')}
        free=fields['APFSContainerFree']
        put('Storage & SSD',f'{free/1024**3:.2f} GiB container free' if isinstance(free,int) else 'Container free space UNAVAILABLE',
            'diskutil info -plist /',at=at,ttl=SLOW_TTL_MS,data=fields,
            details='APFS container free space; snapshot FreeSpace is not usable headroom. Missing TRIM and lifetime-write counters remain UNAVAILABLE. SMART is the OS-reported status, not a lifetime guarantee.')

    def io(self,put):
        at,raw=self.command(['/usr/sbin/ioreg','-ar','-c','IOBlockStorageDriver'])
        services=plistlib.loads(raw)
        counts={}
        for service in services:
            stats=service.get('Statistics') or {}
            if all(isinstance(stats.get(k),int) for k in ('Bytes (Read)','Bytes (Write)')):
                counts[str(service.get('IORegistryEntryID'))]=(stats['Bytes (Read)'],stats['Bytes (Write)'])
        if not counts:raise ValueError('no byte counters')
        if any(x < 0 for pair in counts.values() for x in pair):
            self.previous_io=None
            raise ValueError('invalid negative storage counter')
        if not any(x > 0 for pair in counts.values() for x in pair):
            # These drivers can exist without covering the active storage.
            # A host that has booted and read this code has done I/O; all-zero
            # lifetime counters do not establish a whole-host idle reading.
            self.previous_io=None
            raise ValueError('enumerated drivers expose only zero cumulative counters; active-storage coverage is unverified')
        mono=time.monotonic();old=self.previous_io;self.previous_io=(mono,counts)
        if not old:raise ValueError('first sample retained; waiting for the next sample')
        elapsed=mono-old[0]
        if elapsed<=0 or counts.keys()!=old[1].keys():raise ValueError('storage inventory changed; baseline reset')
        reads=sum(v[0]-old[1][k][0] for k,v in counts.items());writes=sum(v[1]-old[1][k][1] for k,v in counts.items())
        if any(v[j]<old[1][k][j] for k,v in counts.items() for j in (0,1)):
            raise ValueError('counter reset; baseline reset')
        put('Disk I/O rate',f'{reads/elapsed/1024**2:.2f} MiB/s read · {writes/elapsed/1024**2:.2f} MiB/s write',
            'IOBlockStorageDriver counters / monotonic interval',at=at,
            data=dict(read_bytes_per_s=reads/elapsed,write_bytes_per_s=writes/elapsed,interval_s=elapsed,
                      driver_read_bytes=sum(v[0] for v in counts.values()),driver_write_bytes=sum(v[1] for v in counts.values())),
            details='Sum of enumerated driver counters over the measured interval. Not lifetime NAND writes; controller wear and endurance ratings UNAVAILABLE.')

    def sleep_log(self,put):
        at,raw=self.command(['/usr/bin/pmset','-g','log'],slow=True)
        lines=[line for line in raw.decode(errors='replace').splitlines() if re.search(r'\b(Sleep|Wake|DarkWake)\b',line)]
        if not lines:raise ValueError('no sleep/wake entries returned')
        put('Sleep & wake log',f'{min(len(lines),MAX_RECORDS)} recent power-log lines','pmset -g log',at=at,ttl=SLOW_TTL_MS,
            data=lines[-MAX_RECORDS:],details='OS log order, retained as received; no cross-node ordering is inferred. Limited to the latest 100 matching lines.')

    def throttle(self,put):
        at,raw=self.command(['/usr/bin/pmset','-g','therm'],slow=True)
        text=raw.decode(errors='replace').strip()
        if not text or 'Error:' in text:raise ValueError('performance warning status unavailable')
        put('Throttle events','OS performance-warning report','pmset -g therm',at=at,ttl=SLOW_TTL_MS,
            details=text+' This is the OS recorded status, not a complete throttle timeline. Workload correlation UNAVAILABLE.')

    def radio(self,put):
        at,raw=self.command(['/usr/sbin/system_profiler','SPBluetoothDataType','-json'],slow=True)
        doc=json.loads(raw);controllers=doc.get('SPBluetoothDataType') or []
        states=[]
        for c in controllers[:MAX_RECORDS]:
            props=c.get('controller_properties') or {}
            states.append({'bluetooth_power':props.get('controller_state','UNAVAILABLE')})
        if not states:raise ValueError('no controller states')
        put('Radio state','Bluetooth controller state','system_profiler SPBluetoothDataType',at=at,ttl=SLOW_TTL_MS,
            data=states,details='Wi-Fi power, radio watts, and wake attribution UNAVAILABLE. Controller state is not power cost; addresses and paired-device identities are omitted.')

    def peripherals(self,put):
        at,raw=self.command(['/usr/sbin/system_profiler','SPUSBDataType','-json'],slow=True)
        doc=json.loads(raw);inventory=[]
        def visit(items,depth=0):
            if depth>5:return
            for item in items[:MAX_RECORDS]:
                if len(inventory)>=MAX_RECORDS:return
                row={k:item[k] for k in ('_name','bus_power','bus_power_used','extra_current_used') if k in item}
                if row:inventory.append(row)
                visit(item.get('_items') or [],depth+1)
        visit(doc.get('SPUSBDataType') or [])
        if not inventory:raise ValueError('no USB inventory was returned')
        put('Peripherals',f'{len(inventory)} USB inventory entries','system_profiler SPUSBDataType',at=at,ttl=SLOW_TTL_MS,
            data=inventory,details='Reported USB current budgets are not measured watts. Device wake assertions and non-USB peripherals UNAVAILABLE. Serial numbers are not exported.')

    def leases(self,put):
        rows=self.db('state','SELECT domain, epoch, holder, state FROM leased_domain LIMIT ?', (MAX_RECORDS,))
        put('Control-plane lease',f'{sum(r[2] is not None for r in rows)} held domains','state.leased_domain (read-only)',
            data=[dict(domain=d,epoch=e,holder=h,state=s) for d,e,h,s in rows],
            details='Durable holder records and fencing epochs. This reader does not renew or self-promote, and does not establish current quorum or lease freshness.')

    def logs(self,put):
        events=self.events()
        put('Live activity stream',f'{len(events)} recent event headers','active log store, HLC order',
            data=events,details='Latest 100 event headers from the active log segment. Archived segments and event payloads are excluded.')
        relocation=[e for e in events if e['event'].startswith('placement.')]
        if relocation:put('Relocation history',f'{len(relocation)} placement events in tail','active log store',data=relocation,
                          details='Bounded active-segment tail only; absence here is not evidence that no relocation occurred.')
        approvals=[e for e in events if e['event']=='act.resumed']
        if approvals:put('Approval history',f'{len(approvals)} approved resumptions in tail','active log store',data=approvals,
                         details='Owner-approved act.resumed events only; outbox confirmations and automatic elevations are not approvals. This is not a complete approval ledger. Withdrawal UNAVAILABLE: no public revoke operation exists.')

    def live(self,put,attempt):
        ctx=self.context
        devices=ctx.get('devices')
        if devices is not None:
            def device_rows():
                profiles=devices.all()
                put('Endpoints',f'{len(profiles)} registered profiles','live DeviceRegistry.all',data=profiles)
                put('Remote surfaces',f'{len(profiles)} registered profiles','live DeviceRegistry.all',data=profiles,
                    details='Registry profiles only. Opening or pairing a remote surface UNAVAILABLE: no transport command is exposed.')
                put('Node profiles',f'{len(profiles)} registered profiles','live DeviceRegistry.all',data=profiles,
                    details='Only measured capability values are returned by the registry. Omitted throughput and resource budgets remain UNAVAILABLE.')
                put('Key & identity state',f'{len(profiles)} key-storage profiles','live DeviceRegistry.all',
                    data=[{k:p.get(k) for k in ('node_id','key_storage_class','trust_zone_ceiling')} for p in profiles],
                    details='Storage classes and ceilings only; no keys or secrets are read. A ceiling is not an effective fabric zone.')
                domains=('tasks','world','memory','devices','policy','autonomy_queue','alarms')
                assignments={d:devices.placement(d) for d in domains}
                put('Placement decisions','Current registry assignments','live DeviceRegistry.placement',data=assignments,
                    details='Assignments only. Winning score, rejected alternatives, and effective fabric-admission reasons UNAVAILABLE without a placement decision snapshot.')
            attempt(['Endpoints','Remote surfaces','Node profiles','Key & identity state','Placement decisions'],device_rows)
        actor=ctx.get('actor')
        if actor is not None:
            def actor_rows():
                # Read under the owning locks. There are no public snapshot
                # methods yet; adding them must not change authorization logic.
                reg=actor._registry
                with reg._lock:
                    caps=[reg.get(cid) for cid in reg.ids()[:MAX_RECORDS]]
                    rows=[dict(capability=c.capability_id,reversibility=c.reversibility,
                               external_effect=c.external_effect,confirmation=c.requires_owner_confirmation,
                               rules=[dict(level=r.level,condition=r.name) for r in c.rules[:MAX_FIELDS]]) for c in caps]
                put('Capability registry',f'{len(reg.ids())} registered capabilities','live CapabilityRegistry',data=rows,
                    details='Levels depend on action arguments and rule conditions; no constant level is substituted.')
                pdp=actor._pdp
                with pdp._lock:
                    grants=list(pdp._grants.values())
                    grant_rows=[{**g.to_dict(),'expiry_ms':g.expiry_ms,'lease_epoch':g.lease_epoch,
                                 'expired':g.expiry_ms<=self.now_ms()} for g in grants[:MAX_RECORDS]]
                put('Grants',f'{len(grants)} grant records','live PolicyDecisionPoint',data=grant_rows,
                    details='Records include consumed and expired grants; they are not all usable. Editing and revocation UNAVAILABLE on this bridge.')
                rec=actor._reconciler
                with rec._lock:
                    entries=list(rec._entries.values())
                    outbox=[e.to_dict() for e in entries[:MAX_RECORDS]]
                put('Action outbox',f'{len(entries)} runtime outbox records','live Reconciler',data=outbox,
                    details='Current process registry only, not a reconstructed full durable outbox. No side effect is retried from this panel.')
                put('Retry policy','Probe uncertain effects before retry','core.reconcile',
                    data={'states':list(__import__('core.reconcile',fromlist=['OUTBOX_STATES']).OUTBOX_STATES)},
                    details='INTENT before call may replay; uncertain effects require a registered probe. Non-reconcilable effects escalate. Per-task-class policy editor UNAVAILABLE.')
                ex=actor._executor
                with ex._lock:
                    comps=list(ex._compensators)
                put('Compensation',f'{len(comps)} registered compensators','live Executor',data=comps,
                    details='Bound undo implementations, not a guarantee that every in-flight action can be undone. In-flight compensation plans UNAVAILABLE.')
            attempt(['Capability registry','Grants','Action outbox','Retry policy','Compensation'],actor_rows)
        autonomy=ctx.get('autonomy')
        if autonomy is not None:
            def auto_rows():
                with autonomy._lock:
                    data=dict(ticks=autonomy.ticks,registered=autonomy.registry_report(),
                              recent_firings=[{'trigger_id':x.get('trigger_id')} for x in list(autonomy.fired)[-MAX_RECORDS:]],
                              dropped_history=autonomy.dropped_history)
                put('Autonomy queue',f'{data["ticks"]} evaluated ticks','live AutonomyLoop',data=data,
                    details='Trigger registry and recent firings. The runtime exposes no durable pending-intent queue snapshot; firings must not be read as pending actions.')
            attempt(['Autonomy queue'],auto_rows)
        verifier=ctx.get('verifier')
        if verifier is not None:
            def verify_rows():
                with verifier._lock:
                    verdicts=[dict(task=key[0],**v.to_dict()) for key,v in list(verifier._cache.items())[-MAX_RECORDS:]]
                put('Verification state',f'{len(verdicts)} retained verdicts','live Verifier',data=verdicts,
                    details='Verdicts are tied to output hashes; self-model verdicts cannot accept work. This is the bounded live cache, not a claim that the whole system is verified.')
            attempt(['Verification state'],verify_rows)
        bench=ctx.get('bench')
        if bench is not None:
            def work_rate():
                commands=bench.state().get('commands') or []
                completed={str(c.get('command_id') or c.get('id')) for c in commands if c.get('exit_code') == 0}
                now=time.monotonic();old=self.previous_work;self.previous_work=(now,completed)
                if old is None or now<=old[0]:return
                count=len(completed-old[1]);interval=now-old[0]
                put('Work rate',f'{count} observed command completions / {interval:.1f}s','live Workbench command tail',
                    data=dict(completions=count,interval_s=interval,observed_per_minute=count*60/interval),
                    details='Successful commands newly observed between samples, not model token throughput or verified task success. Bounded workbench tail can omit completions between samples.')
            attempt(['Work rate'],work_rate)
        interlock=ctx.get('interlock')
        if interlock is not None:
            # Status is kept unavailable as an action. It must never masquerade
            # as an independent STOP button simply because permission is readable.
            pass

    def simulations(self,put,profiles):
        from core.placement import survival_profile
        profiles=dict(list(profiles.items())[:MAX_RECORDS])
        data=simulate(profiles,self.context.get('assignments') or {})
        put('Blast radius','Simulation · remove each node','core.placement; menu simulation',data=data['blast'],
            details='Read-only scenario evaluation. No node is stopped and no assignment is written.')
        put('Migration dry-run','Simulation · candidate survival sets','core.placement.survival_profile',data=data['migration'],
            details='Per-destination capacity/trust evaluation. Does not predict transfer time or perform migration.')
        put('Survival profile','Simulation · current measured profiles','core.placement.survival_profile',data=data['migration'])
        if len(profiles)>=2:
            put('Node comparison',f'{len(profiles)} measured profile records','enrolled placement profiles',data=data['comparison'],
                details='Side by side on recorded axes. UNKNOWN throughput stays absent.')


def simulate(profiles,assignments):
    """Use the existing placement algorithm with no bus and no write path."""
    from core.placement import Placement, survival_profile
    placement=Placement()
    blast=[];migration=[];comparison=[]
    for nid,p in list(profiles.items())[:MAX_RECORDS]:
        remaining={k:v for k,v in profiles.items() if k!=nid}
        decision=placement.decide(reachable=remaining,current=nid)
        blast.append(dict(removed=nid,affected_domains=[d for d,hosts in assignments.items() if nid in hosts],
                          outcome=type(decision).__name__,detail=dataclasses.asdict(decision)))
        migration.append(dict(destination=nid,profile=dataclasses.asdict(survival_profile(p))))
        fields=dataclasses.asdict(p)
        if not p.measured:fields['sustained_tokens_per_sec']=None
        comparison.append(fields)
    return dict(blast=blast,migration=migration,comparison=comparison)


def clock_interval(sample):
    """NTP-style offset interval from one same-request exchange, not a rank."""
    t0,t1,t2,t3=(sample[k] for k in ('local_send_ms','remote_receive_ms','remote_send_ms','local_receive_ms'))
    if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in (t0,t1,t2,t3)):
        raise ValueError('invalid clock sample')
    if t3-t0<0 or t2-t1<0:raise ValueError('clock moved backward during exchange')
    rtt=(t3-t0)-(t2-t1)
    if rtt<0:raise ValueError('invalid exchange duration')
    offset=((t1-t0)+(t2-t3))/2
    return dict(node=sample['node'],offset_ms=offset,uncertainty_ms=rtt/2,
                low_ms=offset-rtt/2,high_ms=offset+rtt/2)


_collector=None
_pool=None
_future=None
_last=None
_guard=threading.Lock()


def cached_rows(context=None):
    """Do not put slow OS commands on the runtime's conversation thread."""
    global _collector,_pool,_future,_last
    with _guard:
        if _collector is None:
            _collector=Collector(context=context)
            _pool=concurrent.futures.ThreadPoolExecutor(max_workers=1,thread_name_prefix='menu-readings')
        if _future is not None and _future.done():
            try:_last=_future.result()
            except Exception as exc:
                _last=[absent(i,'Menu acquisition failed: '+type(exc).__name__,int(time.time()*1000)) for i in CATALOGUE]
            _future=None
        if _future is None:
            _future=_pool.submit(_collector.collect)
        return _last or [absent(i,'First menu observation is still being acquired.',int(time.time()*1000)) for i in CATALOGUE]
