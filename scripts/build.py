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
CACHE_FILE = 'espn_cache.json'   # historial de córners/remates leído de ESPN (ligas que football-data no trae)
PER_LEAGUE_REQ = 40   # peticiones a ESPN por liga y por corrida (se completa de a poco, lo más reciente primero)
ONLY_REQ = 160       # peticiones por corrida para ligas que salen solo de ESPN (Ecuador)
RUN_SECONDS = 900     # tope de tiempo para esa lectura en cada corrida
CACHE = {'ev': {}, 'days': {}}
DEADLINE = 0.0

FAV = {'ENG', 'GER', 'SCO', 'SUI', 'BRA', 'ECU'}
_main = [('EPL', 'E0', 'Premier League', 'eng.1'), ('ENG', 'E1', 'Championship', 'eng.2'), ('EL1', 'E2', 'League One', 'eng.3'),
         ('SCO', 'SC0', 'Premiership', 'sco.1'),
         ('SC1', 'SC1', 'Championship (Escocia)', 'sco.2'), ('GB1', 'D1', 'Bundesliga', 'ger.1'), ('GER', 'D2', '2. Bundesliga', 'ger.2'),
         ('SA', 'I1', 'Serie A', 'ita.1'), ('SB', 'I2', 'Serie B', 'ita.2'), ('LL', 'SP1', 'La Liga', 'esp.1'), ('LL2', 'SP2', 'La Liga 2', 'esp.2'),
         ('L1', 'F1', 'Ligue 1', 'fra.1'), ('L2', 'F2', 'Ligue 2', 'fra.2'), ('ERE', 'N1', 'Eredivisie', 'ned.1'),
         ('BEL', 'B1', 'Pro League (Bélgica)', 'bel.1'), ('POR', 'P1', 'Primeira Liga', 'por.1'), ('TUR', 'T1', 'Süper Lig', 'tur.1'),
         ('GRE', 'G1', 'Super League (Grecia)', 'gre.1')]
_new = [('SUI', 'SWZ', 'Switzerland', 'Super League (Suiza)', 'sui.1'), ('BRA', 'BRA', 'Brazil', 'Brasileirão', 'bra.1'),
        ('ARG', 'ARG', 'Argentina', 'Liga Profesional', 'arg.1'), ('AUT', 'AUT', 'Austria', 'Bundesliga (Austria)', 'aut.1'),
        ('DNK', 'DNK', 'Denmark', 'Superliga (Dinamarca)', 'den.1'), ('FIN', 'FIN', 'Finland', 'Veikkausliiga', 'fin.1'),
        ('IRL', 'IRL', 'Ireland', 'Premier Division (Irlanda)', 'irl.1'), ('JPN', 'JPN', 'Japan', 'J1 League', 'jpn.1'),
        ('MEX', 'MEX', 'Mexico', 'Liga MX', 'mex.1'), ('NOR', 'NOR', 'Norway', 'Eliteserien', 'nor.1'),
        ('POL', 'POL', 'Poland', 'Ekstraklasa', 'pol.1'), ('ROU', 'ROU', 'Romania', 'Liga 1 (Rumanía)', 'rou.1'),
        ('RUS', 'RUS', 'Russia', 'Premier Liga (Rusia)', 'rus.1'), ('SWE', 'SWE', 'Sweden', 'Allsvenskan', 'swe.1'),
        ('USA', 'USA', 'USA', 'MLS', 'usa.1'), ('CHN', 'CHN', 'China', 'Super League (China)', 'chn.1')]
LEAGUES = [dict(code=c, name=n, kind='main', div=d, espn=e, fav=c in FAV) for c, d, n, e in _main] + \
          [dict(code=c, name=n, kind='new', file=f, country=co, espn=e, fav=c in FAV, flt=('Serie A' if c == 'BRA' else None)) for c, f, co, n, e in _new]
LEAGUES.append(dict(code='ECU', name='LigaPro (Ecuador)', kind='espn', espn='ecu.1', fav=True))   # sin datos en football-data: todo sale de ESPN
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

# ---------- córners de ESPN para ligas sin ese dato ----------
def load_cache():
    try:
        c = json.load(open(CACHE_FILE))
        c.setdefault('ev', {}); c.setdefault('days', {})
        return c
    except Exception:
        return {'ev': {}, 'days': {}}

def save_cache():
    try:
        json.dump(CACHE, open(CACHE_FILE, 'w'), ensure_ascii=False, separators=(',', ':'))
    except Exception as ex:
        log('cache espn no guardada', str(ex)[:100])

def corner_split(sj, hname, aname, hid, aid):
    """Córners y remates del detalle de ESPN y córners del 1.er tiempo contando cada córner del relato con su minuto.
    Los del 1.er tiempo solo se aceptan si el relato coincide EXACTO con la estadística de cada equipo."""
    out = dict(hc=None, ac=None, hst=None, ast=None, hc1=None, ac1=None)
    got = {'wonCorners': {}, 'shotsOnTarget': {}}
    for t in sj['boxscore']['teams']:
        for stt in t.get('statistics', []):
            if stt.get('name') in got:
                try:
                    got[stt['name']][str(t['team']['id'])] = int(float(stt['displayValue']))
                except Exception:
                    pass
    for name, kh, ka in (('wonCorners', 'hc', 'ac'), ('shotsOnTarget', 'hst', 'ast')):
        g = got[name]
        if hid in g and aid in g and g[hid] + g[aid] > 0:  # 0-0 = ESPN no tiene el dato
            out[kh], out[ka] = g[hid], g[aid]
    try:
        if out['hc'] is not None:
            nh, na = ' '.join(norm(hname)), ' '.join(norm(aname))
            tot = {'h': 0, 'a': 0}; first = {'h': 0, 'a': 0}
            for x in (sj.get('commentary') or []):
                mt = re.match(r"\s*corner,\s*(.+?)\.\s*conceded", str(x.get('text', '')), re.I)
                if not mt:
                    continue
                tn = ' '.join(norm(mt.group(1)))
                if tn == nh: side = 'h'
                elif tn == na: side = 'a'
                else:
                    ih, ia = bool(tn) and (tn in nh or nh in tn), bool(tn) and (tn in na or na in tn)
                    side = 'h' if ih and not ia else ('a' if ia and not ih else None)
                mm = re.match(r"\s*(\d+)", str((x.get('time') or {}).get('displayValue', '')))
                if side is None or not mm:
                    return out
                tot[side] += 1
                if int(mm.group(1)) <= 45:
                    first[side] += 1
            if tot['h'] == out['hc'] and tot['a'] == out['ac']:
                out['hc1'], out['ac1'] = first['h'], first['a']
    except Exception:
        pass
    return out

def espn_enrich(lg, out):
    """Completa córners y remates de partidos ya jugados con el detalle de ESPN. Nunca debe romper el proceso."""
    try:
        code = lg['code']
        evs = CACHE['ev'].setdefault(code, {})
        days = set(CACHE.setdefault('days2', {}).setdefault(code, []))
        teams = sorted({m['h'] for m in out} | {m['a'] for m in out})
        budget = PER_LEAGUE_REQ
        cutoff = TODAY - timedelta(days=400)
        todo = sorted({m['d'] for m in out if cutoff <= m['d'] < TODAY and m.get('hc1') is None}, reverse=True)
        for d in todo:
            if d.isoformat() in days:
                continue
            if budget <= 0 or time.time() > DEADLINE:
                break
            budget -= 1
            try:
                j = json.loads(fetch(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg['espn']}/scoreboard?dates={d:%Y%m%d}", tries=2))
            except Exception:
                continue
            complete = True
            for ev in j.get('events', []):
                try:
                    if not ev['status']['type'].get('completed'):
                        continue
                    eid = str(ev['id'])
                    if eid in evs and evs[eid].get('v') == 2:
                        continue
                    comp = ev['competitions'][0]['competitors']
                    ch = next(c for c in comp if c['homeAway'] == 'home')
                    ca = next(c for c in comp if c['homeAway'] == 'away')
                    rec = dict(d=datetime.fromisoformat(ev['date'].replace('Z', '+00:00')).date().isoformat(),
                               h=ch['team']['displayName'], a=ca['team']['displayName'], hc=None, ac=None, hst=None, ast=None, hc1=None, ac1=None, v=2)
                    hid, aid = str(ch['team'].get('id')), str(ca['team'].get('id'))
                except Exception:
                    continue
                if budget <= 0 or time.time() > DEADLINE:
                    complete = False
                    break
                budget -= 1
                try:
                    sj = json.loads(fetch(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg['espn']}/summary?event={eid}", tries=2))
                    rec.update(corner_split(sj, rec['h'], rec['a'], hid, aid))
                except Exception:
                    complete = False
                    continue
                evs[eid] = rec
            if complete:
                days.add(d.isoformat())
        CACHE['days2'][code] = sorted(days)
        idx = {}
        for e in evs.values():
            th, ta = match_team(e['h'], teams), match_team(e['a'], teams)
            if th and ta and (e.get('hc') is not None or e.get('hc1') is not None):
                idx.setdefault((th, ta), []).append(e)
        n = 0
        for m in out:
            if m['hc'] is not None and m.get('hc1') is not None:
                continue
            for e in idx.get((m['h'], m['a']), []):
                if abs((date.fromisoformat(e['d']) - m['d']).days) <= 1:
                    if m['hc'] is None and e.get('hc') is not None:
                        m['hc'], m['ac'], m['hst'], m['ast'] = e['hc'], e['ac'], e['hst'], e['ast']
                    if e.get('hc1') is not None:
                        m['hc1'], m['ac1'] = e['hc1'], e['ac1']
                    n += 1
                    break
        log('espn historial', code, 'eventos', len(evs), 'con córners en historial', n)
    except Exception as ex:
        log('espn_enrich', lg.get('code'), str(ex)[:100])

def half_from_event(ev, ch, ca, hg, ag):
    """Goles del 1.er tiempo (h1, a1) desde linescores o, si no hay, desde el minuto de cada gol. None si no es seguro."""
    try:
        h1, a1 = int(float(ch['linescores'][0]['value'])), int(float(ca['linescores'][0]['value']))
        if h1 <= hg and a1 <= ag:
            return h1, a1
    except Exception:
        pass
    try:
        det = [x for x in (ev['competitions'][0].get('details') or []) if x.get('scoringPlay')]
        if hg + ag == 0:
            return 0, 0
        if len(det) == hg + ag and not any('own' in str((x.get('type') or {}).get('text', '')).lower() for x in det):
            h1 = a1 = 0
            for x in det:
                mm = re.match(r"\s*(\d+)", str((x.get('clock') or {}).get('displayValue', '')))
                if not mm:
                    return None, None
                if int(mm.group(1)) <= 45:
                    tid = str((x.get('team') or {}).get('id'))
                    if tid == str(ch['team'].get('id')): h1 += 1
                    elif tid == str(ca['team'].get('id')): a1 += 1
                    else: return None, None
            return h1, a1
    except Exception:
        pass
    return None, None

def espn_history(lg):
    """Historial completo de una liga que football-data no tiene (Ecuador): marcadores, 1.er tiempo y córners desde ESPN. Se completa de a poco."""
    code = lg['code']
    H = CACHE.setdefault('hist', {}).setdefault(code, {'ev': {}, 'days': []})
    evs = H['ev']; days = set(H['days'])
    budget = ONLY_REQ
    for back in range(0, 400):
        d = TODAY - timedelta(days=back)
        if back > 2 and d.isoformat() in days:
            continue
        if budget <= 0 or time.time() > DEADLINE:
            break
        budget -= 1
        try:
            j = json.loads(fetch(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg['espn']}/scoreboard?dates={d:%Y%m%d}", tries=2))
        except Exception:
            continue
        complete = True
        for ev in j.get('events', []):
            try:
                if not ev['status']['type'].get('completed'):
                    continue
                eid = str(ev['id'])
                if eid in evs and evs[eid].get('v') == 2:
                    continue
                comp = ev['competitions'][0]['competitors']
                ch = next(c for c in comp if c['homeAway'] == 'home')
                ca = next(c for c in comp if c['homeAway'] == 'away')
                hg, ag = int(ch['score']), int(ca['score'])
                h1, a1 = half_from_event(ev, ch, ca, hg, ag)
                rec = dict(d=datetime.fromisoformat(ev['date'].replace('Z', '+00:00')).date().isoformat(), h=ch['team']['displayName'], a=ca['team']['displayName'],
                           hg=hg, ag=ag, h1=h1, a1=a1, hc=None, ac=None, hst=None, ast=None, hc1=None, ac1=None, v=2)
                hid, aid = str(ch['team'].get('id')), str(ca['team'].get('id'))
            except Exception:
                continue
            if budget <= 0 or time.time() > DEADLINE:
                complete = False
                break
            budget -= 1
            try:
                sj = json.loads(fetch(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{lg['espn']}/summary?event={eid}", tries=2))
                rec.update(corner_split(sj, rec['h'], rec['a'], hid, aid))
            except Exception:
                complete = False
                continue
            evs[eid] = rec
        if complete and back > 2:
            days.add(d.isoformat())
    H['days'] = sorted(days)
    out = [dict(e, d=date.fromisoformat(e['d'])) for e in evs.values() if date.fromisoformat(e['d']) >= TODAY - timedelta(days=WINDOW)]
    for m in out:
        m.pop('v', None)
    out.sort(key=lambda m: m['d'])
    log('espn historial solo', code, 'partidos', len(out), 'con córners', sum(1 for m in out if m['hc'] is not None), 'con 1T córners', sum(1 for m in out if m['hc1'] is not None))
    return out

# ---------- historial ----------
def load_history(lg):
    out = []
    if lg['kind'] == 'espn':
        return espn_history(lg)
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
                                hc=num(r.get('HC')), ac=num(r.get('AC')), hst=num(r.get('HST')), ast=num(r.get('AST')), hc1=None, ac1=None))
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
            out.append(dict(d=d, h=r['Home'].strip(), a=r['Away'].strip(), hg=hg, ag=ag, h1=None, a1=None, hc=None, ac=None, hst=None, ast=None, hc1=None, ac1=None))
    out.sort(key=lambda m: m['d'])
    return out

# ---------- modelo ----------
def chan_vals(m, chan):
    if chan == 'g':
        return m['hg'], m['ag']
    if chan == 'g1':
        return (m['h1'], m['a1']) if m['h1'] is not None and m['a1'] is not None else (None, None)
    if chan == 'c1':
        return (m['hc1'], m['ac1']) if m.get('hc1') is not None and m.get('ac1') is not None else (None, None)
    if chan == 'st':
        return (m['hst'], m['ast']) if m.get('hst') is not None and m.get('ast') is not None else (None, None)
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
    th, ta = [0.0] * 4, [0.0] * 4  # P(goles del equipo >= k), k=1..3
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
            for k in (1, 2, 3):
                if i >= k: th[k] += p
                if j >= k: ta[k] += p
    out = {'1': H, 'X': D, '2': V, '1X': H + D, 'X2': V + D, 'o15': o15, 'o25': o25, 'o35': o35, 'btts': bt, 'lh': lh, 'la': la}
    for k in (1, 2, 3):
        out[f'gh{k}'], out[f'ga{k}'] = th[k], ta[k]
    F1 = fit(hist, 'g1', ref)
    l1 = lambdas(F1, h, a)
    out['g1t'] = 1 - math.exp(-(l1[0] + l1[1])) if l1 else None
    out['g2t'] = (1 - math.exp(-max(lh + la - l1[0] - l1[1], 0.05))) if l1 else None
    Fs = fit(hist, 'st', ref)
    ls = lambdas(Fs, h, a)
    if ls:
        for L in (25, 35, 45, 55):
            k = L // 10 + 1
            out[f'sh{L}'], out[f'sa{L}'] = nb_tail(ls[0], k), nb_tail(ls[1], k)
    Fc = fit(hist, 'c', ref)
    lc = lambdas(Fc, h, a)
    if lc and Fc['T'].get(h, {}).get('n', 0) >= MIN_GAMES and Fc['T'].get(a, {}).get('n', 0) >= MIN_GAMES:
        mu = lc[0] + lc[1]
        out['c85'], out['c95'], out['c105'] = nb_tail(mu, 9), nb_tail(mu, 10), nb_tail(mu, 11)
        out['cmu'] = mu
        for L in (35, 45, 55, 65):
            k = L // 10 + 1
            out[f'ch{L}'], out[f'ca{L}'] = nb_tail(lc[0], k), nb_tail(lc[1], k)
    Fc1 = fit(hist, 'c1', ref)
    l1c = lambdas(Fc1, h, a)
    if l1c and Fc1['T'].get(h, {}).get('n', 0) >= MIN_GAMES and Fc1['T'].get(a, {}).get('n', 0) >= MIN_GAMES:
        mu1 = l1c[0] + l1c[1]
        out['c1t25'], out['c1t35'] = nb_tail(mu1, 3), nb_tail(mu1, 4)
        out['c1h15'], out['c1a15'] = nb_tail(l1c[0], 2), nb_tail(l1c[1], 2)
        out['c1h25'], out['c1a25'] = nb_tail(l1c[0], 3), nb_tail(l1c[1], 3)
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
    add('under', 'Menos de 1.5 goles', 1 - M['o15'])
    add('under', 'Menos de 2.5 goles', 1 - M['o25'], odds.get('u25'))
    add('under', 'Menos de 3.5 goles', 1 - M['o35'])
    add('btts', 'Ambos marcan', M['btts'])
    add('g1t', 'Gol en el 1er tiempo', M.get('g1t'))
    add('g2t', 'Gol en el 2.º tiempo', M.get('g2t'))
    for k, L in ((1, '0.5'), (2, '1.5'), (3, '2.5')):
        add('tg', f'Goles de {home} más de {L}', M[f'gh{k}'])
        add('tg', f'Goles de {away} más de {L}', M[f'ga{k}'])
    if 'ch35' in M:
        for L in (35, 45, 55, 65):
            add('corn', f'Córners de {home} más de {L / 10}', M[f'ch{L}'])
            add('corn', f'Córners de {away} más de {L / 10}', M[f'ca{L}'])
    if 'c85' in M:
        add('corn', 'Córners más de 8.5', M['c85'])
        add('corn', 'Córners más de 9.5', M['c95'])
        add('corn', 'Córners más de 10.5', M['c105'])
    if 'c1t25' in M:
        add('c1', 'Córners en el 1er tiempo más de 2.5', M['c1t25'])
        add('c1', 'Córners en el 1er tiempo más de 3.5', M['c1t35'])
        for L, ky in (('1.5', '15'), ('2.5', '25')):
            add('c1', f'Córners de {home} en el 1er tiempo más de {L}', M[f'c1h{ky}'])
            add('c1', f'Córners de {away} en el 1er tiempo más de {L}', M[f'c1a{ky}'])
    return B

def team_form(hist, team, home, k=10):
    """Últimos k partidos del equipo en esa condición (local o visitante), con lo que un tipster mira. Solo se incluye lo que tiene al menos 5 partidos con dato."""
    ms = [m for m in hist if m['d'] < TODAY and (m['h'] if home else m['a']) == team][-k:]
    rows = []
    for m in ms:
        gf, ga = (m['hg'], m['ag']) if home else (m['ag'], m['hg'])
        cf = ca = c1f = c1a = None
        if m['hc'] is not None and m['ac'] is not None:
            cf, ca = (m['hc'], m['ac']) if home else (m['ac'], m['hc'])
        if m.get('hc1') is not None and m.get('ac1') is not None:
            c1f, c1a = (m['hc1'], m['ac1']) if home else (m['ac1'], m['hc1'])
        g1 = None if m['h1'] is None or m['a1'] is None else (m['h1'] + m['a1'] > 0)
        gt = gf + ga
        ct = None if cf is None else cf + ca
        c1t = None if c1f is None else c1f + c1a
        rows.append(dict(sc=gf > 0, cn=ga > 0, bt=gf > 0 and ga > 0, o25=gf + ga > 2.5, g1=g1, gf=gf, ga=ga, cf=cf, ca=ca, c1f=c1f, c1a=c1a, ct=ct, c1t=c1t, gt=gt))
    out = {'n': len(rows)}
    if len(rows) < 5:
        return out
    for key in ('sc', 'cn', 'bt', 'o25', 'g1'):
        v = [r[key] for r in rows if r[key] is not None]
        if len(v) >= 5:
            out[key] = [sum(1 for x in v if x), len(v)]
    for key in ('gf', 'ga', 'gt', 'cf', 'ca', 'ct', 'c1f', 'c1a', 'c1t'):
        v = [r[key] for r in rows if r[key] is not None]
        if len(v) >= 5:
            out[key] = [round(sum(v) / len(v), 1), len(v)]
    return out

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
            '2': first(r, ['AvgA', 'B365A', 'PA', 'MaxA']), 'o25': first(r, ['Avg>2.5', 'B365>2.5', 'P>2.5']), 'u25': first(r, ['Avg<2.5', 'B365<2.5', 'P<2.5'])}

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
                    if l.get('flt') and lgname and lgname != l['flt']:
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

ALIAS = {'queens park rangers': 'qpr', 'wolverhampton wanderers': 'wolves', 'heart of midlothian': 'hearts',
         'manchester city': 'Man City', 'borussia mönchengladbach': "M'gladbach", 'fc cologne': 'FC Koln', 'athletic club': 'Ath Bilbao',
         'deportivo': 'La Coruna', 'rc celta fortuna': 'Celta B', 'real sociedad ii': 'Sociedad B', 'stade rennais': 'Rennes',
         'oh leuven': 'Oud-Heverlee Leuven', 'sporting cp': 'Sp Lisbon', 'amed sfk': 'Amedspor', 'erzurum bb': 'Erzurumspor',
         'istanbul basaksehir': 'Buyuksehyr', 'rapid vienna': 'SK Rapid', 'agf': 'Aarhus', 'f.c. københavn': 'FC Copenhagen',
         'sønderjyske fodbold': 'Sonderjyske', 'urawa red diamonds': 'Urawa Reds', 'pumas unam': 'UNAM Pumas',
         'hamarkameratene': 'HamKam', 'la galaxy': 'Los Angeles Galaxy', 'lafc': 'Los Angeles FC', 'red bull new york': 'New York Red Bulls'}

def match_team(name, teams):
    name = ALIAS.get(name.strip().lower(), name)
    for t in teams:
        if t.lower() == name.lower():
            return t
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
        un = (tot.get('under') or {}).get('close') or (tot.get('under') or {}).get('open') or {}
        if str(un.get('line', '')).lower().replace('u', '') == '2.5':
            o['u25'] = am2dec(un.get('odds'))
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
            st = status['leagues'][l['code']]
            st['espn_fail'] = st.get('espn_fail', 0) + 1
            continue
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
                miss += 1
                status['leagues'][l['code']].setdefault('unmatched_names', []).extend([n for n, t in ((h, th), (a, ta)) if not t])
                continue
            try:
                if ev['status']['type']['name'] != 'STATUS_SCHEDULED':
                    continue
            except Exception:
                pass
            nm = status['leagues'][l['code']].setdefault('name_map', {})
            for x, y in ((h, th), (a, ta)):
                if x != y: nm[x] = y
            out.append(dict(k=k, h=th, a=ta, odds=espn_odds(ev), src='espn'))
    return out, miss

def slug(s):
    return '-'.join(norm(s))

# ---------- backtest ----------
BT_KEYS = ('c1t25', 'c1t35', 'c1m15', 'c1m25', '1', 'X', '2', 'o15', 'o25', 'o35', 'btts', 'g1t', 'c85', 'c95', 'c105', 'ct35', 'ct45', 'ct55', 'ct65', 'tg1', 'tg2', 'tg3', 'g2t', 'st25', 'st35', 'st45', 'st55')

def backtest(hist, days=120):
    recs = {k: [] for k in BT_KEYS}
    start = TODAY - timedelta(days=days)
    test = [m for m in hist if start <= m['d'] < TODAY]
    for m in test:
        M = markets(hist, m['h'], m['a'], m['d'])
        if not M: continue
        t = m['hg'] + m['ag']
        res = {'1': m['hg'] > m['ag'], 'X': m['hg'] == m['ag'], '2': m['hg'] < m['ag'], 'o15': t > 1, 'o25': t > 2, 'o35': t > 3,
               'btts': m['hg'] > 0 and m['ag'] > 0}
        if m['h1'] is not None and m['a1'] is not None and M.get('g1t') is not None:
            res['g1t'] = (m['h1'] + m['a1']) > 0
        if m['hc'] is not None and m['ac'] is not None and 'c85' in M:
            c = m['hc'] + m['ac']
            res['c85'], res['c95'], res['c105'] = c > 8.5, c > 9.5, c > 10.5
        for k, v in res.items():
            recs[k].append((M[k], 1 if v else 0))
        if m['h1'] is not None and m['a1'] is not None and M.get('g2t') is not None:
            recs['g2t'].append((M['g2t'], 1 if (m['hg'] - m['h1']) + (m['ag'] - m['a1']) > 0 else 0))
        if m.get('hst') is not None and m.get('ast') is not None and 'sh25' in M:
            for L in (25, 35, 45, 55):
                recs[f'st{L}'].append((M[f'sh{L}'], 1 if m['hst'] > L / 10 else 0))
                recs[f'st{L}'].append((M[f'sa{L}'], 1 if m['ast'] > L / 10 else 0))
        for k in (1, 2, 3):
            recs[f'tg{k}'].append((M[f'gh{k}'], 1 if m['hg'] >= k else 0))
            recs[f'tg{k}'].append((M[f'ga{k}'], 1 if m['ag'] >= k else 0))
        if m['hc'] is not None and m['ac'] is not None and 'ch35' in M:
            for L in (35, 45, 55, 65):
                recs[f'ct{L}'].append((M[f'ch{L}'], 1 if m['hc'] > L / 10 else 0))
                recs[f'ct{L}'].append((M[f'ca{L}'], 1 if m['ac'] > L / 10 else 0))
        if m.get('hc1') is not None and m.get('ac1') is not None and 'c1t25' in M:
            c1 = m['hc1'] + m['ac1']
            recs['c1t25'].append((M['c1t25'], 1 if c1 > 2.5 else 0))
            recs['c1t35'].append((M['c1t35'], 1 if c1 > 3.5 else 0))
            for L, ky in ((1.5, '15'), (2.5, '25')):
                recs[f'c1m{ky}'].append((M[f'c1h{ky}'], 1 if m['hc1'] > L else 0))
                recs[f'c1m{ky}'].append((M[f'c1a{ky}'], 1 if m['ac1'] > L else 0))
    return recs

def summarize(recs):
    out = {}
    for k, v in recs.items():
        if not v: continue
        bins = []
        edges = [0, .3, .4, .5, .6, .7, .8, 1.01]
        for lo, hi in zip(edges, edges[1:]):
            x = [r for r in v if lo <= r[0] < hi]
            if x:
                bins.append(dict(lo=lo, hi=min(hi, 1), n=len(x), pred=round(sum(r[0] for r in x) / len(x), 3), real=round(sum(r[1] for r in x) / len(x), 3)))
        base = sum(r[1] for r in v) / len(v)
        out[k] = dict(n=len(v), brier=round(sum((p - y) ** 2 for p, y in v) / len(v), 4),
                      brier_base=round(sum((base - y) ** 2 for p, y in v) / len(v), 4),
                      avg_pred=round(sum(r[0] for r in v) / len(v), 3), real=round(base, 3), bins=bins)
    return out

CAL_KEYS = ('c1t25', 'c1t35', 'c1m15', 'c1m25', 'o15', 'o25', 'o35', 'btts', 'g1t', 'c85', 'c95', 'c105', 'ct35', 'ct45', 'ct55', 'ct65', 'tg1', 'tg2', 'tg3', 'g2t', 'st25', 'st35', 'st45', 'st55')

def make_calibration(summary):
    """Corrige el sesgo del modelo con lo que paso en partidos reales (por mercado, con interpolacion y encogimiento)."""
    cal = {}
    for k in CAL_KEYS:
        r = summary.get(k)
        if not r: continue
        pts = []
        for b in r['bins']:
            if b['n'] >= 30:
                w = b['n'] / (b['n'] + 300.0)
                pts.append((b['pred'], b['pred'] + w * (b['real'] - b['pred'])))
        if len(pts) >= 2:
            cal[k] = sorted(pts)
    return cal

LG_OFF = 0.0  # correccion extra de la liga que se esta procesando (se fija en main)

def make_league_offsets(cal, lrecs):
    """Por liga: que tanto se aparta lo real de lo que dice el modelo ya corregido en apuestas de 60% o mas. Con encogimiento y tope."""
    out = {}
    for code, r in lrecs.items():
        n = 0; sp = 0.0; sy = 0.0
        for k in CAL_KEYS:
            for p, y in r.get(k, []):
                q = apply_cal(cal, k, p)
                if q is not None and q >= 0.6:
                    n += 1; sp += q; sy += y
        if n >= 60:
            d = (sy - sp) / n
            w = n / (n + 400.0)
            out[code] = (round(max(-0.06, min(0.06, d * w)), 4), n, round(sp / n, 3), round(sy / n, 3))
    return out

def apply_cal(cal, k, p):
    pts = cal.get(k)
    if p is None or not pts: return p
    if p <= pts[0][0]:
        q = p + (pts[0][1] - pts[0][0])
    elif p >= pts[-1][0]:
        q = p + (pts[-1][1] - pts[-1][0])
    else:
        q = p
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= p <= x1:
                t = (p - x0) / (x1 - x0) if x1 > x0 else 0
                q = y0 + t * (y1 - y0); break
    q = q + LG_OFF * 4 * q * (1 - q)
    return min(0.98, max(0.02, q))

def espn_results(l, teams):
    """Marcadores finales de ayer y hoy desde ESPN (solo goles). Nunca debe romper el proceso."""
    out = []
    for i in (0, 1, 2):
        d = TODAY - timedelta(days=i)
        try:
            j = json.loads(fetch(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{l['espn']}/scoreboard?dates={d:%Y%m%d}", tries=2))
        except Exception:
            continue
        for ev in j.get('events', []):
            try:
                if not ev['status']['type'].get('completed'):
                    continue
                comp = ev['competitions'][0]['competitors']
                ch = next(c for c in comp if c['homeAway'] == 'home')
                ca = next(c for c in comp if c['homeAway'] == 'away')
                th, ta = match_team(ch['team']['displayName'], teams), match_team(ca['team']['displayName'], teams)
                hg, ag = int(ch['score']), int(ca['score'])
                k = datetime.fromisoformat(ev['date'].replace('Z', '+00:00'))
            except Exception:
                continue
            h1 = a1 = None
            try:  # marcador del primer tiempo desde linescores
                h1, a1 = int(float(ch['linescores'][0]['value'])), int(float(ca['linescores'][0]['value']))
                if h1 > hg or a1 > ag:
                    h1 = a1 = None
            except Exception:
                h1 = a1 = None
            if h1 is None:  # sin linescores: se calcula con el minuto de cada gol (45'+x = 1.er tiempo)
                try:
                    det = [x for x in (ev['competitions'][0].get('details') or []) if x.get('scoringPlay')]
                    if hg + ag == 0:
                        h1 = a1 = 0
                    elif len(det) == hg + ag and not any('own' in str((x.get('type') or {}).get('text', '')).lower() for x in det):
                        h1 = a1 = 0
                        for x in det:
                            mm = re.match(r"\s*(\d+)", str((x.get('clock') or {}).get('displayValue', '')))
                            if not mm:
                                raise ValueError('sin minuto')
                            if int(mm.group(1)) <= 45:
                                tid = str((x.get('team') or {}).get('id'))
                                if tid == str(ch['team'].get('id')): h1 += 1
                                elif tid == str(ca['team'].get('id')): a1 += 1
                                else: raise ValueError('equipo')
                except Exception:
                    h1 = a1 = None
            if th and ta:
                out.append(dict(l=l['code'], h=th, a=ta, d=k.date().isoformat(), hg=hg, ag=ag, h1=h1, a1=a1, hc=None, ac=None, hst=None, ast=None, hc1=None, ac1=None, _id=ev.get('id'), _hid=str(ch['team'].get('id')), _aid=str(ca['team'].get('id')), _hn=ch['team']['displayName'], _an=ca['team']['displayName']))
    return out

def espn_corners(l, e):
    """Córners y remates al arco desde el detalle del partido en ESPN. Si no hay dato, queda en None. Nunca rompe el proceso."""
    try:
        j = json.loads(fetch(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{l['espn']}/summary?event={e['_id']}", tries=2))
        r = corner_split(j, e.get('_hn', e['h']), e.get('_an', e['a']), e['_hid'], e['_aid'])
        for k in ('hc', 'ac', 'hst', 'ast', 'hc1', 'ac1'):
            if r[k] is not None:
                e[k] = r[k]
        if r['hc'] is not None:
            log('corners', 'espn', l['code'], e['h'], e['a'], r['hc'], r['ac'], '1T', r['hc1'], r['ac1'])
    except Exception as ex:
        log('detalle espn sin dato', l['code'], str(ex)[:60])

def build_results(H):
    res, cut = [], TODAY - timedelta(days=14)
    for l in LEAGUES:
        code = l['code']
        got = []
        for m in H.get(code, []):
            if m['d'] >= cut:
                got.append(dict(l=code, h=m['h'], a=m['a'], d=m['d'].isoformat(), hg=int(m['hg']), ag=int(m['ag']),
                                h1=None if m['h1'] is None else int(m['h1']), a1=None if m['a1'] is None else int(m['a1']),
                                hc=None if m['hc'] is None else int(m['hc']), ac=None if m['ac'] is None else int(m['ac']),
                                hst=None if m.get('hst') is None else int(m['hst']), ast=None if m.get('ast') is None else int(m['ast']),
                                hc1=None if m.get('hc1') is None else int(m['hc1']), ac1=None if m.get('ac1') is None else int(m['ac1'])))
        try:
            for e in espn_results(l, status['leagues'][code].get('teams', [])):
                dup = any(g['h'] == e['h'] and g['a'] == e['a'] and abs((date.fromisoformat(g['d']) - date.fromisoformat(e['d'])).days) <= 1 for g in got)
                if not dup:
                    espn_corners(l, e)
                    got.append(e)
        except Exception as ex:
            log('resultados espn', code, str(ex)[:100])
        for g in got:
            for k in ('_id', '_hid', '_aid', '_hn', '_an'):
                g.pop(k, None)
        res += got
    return res

def main():
    global CACHE, DEADLINE, LG_OFF
    CACHE = load_cache(); DEADLINE = time.time() + RUN_SECONDS
    fx = load_fixtures()
    LREC = {}
    bt, pooled, H, F = {}, {'ALL': {k: [] for k in BT_KEYS}, 'FAV': {k: [] for k in BT_KEYS}}, {}, {}
    # --- pasada 1: historial y prueba contra partidos reales
    for l in LEAGUES:
        code = l['code']
        st = status['leagues'][code] = dict(name=l['name'])
        hist = load_history(l)
        if l.get('espn') and l['kind'] != 'espn':
            espn_enrich(l, hist)
        H[code] = hist
        st['hist'] = len(hist)
        st['last_result'] = hist[-1]['d'].isoformat() if hist else None
        st['has_corners'] = sum(1 for m in hist if m['hc'] is not None)
        st['has_half'] = sum(1 for m in hist if m['h1'] is not None)
        st['teams'] = sorted({m['h'] for m in hist} | {m['a'] for m in hist})
        st['fav'] = l['fav']
        try:
            r = backtest(hist)
            LREC[code] = r
            bt[code] = summarize(r)
            for k in BT_KEYS:
                pooled['ALL'][k] += r[k]
                if l['fav']: pooled['FAV'][k] += r[k]
        except Exception as e:
            status['errors'].append(f'backtest {code}: {e}')
    save_cache()
    allsum = summarize(pooled['ALL'])
    cal = make_calibration(allsum)
    LOFF = make_league_offsets(cal, LREC)
    status['league_offsets'] = {k: dict(off=v[0], n=v[1], model=v[2], real=v[3]) for k, v in LOFF.items()}
    # --- pasada 2: calendario y predicciones (con correccion)
    matches = []
    for l in LEAGUES:
        code = l['code']; st = status['leagues'][code]; hist = H[code]; teams = st['teams']
        LG_OFF = LOFF.get(code, (0.0,))[0]
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
            M['g1t'] = apply_cal(cal, 'g1t', M.get('g1t'))
            M['g2t'] = apply_cal(cal, 'g2t', M.get('g2t'))
            for L in (25, 35, 45, 55):
                for pre in ('sh', 'sa'):
                    if f'{pre}{L}' in M: M[f'{pre}{L}'] = apply_cal(cal, f'st{L}', M[f'{pre}{L}'])
            for k in ('o15', 'o25', 'o35', 'btts'):
                M[k] = apply_cal(cal, k, M[k])
            for k, ck in (('c1t25', 'c1t25'), ('c1t35', 'c1t35')):
                if k in M: M[k] = apply_cal(cal, ck, M[k])
            for k in ('c1h15', 'c1a15', 'c1h25', 'c1a25'):
                if k in M: M[k] = apply_cal(cal, 'c1m' + k[3:], M[k])
            for k, ck in (('c85', 'c85'), ('c95', 'c95'), ('c105', 'c105')):
                if k in M: M[k] = apply_cal(cal, ck, M[k])
            for k in (1, 2, 3):
                for pre in ('gh', 'ga'):
                    M[f'{pre}{k}'] = apply_cal(cal, f'tg{k}', M[f'{pre}{k}'])
            for L in (35, 45, 55, 65):
                for pre in ('ch', 'ca'):
                    if f'{pre}{L}' in M: M[f'{pre}{L}'] = apply_cal(cal, f'ct{L}', M[f'{pre}{L}'])
            matches.append(dict(id=f"{code}-{f['k']:%Y%m%d}-{slug(f['h'])}-{slug(f['a'])}", league=code, leagueName=l['name'],
                                utc=f['k'].strftime('%Y-%m-%dT%H:%M:%SZ'), home=f['h'], away=f['a'], src=f['src'], fav=l['fav'],
                                oddsFrom=('promedio de casas' if f['src'] == 'fd' else ('DraftKings' if any(f['odds'].values()) else None)),
                                lh=round(M['lh'], 2), la=round(M['la'], 2), form=dict(h=team_form(hist, f['h'], True), a=team_form(hist, f['a'], False)),
                                bets=bets_for(M, f['h'], f['a'], f['odds'])))
            done += 1
        st['matches'] = done
    matches.sort(key=lambda m: m['utc'])
    status['calibration'] = {k: [[round(x, 3), round(y, 3)] for x, y in v] for k, v in cal.items()}
    json.dump(dict(generated=NOW.strftime('%Y-%m-%dT%H:%M:%SZ'), matches=matches, status=status), open('data.json', 'w'), ensure_ascii=False, separators=(',', ':'))
    bt['ALL'] = allsum; bt['FAV'] = summarize(pooled['FAV'])
    try:
        rs = build_results(H)
        json.dump(dict(generated=NOW.strftime('%Y-%m-%dT%H:%M:%SZ'), results=rs), open('results.json', 'w'), ensure_ascii=False, separators=(',', ':'))
        log('resultados:', len(rs))
    except Exception as ex:
        status['errors'].append('resultados: ' + str(ex)[:150])
    json.dump(dict(generated=NOW.strftime('%Y-%m-%dT%H:%M:%SZ'), leagues=bt), open('backtest.json', 'w'), ensure_ascii=False, indent=1)
    log(json.dumps(status, indent=1, ensure_ascii=False)[:3000]); log('partidos:', len(matches))


if __name__ == '__main__':
    main()
