import urllib.request, json, csv, io, collections
UA_B={'User-Agent':'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1','Accept':'application/json,text/plain,*/*'}
out=[]
def get(u,h=None):
    try:
        r=urllib.request.urlopen(urllib.request.Request(u,headers=h or UA_B),timeout=30)
        return r.status,r.read().decode('utf-8','replace')
    except Exception as e:
        return 'ERR',str(e)[:150]
def p(*a): out.append(' '.join(str(x) for x in a))
# fixtures.csv
s,t=get('https://www.football-data.co.uk/fixtures.csv')
p('fixtures.csv',s,len(t))
if s==200:
    rows=list(csv.DictReader(io.StringIO(t.lstrip('﻿'))))
    c=collections.Counter(r.get('Div') for r in rows);p('Div counts',dict(c))
    for d in ('E1','D2','SC0'):
        ds=sorted({r['Date'] for r in rows if r.get('Div')==d});p(d,'fechas',ds)
    p('cols',list(rows[0].keys())[:20])
s,t=get('https://www.football-data.co.uk/new_league_fixtures.csv')
p('new_league_fixtures',s)
if s==200:
    rows=list(csv.DictReader(io.StringIO(t.lstrip('﻿'))))
    c=collections.Counter((r.get('Country'),r.get('League')) for r in rows);p(dict(c));p('cols',list(rows[0].keys()))
# ESPN
for u in ['https://site.api.espn.com/apis/site/v2/sports/soccer/eng.2/scoreboard?dates=20261031',
          'https://site.web.api.espn.com/apis/site/v2/sports/soccer/eng.2/scoreboard?dates=20261031',
          'https://site.api.espn.com/apis/site/v2/sports/soccer/eng.2/scoreboard']:
    s,t=get(u);p('ESPN',u[:70],s,t[:100].replace('\n',' '))
# TheSportsDB
for name,id_ in [('ENG',4329),('GER2',4399),('SCO',4330),('BRA',4351),('SUI',4413)]:
    s,t=get(f'https://www.thesportsdb.com/api/v1/json/3/eventsnextleague.php?id={id_}')
    n=0;sample=''
    if s==200:
        try:
            j=json.loads(t);ev=j.get('events') or []
            n=len(ev);sample=[(e['dateEvent'],e['strHomeTeam'],e['strAwayTeam'],e.get('strLeague')) for e in ev[:3]]
        except Exception as e: sample=str(e)
    p('TSDB',name,id_,s,n,sample)
s,t=get('https://www.thesportsdb.com/api/v1/json/3/search_all_leagues.php?c=Switzerland&s=Soccer');p('TSDB swiss leagues',s,t[:300])
# OpenLigaDB
s,t=get('https://api.openligadb.de/getmatchdata/bl2/2026')
p('OpenLiga bl2/2026',s,len(t) if s==200 else t)
if s==200:
    j=json.loads(t);fut=[m for m in j if not m.get('matchIsFinished')][:3]
    p([(m['matchDateTimeUTC'],m['team1']['teamName'],m['team2']['teamName']) for m in fut])
open('probe_out.txt','w').write('\n'.join(out))
print('\n'.join(out))
