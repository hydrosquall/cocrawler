'''
A trivial stats system for CoCrawler
'''

import logging
import pickle
import time
from contextlib import contextmanager

from sortedcontainers import SortedSet

LOGGER = logging.getLogger(__name__)

start_time = time.time()
start_cpu = time.clock()
maxes = {}
sums = {}
burners = {}
latencies = {}
coroutine_states = {}
exitstatus = 0

def stats_max(name, value):
    maxes[name] = max(maxes.get(name, value), value)

def stats_sum(name, value):
    sums[name] = sums.get(name, 0) + value

def mynegsplitter(string):
    _, value = string.rsplit(':', maxsplit=1)
    return -float(value)

def _record_cpu_burn(name, start, url=None):
    elapsed = time.clock() - start
    burn = burners.get(name, {})
    burn['count'] = burn.get('count', 0) + 1
    burn['time'] = burn.get('time', 0.0) + elapsed
    avg = burn.get('avg', 10000000.)

    # are we exceptional? 10x current average and significant
    if elapsed > avg * 10 and elapsed > 0.015:
        if 'list' not in burn:
            burn['list'] = SortedSet(key=mynegsplitter) # XXX switch this to a ValueSortedDict
        url = url or 'none'
        burn['list'].add(url + ':' + str(elapsed))

    burn['avg'] = burn['time']/burn['count']
    burners[name] = burn

def _record_latency(name, start, url=None):
    elapsed = time.time() - start
    latency = latencies.get(name, {})
    latency['count'] = latency.get('count', 0) + 1
    latency['time'] = latency.get('time', 0.0) + elapsed
    avg = latency.get('avg', 1000000.)

    # are we exceptional? 10x current average and significant
    if elapsed > avg * 10 and elapsed > 0.015:
        if 'list' not in latency:
            latency['list'] = SortedSet(key=mynegsplitter) # XXX switch this to a ValueSortedDict
        url = url or 'none'
        latency['list'].add(url + ':' + str(elapsed))

    latency['avg'] = latency['time']/latency['count']
    latencies[name] = latency

def update_cpu_burn(name, count, time, l):
    burn = burners.get(name, {})
    burn['count'] = burn.get('count', 0) + count
    burn['time'] = burn.get('time', 0.0) + time
    burn['list'] = l.union(burn.get('list', SortedSet(key=mynegsplitter)))
    burners[name] = burn

@contextmanager
def record_burn(name, url=None):
    try:
        start = time.clock()
        yield
    finally:
        _record_cpu_burn(name, start, url=url)

@contextmanager
def record_latency(name, url=None):
    try:
        start = time.time()
        yield
    finally:
        _record_latency(name, start, url=url)

@contextmanager
def coroutine_state(k):
    # the documentation for generators leaves something to be desired
    coroutine_states[k] = coroutine_states.get(k, 0) + 1
    try:
        yield
    finally:
        coroutine_states[k] -= 1

def coroutine_report():
    LOGGER.info('Coroutine report:')
    for k in sorted(list(coroutine_states.keys())):
        if coroutine_states[k] > 0:
            LOGGER.info('  %s: %d', k, coroutine_states[k])

def report():
    LOGGER.info('Stats report:')
    for s in sorted(sums):
        LOGGER.info('  %s: %d', s, sums[s])
    for s in sorted(maxes):
        LOGGER.info('  %s: %d', s, maxes[s])

    LOGGER.info('CPU burn report:')
    for key, burn in sorted(burners.items(), key=lambda x: x[1]['time'], reverse=True):
        LOGGER.info('  %s has %d calls taking %.3f cpu seconds.', key, burn['count'], burn['time'])
        if burn.get('list'):
            LOGGER.info('    biggest burners')
            first10 = burn['list'][0:min(len(burn['list']), 10)]
            for url in first10:
                u, e = url.rsplit(':', maxsplit=1)
                LOGGER.info('      %.3fs: %s', float(e), u)

    LOGGER.info('Latency report:')
    for key, latency in sorted(latencies.items(), key=lambda x: x[1]['time'], reverse=True):
        LOGGER.info('  %s has %d calls taking %.3f cpu seconds.', key, latency['count'], latency['time'])
        if latency.get('list'):
            LOGGER.info('    biggest latencies')
            first10 = latency['list'][0:min(len(latency['list']), 10)]
            for url in first10:
                u, e = url.rsplit(':', maxsplit=1)
                LOGGER.info('      %.3fs: %s', float(e), u)

    LOGGER.info('Summary:')
    elapsed = time.time() - start_time
    elapsedc = time.clock() - start_cpu # includes all threads
    parser_cpu = stat_value('parser cpu time')
    if parser_cpu:
        elapsedc -= parser_cpu
    LOGGER.info('  Elapsed time is %.3f seconds', elapsed)
    LOGGER.info('  Main thread cpu time is %.3f seconds', elapsedc)
    if elapsed > 0:
        LOGGER.info('  Main thread cpu {:.1f}%'.format(elapsedc/elapsed*100))
    if sums.get('fetch URLs', 0) and elapsed > 0:
        LOGGER.info('  Crawl rate is %d pages/second', int(sums['fetch URLs']/elapsed))
    if sums.get('fetch URLs', 0) and elapsedc > 0:
        LOGGER.info('  Crawl rate is %d pages/main-thread-cpu-second', int(sums['fetch URLs']/elapsedc))
    if sums.get('fetch bytes', 0) and elapsed > 0:
        LOGGER.info('  Crawl rate is %.2f gigabits/s', sums['fetch bytes']/elapsed*8/1000000000.)

def stat_value(name):
    if name in sums:
        return sums[name]
    if name in maxes:
        return maxes[name]
    if name in burners:
        return burners[name].get('time', 0)

def burn_values(name):
    if name in burners:
        return burners[name].get('time', 0), burners[name].get('count', 0)
    else:
        return None, None

def check(config, no_test=False):
    if no_test:
        return

    seq = config.get('Testing', {}).get('StatsEQ', {})
    sge = config.get('Testing', {}).get('StatsGE', {})
    global exitstatus
    if seq:
        for s in seq:
            if stat_value(s) != seq[s]:
                if stat_value(s) is None and seq[s] == 0:
                    continue
                LOGGER.error('Stat %s=%s is not the expected value of %s', s, stat_value(s), seq[s])
                exitstatus = 1
            else:
                LOGGER.debug('Stat %s=%s is the expected value', s, seq[s])
    if sge:
        for s in sge:
            if stat_value(s) < sge[s]:
                if stat_value(s) is None and sge[s] == 0:
                    continue
                LOGGER.error('Stat %s of %s is not >= %s', s, stat_value(s), sge[s])
                exitstatus = 1
            else:
                LOGGER.debug('Stat %s=%s is the expected value', s, sge[s])

def raw():
    '''
    Return a list of stuff suitable to feeding to stats.update() in a different thread.
    '''
    return maxes, sums, burners

def update(l):
    '''
    Update current thread's stats with stats from elsewhere
    '''
    m, s, b = l
    for k in m:
        stats_max(k, m[k])
    for k in s:
        stats_sum(k, s[k])
    for k in b:
        update_cpu_burn(k, b[k]['count'], b[k]['time'], b[k].get('list', SortedSet(key=mynegsplitter)))

def clear():
    '''
    After raw(), this clears stats to prevent double-counting
    '''
    global maxes
    maxes = {}
    global sums
    sums = {}
    for b in burners:
        burners[b] = {'avg': burners[b].get('avg'), 'count': 0, 'time': 0}
    for l in latencies:
        latencies[l] = {'avg': latencies[l].get('avg'), 'count': 0, 'time': 0}

def save(f):
    pickle.dump('stats', f)
    pickle.dump(start_time, f)
    pickle.dump(burners, f)
    pickle.dump(maxes, f)
    pickle.dump(sums, f)

def load(f):
    if pickle.load(f) != 'stats':
        raise ValueError('invalid stats section in savefile')
    global start_time
    start_time = pickle.load(f)
    global burners
    burners = pickle.load(f)
    global maxes
    maxes = pickle.load(f)
    global sums
    sums = pickle.load(f)
