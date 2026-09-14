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
# How far a published power figure may sit from voltage x current in the same
# sample before its unit counts as unproven. Measured agreement on this Mac,
# 2026-09-14: 7455 mW against 11400 mV x 654 mA = 7455.6 mW.
POWER_AGREEMENT = 0.10
# The numeric readings Before/after compares: (row, data key, scale, unit).
BASELINE_KEYS = (('Power draw', 'system_load_mw', 1/1000, 'W'),
                 ('Memory headroom', 'reclaimable_gib', 1, 'GiB'),
                 ('Compressor & swap', 'compressor_bytes', 1/1024**3, 'GiB'))
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


def project_file(rel):
    """A file from the project, found from the repo or, inside the bundle, from
    the project root the build recorded in place.toml. None when neither has it."""
    p=REPO/rel
    if p.is_file():return p
    try:
        root=tomllib.loads((REPO/'place.toml').read_text(encoding='utf-8')).get('project_root')
    except (OSError,ValueError):
        return None
    q=Path(root)/rel if root else None
    return q if q is not None and q.is_file() else None


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
        self.baseline = None
        self.power_unit_proven_at = None

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
            attempt(['Power draw'],lambda:self.power(put))
            attempt(['Costing me now','Process energy'],lambda:self.energy(put))
            attempt(['Display power'],lambda:self.display(put))
            attempt(['Fan & acoustics'],lambda:self.thermal_level(put))
        else:
            for name in ('Battery health','Charge policy','Thermal history','Compressor & swap',
                         'Disk I/O rate','Sleep & wake log','Throttle events','Radio state','Peripherals'):
                result[name]=absent(items[name],'This OS adapter does not expose the required observation.',checked)

        attempt(['Control-plane lease'],lambda:self.leases(put))
        attempt(['Live activity stream','Relocation history','Approval history'],lambda:self.logs(put))
        self.live(put,attempt)
        devices=self.context.get('devices')
        if devices is not None:
            attempt(['Enrollment','Node roles','Trust zones','Onboarding wizard','Behaviour on / off this Mac'],
                    lambda:self.fabric_rows(put,devices))
        attempt(['Maintenance actions'],lambda:self.maintenance(put))
        attempt(['Consent channel policy'],lambda:self.consent_policy(put))
        profiles=self.context.get('placement_profiles')
        if not profiles and devices is not None:
            try:
                profiles=self.registry_profiles(devices,result)
            except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError) as exc:
                profiles=None
                fail(['Survival profile','Blast radius','Migration dry-run'],exc)
        if profiles:
            attempt(['Survival profile','Blast radius','Migration dry-run','Node comparison'],
                    lambda:self.simulations(put,profiles))
        clock_samples=self.context.get('clock_samples')
        if clock_samples:
            attempt(['Clock skew'],lambda:put('Clock skew','Bounded clock-offset intervals','clock request/response observations',
                data=[clock_interval(s) for s in clock_samples[:MAX_RECORDS]],details='Intervals include round-trip uncertainty. HLC still decides order.'))
        # THE MAIN DESTINATIONS ARE CARDS THAT MANAGE (core/menu_cards.py). A
        # catalogue row for one of them still read UNAVAILABLE with the excuse
        # the card had already retired -- "no revoke command" beside a card whose
        # revoke button works. Only rows nothing else produced are filled, so a
        # live reading is never replaced by a card's summary.
        try:
            self.destinations(put,result)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error) as exc:
            for item in CATALOGUE:
                if item['area']=='main' and result[item['name']]['status']=='unavailable':
                    result[item['name']]=absent(item,item['reason']+' Card: '+type(exc).__name__+': '+str(exc)[:200],checked)
        attempt(['Before/after'],lambda:self.before_after(put,result))
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
        state=('charging' if charge.get('IsCharging') else
               'on the adapter, not charging' if charge.get('ExternalConnected') else 'on battery')
        put('Charging schedule',f"macOS decides, not VESPER · today {charge.get('DailyMinSoc')}–{charge.get('DailyMaxSoc')}% · {state}",
            'ioreg AppleSmartBattery',at=at,data=charge,
            details='VESPER sets no charging schedule: charging control would need a governed host action that does not exist, so macOS decides when to charge. The day\'s observed charge range is the evidence of what it did.')
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
        # SPUSBHostDataType IS WHAT THIS OS ANSWERS. The row asked SPUSBDataType
        # only, got no inventory, and read "no public peripheral inventory" while
        # the host data type listed three USB buses (2026-09-14, macOS 26).
        doc=None;source=None;at=0
        for dtype in ('SPUSBHostDataType','SPUSBDataType'):
            try:
                at,raw=self.command(['/usr/sbin/system_profiler',dtype,'-json'],slow=True)
            except (OSError,ValueError,subprocess.SubprocessError):
                continue
            doc=json.loads(raw)
            if doc.get(dtype):
                source=dtype;break
        if not source:raise ValueError('neither USB data type returned an inventory')
        inventory=[];counts={'buses':0,'devices':0}
        def visit(items,depth=0):
            if depth>5:return
            for item in items[:MAX_RECORDS]:
                if len(inventory)>=MAX_RECORDS:return
                counts['buses' if depth==0 else 'devices']+=1
                row={k:item[k] for k in ('_name','USBKeyHardwareType','bus_power','bus_power_used','extra_current_used') if k in item}
                row['depth']=depth
                inventory.append(row)
                visit(item.get('_items') or [],depth+1)
        visit(doc.get(source) or [])
        put('Peripherals',f"{counts['devices']} USB device(s) on {counts['buses']} bus(es)",f'system_profiler {source}',at=at,ttl=SLOW_TTL_MS,
            data=inventory,details='Buses and the devices on them. Reported USB current budgets are not measured watts; device wake assertions and non-USB peripherals are not in this inventory. Serial numbers are not exported.')

    def power(self,put):
        # WATTS WITHOUT ROOT, AND THE UNIT PROVEN IN THE SAME SAMPLE. The battery
        # controller publishes `PowerTelemetryData.SystemLoad`. On battery it must
        # equal Voltage x InstantAmperage from the same service; on the adapter,
        # SystemPowerIn must equal SystemVoltageIn x SystemCurrentIn. A figure is
        # published only when it does -- a plausible number is not a unit.
        at,raw=self.command(['/usr/sbin/ioreg','-ar','-c','AppleSmartBattery'])
        entries=plistlib.loads(raw)
        if not entries:raise ValueError('no battery service returned')
        b=entries[0];t=b.get('PowerTelemetryData') or {}
        load=t.get('SystemLoad')
        if not isinstance(load,int) or load<=0:raise ValueError('PowerTelemetryData.SystemLoad is absent or zero')
        external=bool(b.get('ExternalConnected'))
        if external:
            volts,amps,claimed,label=t.get('SystemVoltageIn'),t.get('SystemCurrentIn'),t.get('SystemPowerIn'),'adapter in'
        else:
            amps=b.get('InstantAmperage',b.get('Amperage'))
            # A signed current published as an unsigned 64-bit integer: 2**64-654 is -654 mA.
            if isinstance(amps,int) and amps>=2**63:amps-=2**64
            volts,amps,claimed,label=b.get('Voltage'),(-amps if isinstance(amps,int) else amps),load,'battery out'
        if not all(isinstance(v,int) and v>0 for v in (volts,amps,claimed)):
            raise ValueError(f'the {label} cross-check has no voltage, current or power in this sample')
        product=volts*amps/1000
        disagreement=abs(product-claimed)/claimed
        # THE UNIT IS PROVEN ONCE; A SAMPLE CAN STILL STRADDLE A LOAD SWING. The
        # controller refreshes the power figure and the current at different
        # instants: live on 2026-09-14 one sample read 19336 mW against 23204 mW
        # (20%) during a build, and the next 20686 against 20252 (2%). A unit
        # does not change between samples, so once one agrees the figure is
        # published with each sample's own disagreement recorded; until one
        # agrees, nothing is.
        if disagreement<=POWER_AGREEMENT and self.power_unit_proven_at is None:
            self.power_unit_proven_at=at
        if self.power_unit_proven_at is None:
            raise ValueError(f'{label} power {claimed} disagrees with voltage x current {product:.0f} by {disagreement:.0%}; the unit is not proven yet')
        value=f'{load/1000:.2f} W whole machine'
        if external:value+=f' · {claimed/1000:.2f} W from the adapter'
        put('Power draw',value,'ioreg AppleSmartBattery.PowerTelemetryData',at=at,
            data=dict(system_load_mw=load,external_power=external,unit_proven_at_ms=self.power_unit_proven_at,
                      cross_check=dict(of=label,voltage_mv=volts,current_ma=amps,claimed_mw=claimed,
                                       product_mw=round(product,1),disagreement=round(disagreement,4))),
            details='Whole-machine load from the battery controller, cross-checked against voltage × current from the same service in this sample. The split into compute versus everything else needs powermetrics, which needs root, and is not attempted.')

    def energy(self,put):
        # APPLE'S ENERGY-IMPACT SCORE -- the number Activity Monitor shows -- and
        # NOT WATTS. `top` computes it without root. Its first sample has no
        # interval behind it and reads 0.0 for every process (2026-09-14), so only
        # the LAST sample counts; a parser that took the first would rank nothing.
        at,raw=self.command(['/usr/bin/top','-l','2','-n','15','-stats','pid,command,power','-o','power'])
        blocks=[];current=None
        for line in raw.decode(errors='replace').splitlines():
            if line.startswith('PID'):
                current=[];blocks.append(current);continue
            m=re.match(r'\s*(\d+)\s+(.*?)\s+(\d+(?:\.\d+)?)\s*$',line) if current is not None else None
            if m:current.append(dict(pid=int(m[1]),process=m[2].strip()[:40],energy_impact=float(m[3])))
        if len(blocks)<2:raise ValueError('top returned fewer than two samples; the first has no interval behind it')
        rows=sorted(blocks[-1],key=lambda r:r['energy_impact'],reverse=True)
        if not rows:raise ValueError('the last sample listed no processes')
        lead=' · '.join(f"{r['process']} {r['energy_impact']:.1f}" for r in rows[:3])
        put('Costing me now',lead,'top -l 2 -stats power (last sample)',at=at,data=rows[:10],
            details="Apple's energy-impact score over the last second, highest first: a relative score, the one Activity Monitor shows, not watts. Whole-machine watts are on Power draw.")
        put('Process energy',f"{sum(1 for r in rows if r['energy_impact']>0)} of {len(rows)} sampled processes drawing",
            'top -l 2 -stats power (last sample)',at=at,data=rows,
            details='Per-process energy impact, ranked. Relative, not watts: per-process watts need powermetrics, which needs root, and is not attempted.')

    def display(self,put):
        # THE BACKLIGHT'S OWN NUMBERS, published by its driver without root:
        # the brightness setting, luminance in milli-nits and the backlight
        # current in microamps (2026-09-14: 32768/65536, 381794 mnits, 3199 µA).
        # Watts for the display alone are not published.
        at,raw=self.command(['/usr/sbin/ioreg','-ar','-k','IODisplayParameters'])
        def find(node,depth=0):
            if depth>8 or not isinstance(node,dict):return None
            p=node.get('IODisplayParameters')
            if isinstance(p,dict) and isinstance(p.get('brightness'),dict):return p
            for child in node.get('IORegistryEntryChildren') or []:
                got=find(child,depth+1)
                if got:return got
            return None
        params=next((p for p in (find(e) for e in plistlib.loads(raw) or []) if p),None)
        if params is None:raise ValueError('no display publishes brightness parameters')
        def part(key):
            d=params.get(key) or {}
            v,lo,hi=d.get('value'),d.get('min'),d.get('max')
            return (v,lo,hi) if all(isinstance(x,int) for x in (v,lo,hi)) and hi>lo else None
        br=part('brightness')
        if br is None:raise ValueError('brightness carries no value, min and max')
        value=f'brightness {100*(br[0]-br[1])/(br[2]-br[1]):.0f}%'
        nits=part('BrightnessMilliNits');micro=part('BrightnessMicroAmps')
        if nits:value+=f' · {nits[0]/1000:.0f} nits'
        if micro:value+=f' · backlight {micro[0]/1000:.1f} mA'
        put('Display power',value,'ioreg IODisplayParameters',at=at,
            data={k:params.get(k) for k in ('brightness','BrightnessMilliNits','BrightnessMicroAmps')},
            details='The built-in backlight as its driver reports it: the setting, the luminance and the backlight current. Display watts are not published separately; whole-machine watts are on Power draw, so the cost of a brightness change can be measured there.')

    def thermal_level(self,put):
        # THE OS'S OWN THERMAL AND PERFORMANCE WARNING STATE -- what the fan
        # answers to. Fan RPM sits behind the SMC and is not read here.
        at,raw=self.command(['/usr/bin/pmset','-g','therm'],slow=True)
        text=raw.decode(errors='replace').strip()
        if not text or 'Error:' in text:raise ValueError('pmset -g therm returned no status')
        levels=dict(re.findall(r'([A-Za-z_]+)\s*=\s*(\d+)',text))
        quiet=('No thermal warning level has been recorded' in text
               and 'No performance warning level has been recorded' in text)
        value=('no thermal or performance warning' if quiet and not levels
               else ' · '.join(f'{k} {v}' for k,v in levels.items()) or text.splitlines()[0][:120])
        put('Fan & acoustics',value,'pmset -g therm',at=at,ttl=SLOW_TTL_MS,data=dict(levels=levels,report=text[:600]),
            details='The thermal and performance warning levels macOS records -- the state the fan responds to. Fan RPM is held by the SMC and is not read by this publisher.')

    def destinations(self,put,result):
        from core.menu_cards import cards
        deck=cards(None)
        for item in CATALOGUE:
            if item['area']!='main' or result[item['name']]['status']!='unavailable':continue
            card=deck.get(item['id']) or {}
            rows=card.get('rows') or []
            if not rows:continue
            acts=[a.get('label') for a in (card.get('actions') or [])]
            put(item['name'],' · '.join(f"{r.get('label')}: {r.get('value')}" for r in rows[:2])[:240],
                'core.menu_cards · '+str(rows[0].get('source') or 'card'),data=dict(rows=rows,actions=acts),
                details=str(card.get('summary') or '')+(f' Managed from its card: {len(acts)} action(s).' if acts else ''))

    def before_after(self,put,result):
        # A REAL BEFORE AND AFTER. The first numeric readings this publisher took
        # are the baseline and every later collection is compared against them.
        now={}
        for name,key,scale,unit in BASELINE_KEYS:
            row=result.get(name) or {}
            d=row.get('data') if row.get('status')=='available' else None
            if isinstance(d,dict) and isinstance(d.get(key),(int,float)) and not isinstance(d.get(key),bool):
                now[name]=(d[key]*scale,unit,row['at_ms'])
        if not now:raise ValueError('no numeric reading was available to compare')
        if self.baseline is None:self.baseline=now
        pairs=[(n,self.baseline[n],now[n]) for n in now if n in self.baseline]
        if not pairs:raise ValueError('the baseline shares no reading with this collection')
        put('Before/after',' · '.join(f'{n.lower()} {b[0]:.2f}→{c[0]:.2f} {c[1]}' for n,b,c in pairs),
            'this publisher: its first reading against its latest',
            data=[dict(reading=n,before=b[0],after=c[0],unit=c[1],before_at_ms=b[2],after_at_ms=c[2]) for n,b,c in pairs],
            details='Before is the first reading this publisher took after VESPER started; after is the latest. To measure a change you make, note the after value, make the change, and read it again a minute later.')

    def leases(self,put):
        rows=self.db('state','SELECT domain, epoch, holder, state FROM leased_domain LIMIT ?', (MAX_RECORDS,))
        put('Control-plane lease',f'{sum(r[2] is not None for r in rows)} held domains','state.leased_domain (read-only)',
            data=[dict(domain=d,epoch=e,holder=h,state=s) for d,e,h,s in rows],
            details='Durable holder records and fencing epochs. This reader does not renew or self-promote, and does not establish current quorum or lease freshness.')

    def logs(self,put):
        events=self.events()
        put('Live activity stream',f'{len(events)} recent event headers','active log store, HLC order',
            data=events,details='Latest 100 event headers from the active log segment. Archived segments and event payloads are excluded.')
        # COUNTED BY KIND ACROSS THE ACTIVE STORE, like approvals below: the tail
        # held no placement event and the row read UNAVAILABLE over 358 of them.
        relocation=[e for e in events if e['event'].startswith('placement.')]
        by_kind=dict(self.db('log',"SELECT kind, count(*) FROM records WHERE kind >= 'placement.' AND kind < 'placement/' GROUP BY kind"))
        put('Relocation history',
            (f"{sum(by_kind.values())} placement events: "+', '.join(f"{k.split('.',1)[1]} {n}" for k,n in sorted(by_kind.items()))
             if by_kind else 'no placement events recorded'),
            'active log store, kind placement.* (indexed count)',data=dict(by_kind=by_kind,recent=relocation),
            details='Every placement event in the active log segment, counted by kind; archived segments are not counted.')
        # COUNTED ACROSS THE WHOLE ACTIVE STORE, not read off the 100-record
        # tail. Approvals are rare and the log is not, so the tail held none for
        # days and the row read UNAVAILABLE -- but "none in the tail" is not "none
        # approved". `kind` is indexed, so the count costs one index range.
        approvals=[e for e in events if e['event']=='act.resumed']
        total=self.db('log',"SELECT count(*) FROM records WHERE kind='act.resumed'")[0][0]
        pressed=self.db('log',"SELECT count(*) FROM records WHERE kind='control.applied'")[0][0]
        put('Approval history',f'{total} approvals recorded' if total else 'none recorded yet',
            'active log store, kind=act.resumed (indexed count)',
            data=dict(approvals=total,owner_controls_applied=pressed,recent=approvals),
            details=('Owner-approved act.resumed events across the active log segment; archived segments are not counted, '
                     'and outbox confirmations and automatic elevations are not approvals. '
                     f'{pressed} button presses from the home were applied as controls. An approval is spent by the action '
                     'it approved, so there is nothing standing to withdraw; standing grants are on the Grants row.'))

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

    def fabric_rows(self,put,devices):
        # THE ENROLLED FABRIC AS THE RUNTIME HOLDS IT. Every row here reads the
        # live registry; none of them is a declaration taken from a contract.
        profiles=devices.all()
        ids=[str(p.get('node_id')) for p in profiles]
        domains=('tasks','world','memory','devices','policy','autonomy_queue','alarms')
        held={nid:[d for d in domains if nid in (devices.placement(d) or [])] for nid in ids}
        put('Enrollment',f"{len(ids)} enrolled: {', '.join(ids)}" if ids else 'no node enrolled','live DeviceRegistry.all',
            data=profiles,
            details='The nodes this runtime has admitted. A new machine is measured by tools/profile_node.py on that machine, and its profile reaches placement only through a reviewed promotion; the display never admits a node.')
        put('Node roles',' · '.join(f"{nid} holds {', '.join(ds) if ds else 'nothing yet'}" for nid,ds in held.items()) or 'no node enrolled',
            'live DeviceRegistry.placement',data=held,
            details='What each node is used for, read from the live placement assignments: a role is what a node holds, not its availability class.')
        put('Trust zones',' · '.join(f"{p.get('node_id')} ceiling {p.get('trust_zone_ceiling')} ({p.get('key_storage_class')})" for p in profiles) or 'no node enrolled',
            'live DeviceRegistry.all',
            data=[{k:p.get(k) for k in ('node_id','trust_zone_ceiling','key_storage_class','is_survival_host')} for p in profiles],
            details="The ceiling each node's key storage allows. A node reached through a fabric segment gets the weaker of this and the segment's ceiling (INV-NET-2); the fabric is not attested, so no remote node is admitted today.")
        # tools/spike/, AND FOUND FROM THE PROJECT ROOT: the bundle carries no
        # tools/spike, so a path from the runtime copy read "missing" for a file
        # that exists (driven 2026-09-14).
        wizard=project_file('tools/spike/profile_node.py')
        put('Onboarding wizard',('ready' if wizard else 'tools/spike/profile_node.py is missing')+': three steps, the first on the new machine',
            str(wizard or 'tools/spike/profile_node.py'),
            data=[dict(step=1,where='the new machine',do='python3 tools/spike/profile_node.py -- standard library only, no setup'),
                  dict(step=2,where='this Mac',do='bring the profile back and review what was measured'),
                  dict(step=3,where='review',do='promote it into contracts/policy/capability_profiles.toml as a reviewed act')],
            details='Enrollment measures rather than declares (INV-HW-2). The display lays out the steps; it never admits a node itself.')
        mode=self._permission_mode()
        put('Behaviour on / off this Mac',
            (f'runs only on this Mac · one rule set · permission mode {mode}' if len(ids)<=1
             else f'{len(ids)} nodes · rules follow placement · permission mode {mode}'),
            'live DeviceRegistry.all; permission_mode.json',data=dict(nodes=ids,permission_mode=mode),
            details='With one node there is no "off this Mac": VESPER runs here under the permission mode you set. Separate rules per node become possible once a second node is enrolled.')

    def consent_policy(self,put):
        # WHAT ACTUALLY APPROVES TODAY, read from the path that settles a parked
        # question: the runtime classifies the owner's latest utterance -- spoken
        # or typed, one intake -- and a yes answers the question in front of them.
        # Nothing splits approval tiers by channel, and saying so IS the reading:
        # a policy the code does not enforce is not shown as one.
        src=(REPO/'tools'/'ops'/'vesper_runtime.py').read_text(encoding='utf-8')
        if 'consent.classify(spoken)' not in src or 'actor.broker.answer(pending' not in src:
            raise ValueError('the approval path was not found in the runtime, so what approves cannot be stated')
        put('Consent channel policy','a yes, spoken or typed, answers the question in front of you · no tier requires a tap',
            'tools/ops/vesper_runtime.py: consent.classify on the latest utterance',
            data=dict(channels=['voice','typed'],tiers_requiring_a_tap=[]),
            details='The question in front of you is settled by your next utterance, whichever way it arrived; a question queued behind it is re-asked rather than settled. Requiring a tap for the highest tiers is a policy you have not set, and the runtime does not enforce one.')

    def _permission_mode(self):
        try:
            return str(json.loads((self.state/'permission_mode.json').read_text(encoding='utf-8')).get('mode') or 'unknown')
        except (OSError,ValueError):
            return 'unknown'

    def maintenance(self,put):
        # WHAT UPKEEP HAS BEEN DONE, AND THE STORES THAT GROW UNTIL SOMETHING
        # COMPACTS THEM. The gate log is written by the host's run_gates action.
        rows={}
        gates=self.state/'gates.log'
        if gates.is_file():
            tail=[line for line in gates.read_text(encoding='utf-8',errors='replace').splitlines() if line.strip()][-1:]
            rows['gates']=dict(last_line=tail[0][:160] if tail else '',written_at_ms=int(gates.stat().st_mtime*1000))
        for name in ('bus/log.db','l2.db','audit.db'):
            p=self.state/name
            if p.is_file():rows[name]=round(p.stat().st_size/1024**2,1)
        if not rows:raise ValueError('no gate log and no stores to report')
        gate=('gates never run from the home' if 'gates' not in rows else
              f"gates last run {max(0,int(time.time()-rows['gates']['written_at_ms']/1000))//60} min ago")
        put('Maintenance actions',f"{gate} · event log {rows.get('bus/log.db','?')} MB · memory {rows.get('l2.db','?')} MB",
            'gates.log; store file sizes',data=rows,
            details='Run the gates from the verification card; the event-log and memory-store sizes say when compaction is worth doing. Nothing here runs by itself.')

    def registry_profiles(self,devices,result):
        # THE NODE PLACEMENT CAN SEE, WITH WHAT WAS MEASURED ABOUT IT HERE. The
        # registry profile carries no RAM or storage, and a NodeProfile left at
        # zero would "simulate" a host that fits nothing. So with exactly one
        # node -- the host the runtime registers -- RAM is read from sysctl
        # hw.memsize and storage from this collection's own diskutil reading.
        # Throughput is never measured here, so `measured` stays False.
        from core.placement import NodeProfile
        profiles=devices.all()
        if len(profiles)!=1:
            raise ValueError(f'{len(profiles)} registry profiles; host resources are attributed only to a single local node')
        p=profiles[0]
        _,raw=self.command(['/usr/sbin/sysctl','-n','hw.memsize'])
        ram_gb=int(raw.decode().strip())/1024**3
        free=((result.get('Storage & SSD') or {}).get('data') or {}).get('APFSContainerFree')
        if not isinstance(free,int):raise ValueError('no measured free storage in this collection')
        node=NodeProfile(node_id=str(p['node_id']),trust_zone=str(p['trust_zone_ceiling']),
                         availability_class=str(p['availability_class']),ram_gb=round(ram_gb,2),
                         storage_gb=round(free/1024**3,2),measured=False,
                         survival_capable=bool(p.get('is_survival_host')))
        return {node.node_id:node}

    def simulations(self,put,profiles):
        from core.placement import survival_profile
        profiles=dict(list(profiles.items())[:MAX_RECORDS])
        data=simulate(profiles,self.context.get('assignments') or {})
        # THE VALUE SAYS WHAT THE SIMULATION FOUND, not that one was run.
        def carried(m):
            p=m['profile'];n=len(p.get('capabilities') or ());d=len(p.get('degradations') or ())
            short=p.get('core_shortfall') or ()
            why=(f" ({short[0].get('capability')}: {short[0].get('reason')})"
                 if short and isinstance(short[0],dict) else '')
            return f"{m['destination']} carries {n} of {n+d}"+('' if p.get('core_complete') else ', core incomplete'+why)
        put('Blast radius',' · '.join(f"without {b['removed']}: {b['outcome']}"
                                      +(f", {len(b['affected_domains'])} domain(s) displaced" if b['affected_domains'] else '')
                                      for b in data['blast']),
            'core.placement; menu simulation',data=data['blast'],
            details='Read-only scenario evaluation: each node removed in turn and placement asked again. No node is stopped and no assignment is written.')
        put('Migration dry-run',' · '.join('to '+carried(m) for m in data['migration']),'core.placement.survival_profile',data=data['migration'],
            details='Per-destination capacity/trust evaluation. Does not predict transfer time or perform migration.')
        put('Survival profile',' · '.join(carried(m) for m in data['migration']),'core.placement.survival_profile',data=data['migration'],
            details='What each node can carry if it is the last one standing, core first, then capabilities in value order while they fit; what does not fit is named with its reason.')
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
