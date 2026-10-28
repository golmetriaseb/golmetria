#!/usr/bin/env python3
"""Golmetría: descarga datos públicos (football-data.co.uk + ESPN), calcula el modelo y escribe data.json / backtest.json."""
import csv, io, json, math, re, sys, time, unicodedata, difflib, urllib.request
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo

UA = {'User-Agent': 'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1', 'Accept': '*/*'}
BASE = 'https://www.football-data.co.uk/'
LONDON = ZoneInfo('Europe/London')
NOW = datetime.now(timezone.utc)
TODAY = NOW.date()
WINDOW = 520          # dias de historial
HALF_LIFE = 180.0     # dias
K = 4.0               # encogimiento
RHO = -0.06
MIN_GAMES = 6
HORIZON = 8           # dias hacia adelante

LEAGUES = [
    dict(code='ENG', name='Championship',   kind='main', div='E1',  espn='eng.2'),
    dict(code='GER', name='2. Bundesliga',  kind='main', div='D2',  espn='ger.2'),
    dict(code='SCO', name='Premiership',    kind='main', div='SC0', espn='sco.1'),
    dict(code='SUI', name='Super League',   kind='new',  file='SWZ', country='Switzerland', espn='sui.1'),
    dict(code='BRA', name='Brasileirão',    kind='new',  file='BRA', country='Brazil', espn='bra.1'),
]
status = {'generated': NOW.isoformat(), 'leagues': {}, 'errors': []}

def log(*a):
    print(*a, file=sys.stderr, flush=True)

def fetch(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                raw = r.read()
            for enc in ('utf-8-sig', 'latin-1'):
                try:
                    return raw.decode(enc)
                except Exception:
                    pass
        except Exception as e:
            last = e
            time.sleep(2 + i * 2)
    raise RuntimeError(f'{url}: {last}')

def rows(text):
    return list(csv.DictReader(io.StringIO(text)))

def pdate(s):
    s = (s or '').strip()
    for f in ('%d/%m/%Y', '%d/%m/%y', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, f).date()
        except Exception:
            pass
    return None

def num(x):
    try:
        v = float(str(x).strip())
        return v
    except Exception:
        return None

def season_codes():
    y = TODAY.year % 100
    cur = f'{y:02d}{y+1:02d}' if TODAY.month >= 7 else f'{y-1:02d}{y:02d}'
    p = int(cur[:2]) - 1
    prev = f'{p:02d}{p+1:02d}'
    return [prev, cur]

# ---------- historial ----------
def load_history(lg):
    out = []
    if lg['kind'] == 'main':
        for sc in season_codes():
            try:
                t = fetch(f"{BASE}mmz4281/{sc}/{lg['div']}.csv")
            except Exception as e:
                status['errors'].append(str(e)[:200]); continue
            for r in rows(t):
                d = pdate(r.get('Date'))
                hg, ag = num(r.get('FTHG')), num(r.get('FTAG'))
                if not d or hg is None or ag is None or not r.get('HomeTeam'):
                    continue
                out.append(dict(d=d, h=r['HomeTeam'].strip(), a=r['AwayTeam'].strip(), hg=hg, ag=ag,
                                h1=num(r.get('HTHG')), a1=num(r.get('HTAG')),
                                hc=num(r.get('HC')), ac=num(r.get('AC'))))
    else:
        try:
            t = fetch(f"{BASE}new/{lg['file']}.csv")
        except Exception as e:
            status['errors'].append(str(e)[:200]); return out
        for r in rows(t):
            d = pdate(r.get('Date'))
            hg, ag = num(r.get('HG')), num(r.get('AG'))
            if not d or hg is None or ag is None or not r.get('Home'):
                continue
            out.append(dict(d=d, h=r['Home'].strip(), a=r['Away'].strip(), hg=hg, ag=ag, h1=None, a1=None, hc=None, ac=None))
    out.sort(key=lambda m: m['d'])
    return out

# ---------- modelo ----------
def chan_vals(m, chan):
    if chan == 'g':
        return m['hg'], m['ag']
    if chan == 'g1':
        return (m['h1'], m['a1']) if m['h1'] is not None and m['a1'] is not None else (None, None)
    return (m['hc'], m['ac']) if m['hc'] is not None and m['ac'] is not None else (None, None)

def fit(hist, chan, ref):
    ms = [m for m in hist if m['d'] < ref and (ref - m['d']).days <= WINDOW]
    sw = swh = swa = 0.0
    T = {}
    mh = ma = 0.0
    cnt = 0
    for m in ms:
        x, y = chan_vals(m, chan)
        if x is None:
            continue
        w = 0.5 ** ((ref - m['d']).days / HALF_LIFE)
        cnt += 1
        sw += w; mh += w * x; ma += w * y
        for team, home, gf, ga in ((m['h'], True, x, y), (m['a'], False, y, x)):
            t = T.setdefault(team, dict(Wh=0, gfh=0, gah=0, Wa=0, gfa=0, gaa=0, n=0))
            t['n'] += 1
            if home:
                t['Wh'] += w; t['gfh'] += w * gf; t['gah'] += w * ga
            else:
                t['Wa'] += w; t['gfa'] += w * gf; t['gaa'] += w * ga
    if sw <= 0 or cnt < 20:
        return None
    return dict(mu_h=mh / sw, mu_a=ma / sw, T=T)

def strengths(F, team):
    t = F['T'].get(team)
    if not t:
        return None
    mh, ma = F['mu_h'], F['mu_a']
    mall = (mh + ma) / 2
    if min(mh, ma, mall) <= 0:
        return None
    ah = (t['gfh'] + K * mh) / ((t['Wh'] + K) * mh)
    dh = (t['gah'] + K * ma) / ((t['Wh'] + K) * ma)
    aa = (t['gfa'] + K * ma) / ((t['Wa'] + K) * ma)
    da = (t['gaa'] + K * mh) / ((t['Wa'] + K) * mh)
    ao = (t['gfh'] + t['gfa'] + K * mall) / ((t['Wh'] + t['Wa'] + K) * mall)
    do = (t['gah'] + t['gaa'] + K * mall) / ((t['Wh'] + t['Wa'] + K) * mall)
    return dict(ah=.5 * ah + .5 * ao, dh=.5 * dh + .5 * do, aa=.5 * aa + .5 * ao, da=.5 * da + .5 * do, n=t['n'])

def lambdas(F, h, a):
    if not F:
        return None
    sh, sa = strengths(F, h), strengths(F, a)
    if not sh or not sa:
        return None
    return F['mu_h'] * sh['ah'] * sa['da'], F['mu_a'] * sa['aa'] * sh['dh']

def pois(l, n):
    a = [math.exp(-l)]
    for k in range(1, n + 1):
        a.append(a[-1] * l / k)
    return a

def grid(lh, la, n=10):
    A, B = pois(lh, n), pois(la, n)
    G = [[A[i] * B[j] for j in range(n + 1)] for i in range(n + 1)]
    G[0][0] *= max(0.0, 1 - lh * la * RHO)
    G[0][1] *= max(0.0, 1 + lh * RHO)
    G[1][0] *= max(0.0, 1 + la * RHO)
    G[1][1] *= (1 - RHO)
    s = sum(map(sum, G))
    return [[v / s for v in r] for r in G]

def nb_tail(mu, k):
    v = 1.3 * mu
    r = mu * mu / (v - mu)
    p = r / (r + mu)
    f = p ** r
    c = 0.0
    for i in range(k):
        c += f
        f = f * (i + r) / (i + 1) * (1 - p)
    return 1 - c

def markets(hist, h, a, ref):
    Fg = fit(hist, 'g', ref)
    lam = lambdas(Fg, h, a)
    if not lam:
        return None
    sh, sa = strengths(Fg, h), strengths(Fg, a)
    if sh['n'] < MIN_GAMES or sa['n'] < MIN_GAMES:
        return None
    lh, la = lam
    G = grid(lh, la)
    H = D = V = o15 = o25 = o35 = bt = 0.0
    for i, r in enumerate(G):
        for j, p in enumerate(r):
            if i > j: H += p
            elif i == j: D += p
            else: V += p
            t = i + j
            if t > 1: o15 += p
            if t > 2: o25 += p
            if t > 3: o35 += p
            if i and j: bt += p
    out = {'1': H, 'X': D, '2': V, '1X': H + D, 'X2': V + D, 'o15': o15, 'o25': o25, 'o35': o35, 'btts': bt, 'lh': lh, 'la': la}
    F1 = fit(hist, 'g1', ref)
    l1 = lambdas(F1, h, a)
    out['g1t'] = 1 - math.exp(-(l1[0] + l1[1])) if l1 else None
    Fc = fit(hist, 'c', ref)
    lc = lambdas(Fc, h, a)
    if lc:
        mu = lc[0] + lc[1]
        out['c85'], out['c95'], out['c105'] = nb_tail(mu, 9), nb_tail(mu, 10), nb_tail(mu, 11)
        out['cmu'] = mu
    return out

def bets_for(M, home, away, odds):
    B = []
    def add(t, label, p, odd=None):
        if p is None: return
        B.append(dict(type=t, label=label, p=round(p, 4), odd=odd))
    add('win', f'Gana {home}', M['1'], odds.get('1'))
    add('win', 'Empate', M['X'], odds.get('X'))
    add('win', f'Gana {away}', M['2'], odds.get('2'))
    add('win', f'{home} o empate', M['1X'])
    add('win', f'{away} o empate', M['X2'])
    add('o15', 'Más de 1.5 goles', M['o15'])
    add('o25', 'Más de 2.5 goles', M['o25'], odds.get('o25'))
    add('o35', 'Más de 3.5 goles', M['o35'])
    add('btts', 'Ambos marcan', M['btts'])
    add('g1t', 'Gol en el 1er tiempo', M.get('g1t'))
    if 'c85' in M:
        add('corn', 'Córners más de 8.5', M['c85'])
        add('corn', 'Córners más de 9.5', M['c95'])
        add('corn', 'Córners más de 10.5', M['c105'])
    return B

# ---------- partidos futuros ----------
def first(r, keys):
    for k in keys:
        v = num(r.get(k))
        if v and v > 1.0:
            return v
    return None

def kickoff(d, tm):
    hh, mm = 12, 0
    m = re.match(r'(\d{1,2}):(\d{2})', (tm or '').strip())
    if m: hh, mm = int(m.group(1)), int(m.group(2))
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=LONDON).astimezone(timezone.utc)

def odds_from(r):
    return {'1': first(r, ['AvgH', 'B365H', 'PH', 'MaxH']), 'X': first(r, ['AvgD', 'B365D', 'PD', 'MaxD']),
            '2': first(r, ['AvgA', 'B365A', 'PA', 'MaxA']), 'o25': first(r, ['Avg>2.5', 'B365>2.5', 'P>2.5'])}

def load_fixtures():
    fx = {l['code']: [] for l in LEAGUES}
    try:
        for r in rows(fetch(BASE + 'fixtures.csv')):
            for l in LEAGUES:
                if l['kind'] == 'main' and r.get('Div') == l['div']:
                    d = pdate(r.get('Date'))
                    if d and r.get('HomeTeam'):
                        fx[l['code']].append(dict(k=kickoff(d, r.get('Time')), h=r['HomeTeam'].strip(), a=r['AwayTeam'].strip(), odds=odds_from(r), src='fd'))
    except Exception as e:
        status['errors'].append('fixtures.csv: ' + str(e)[:150])
    try:
        for r in rows(fetch(BASE + 'new_league_fixtures.csv')):
            for l in LEAGUES:
                if l['kind'] == 'new' and (r.get('Country') or '').strip() == l['country']:
                    lgname = (r.get('League') or '').strip()
                    if l['code'] == 'BRA' and lgname and lgname != 'Serie A':
                        continue
                    d = pdate(r.get('Date'))
                    if d and r.get('Home'):
                        fx[l['code']].append(dict(k=kickoff(d, r.get('Time')), h=r['Home'].strip(), a=r['Away'].strip(), odds=odds_from(r), src='fd'))
    except Exception as e:
        status['errors'].append('new_league_fixtures.csv: ' + str(e)[:150])
    return fx

def norm(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'\b(fc|afc|sc|cf|fk|sv|vfl|vfb|1\.|club|de|sport|esporte|clube)\b', ' ', s)
    return re.sub(r'[^a-z0-9 ]', ' ', s).split()

def match_team(name, teams):
    n = ' '.join(norm(name))
    best, br = None, 0
    for t in teams:
        tn = ' '.join(norm(t))
        r = difflib.SequenceMatcher(None, n, tn).ratio()
        if n and (n in tn or tn in n):
            r = max(r, 0.85)
        if r > br: best, br = t, r
    return best if br >= 0.72 else None

def am2dec(x):
    try:
        v = float(str(x).replace('+', ''))
    except Exception:
        return None
    if v == 0: return None
    d = 1 + v / 100 if v > 0 else 1 + 100 / abs(v)
    return round(d, 2) if d > 1.01 else None

def espn_odds(ev):
    o = {}
    try:
        od = ev['competitions'][0].get('odds') or []
        if not od: return o
        od = od[0]
        ml = od.get('moneyline') or {}
        def side(k):
            x = (ml.get(k) or {})
            return am2dec(((x.get('close') or x.get('open') or {}).get('odds')))
        o['1'], o['X'], o['2'] = side('home'), side('draw'), side('away')
        tot = od.get('total') or {}
        ov = (tot.get('over') or {}).get('close') or (tot.get('over') or {}).get('open') or {}
        if str(ov.get('line', '')).lower().replace('o', '') == '2.5':
            o['o25'] = am2dec(ov.get('odds'))
    except Exception:
        pass
    return o

def espn_fixtures(l, teams):
    out, miss = [], 0
    for i in range(HORIZON):
        d = TODAY + timedelta(days=i)
        try:
            j = json.loads(fetch(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{l['espn']}/scoreboard?dates={d:%Y%m%d}", tries=2))
        except Exception as e:
            status['errors'].append(f"espn {l['code']} {d}: {str(e)[:100]}"); continue
        for ev in j.get('events', []):
            try:
                comp = ev['competitions'][0]['competitors']
                h = next(c for c in comp if c['homeAway'] == 'home')['team']['displayName']
                a = next(c for c in comp if c['homeAway'] == 'away')['team']['displayName']
                k = datetime.fromisoformat(ev['date'].replace('Z', '+00:00'))
            except Exception:
                continue
            th, ta = match_team(h, teams), match_team(a, teams)
            if not th or not ta:
                miss += 1; continue
            try:
                if ev['status']['type']['name'] != 'STATUS_SCHEDULED':
                    continue
            except Exception:
                pass
            out.append(dict(k=k, h=th, a=ta, odds=espn_odds(ev), src='espn'))
    return out, miss

def slug(s):
    return '-'.join(norm(s))

# ---------- backtest ----------
def backtest(hist, days=120):
    recs = {k: [] for k in ('1', 'X', '2', 'o15', 'o25', 'btts')}
    start = TODAY - timedelta(days=days)
    test = [m for m in hist if start <= m['d'] < TODAY]
    for m in test:
        M = markets(hist, m['h'], m['a'], m['d'])
        if not M: continue
        t = m['hg'] + m['ag']
        res = {'1': m['hg'] > m['ag'], 'X': m['hg'] == m['ag'], '2': m['hg'] < m['ag'], 'o15': t > 1, 'o25': t > 2, 'btts': m['hg'] > 0 and m['ag'] > 0}
        for k in recs: recs[k].append((M[k], 1 if res[k] else 0))
    out = {}
    for k, v in recs.items():
        if not v: continue
        bins = []
        edges = [0, .3, .4, .5, .6, .7, .8, 1.01]
        for lo, hi in zip(edges, edges[1:]):
            s = [x for x in v if lo <= x[0] < hi]
            if s:
                bins.append(dict(lo=lo, hi=min(hi, 1), n=len(s), pred=round(sum(x[0] for x in s) / len(s), 3), real=round(sum(x[1] for x in s) / len(s), 3)))
        out[k] = dict(n=len(v), brier=round(sum((p - y) ** 2 for p, y in v) / len(v), 4), bins=bins)
    return out

def main():
    fx = load_fixtures()
    matches, bt = [], {}
    for l in LEAGUES:
        code = l['code']
        st = status['leagues'][code] = dict(name=l['name'])
        hist = load_history(l)
        st['hist'] = len(hist)
        st['last_result'] = hist[-1]['d'].isoformat() if hist else None
        st['has_corners'] = sum(1 for m in hist if m['hc'] is not None)
        st['has_half'] = sum(1 for m in hist if m['h1'] is not None)
        teams = sorted({m['h'] for m in hist} | {m['a'] for m in hist})
        lf = fx.get(code, [])
        st['fixtures_fd'] = len(lf)
        try:
            ef, miss = espn_fixtures(l, teams)
        except Exception as e:
            ef, miss = [], 0; status['errors'].append(f'espn {code}: {e}')
        st['fixtures_espn'] = len(ef); st['espn_unmatched'] = miss
        seen = {(x['h'], x['a'], x['k'].date()) for x in lf}
        allf = list(lf)
        for e in ef:
            if not any((e['h'], e['a'], e['k'].date() + timedelta(days=dd)) in seen for dd in (-1, 0, 1)):
                allf.append(e)
        done = 0
        for f in allf:
            if not (NOW - timedelta(hours=3) <= f['k'] <= NOW + timedelta(days=HORIZON)):
                continue
            M = markets(hist, f['h'], f['a'], TODAY)
            if not M:
                st['skipped'] = st.get('skipped', 0) + 1; continue
            matches.append(dict(id=f"{code}-{f['k']:%Y%m%d}-{slug(f['h'])}-{slug(f['a'])}", league=code, leagueName=l['name'],
                                utc=f['k'].strftime('%Y-%m-%dT%H:%M:%SZ'), home=f['h'], away=f['a'], src=f['src'], oddsFrom=('promedio de casas' if f['src']=='fd' else ('DraftKings' if any(f['odds'].values()) else None)),
                                lh=round(M['lh'], 2), la=round(M['la'], 2), bets=bets_for(M, f['h'], f['a'], f['odds'])))
            done += 1
        st['matches'] = done
        try:
            bt[code] = backtest(hist)
        except Exception as e:
            status['errors'].append(f'backtest {code}: {e}')
    matches.sort(key=lambda m: m['utc'])
    json.dump(dict(generated=NOW.strftime('%Y-%m-%dT%H:%M:%SZ'), matches=matches, status=status), open('data.json', 'w'), ensure_ascii=False, separators=(',', ':'))
    json.dump(dict(generated=NOW.strftime('%Y-%m-%dT%H:%M:%SZ'), leagues=bt), open('backtest.json', 'w'), ensure_ascii=False, indent=1)
    log(json.dumps(status, indent=1, ensure_ascii=False)); log('partidos:', len(matches))

if __name__ == '__main__':
    main()
