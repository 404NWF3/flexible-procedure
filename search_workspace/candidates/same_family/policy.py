"""Parameterized online rules. P is frozen in each registered source bundle."""
P = {'dispatch': 'family'}


def decide(o):
    kind = o['kind']
    jobs = o['jobs']
    if kind == 'admit':
        cap = P.get('cap', 100000)
        cutoff = P.get('cutoff', 0)
        candidates = [j for j in jobs if j['internal'] or (
            o['wip'] < cap and o['remaining'] > cutoff and
            (P.get('release_min_margin', -10000) <= j['margin']))]
        if not candidates:
            return {'wait': 15}
        mode = P.get('admission', 'fifo')
        def rank(j):
            # The request sequence is an opaque ordinal, not an environment seed.
            if mode == 'internal':
                return (not j['internal'], j['request'])
            if mode == 'value':
                return (not j['internal'], -j['margin'] / max(1, j['remaining_mean']), j['request'])
            return (j['request'],)
        j = min(candidates, key=rank)
        return {'job': j['id']}
    mode = P.get('dispatch', 'fifo')
    last = o['last_product']
    aging = P.get('aging', 100000000)
    station_modes = P.get('station_modes', {})
    mode = station_modes.get(o['station'], mode)
    def rank(j):
        fifo = (j['queue_entered'], j['id'])
        setup = 15 if last is not None and last != j['product'] else 0
        if mode == 'fifo':
            return fifo
        if mode == 'family':
            if last is None or j['wait'] >= aging:
                return (0, *fifo)
            return (1, j['product'] != last, *fifo)
        if mode == 'shortest':
            return (j['remaining_mean'] + P.get('setup_weight', 1) * setup, *fifo)
        if mode == 'margin':
            score = (j['price'] - (100/60) * (j['remaining_mean'] + setup)) / max(1, j['remaining_mean'] + P.get('setup_weight', 1) * setup)
        elif mode == 'local_value':
            score = (j['price'] - (100/60) * (j['remaining_mean'] + setup)) / max(1, j['current_mean'] + P.get('setup_weight', 1) * setup)
        else:
            raise ValueError('unknown dispatch')
        score += P.get('age_weight', 0) * j['wait'] / 60
        if o['remaining'] < P.get('terminal_window', 0):
            score -= max(0, j['remaining_mean'] + setup - o['remaining']) * 100
        return (-score, *fifo)
    return {'job': min(jobs, key=rank)['id']}
