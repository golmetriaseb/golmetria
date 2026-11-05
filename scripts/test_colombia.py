# PRUEBA (no toca data.json): ¿ESPN tiene la Colombia?
import json, time, re, urllib.request, datetime as dt, collections
H={'User-Agent':'Mozilla/5.0'}
def get(u,t=2):
    for i in range(t):
        try: return json.loads(urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=25).read())
        except Exception as e: err=e; time.sleep(1.5)
    raise err
for code in ('col.1','col.2'):
    print('\n=====',code)
    today=dt.date.today(); evs=[]; fut=[]
    d=today-dt.timedelta(days=200)
    while d<=today+dt.timedelta(days=7):
        try:
            for e in get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{code}/scoreboard?dates={d:%Y%m%d}",1).get('events',[]):
                (evs if e['status']['type'].get('completed') else fut).append(e)
        except Exception: pass
        d+=dt.timedelta(days=1)
    print('terminados (200 días):',len(evs),'| próximos/en juego (7 días):',len(fut))
    teams=set()
    for e in evs:
        for t in e['competitions'][0]['competitors']: teams.add(t['team']['displayName'])
    print('equipos:',len(teams),sorted(teams)[:30])
    if evs:
        c=collections.Counter(e['date'][:7] for e in evs); print('por mes:',dict(sorted(c.items())))
        ok=zero=0; mins=0; g=0
        for e in evs[-25:]:
            try:
                j=get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{code}/summary?event={e['id']}")
                s=sum(int(float(x['displayValue'])) for t in j['boxscore']['teams'] for x in t.get('statistics',[]) if x.get('name')=='wonCorners' and x.get('displayValue') not in (None,''))
                if s>0: ok+=1
                else: zero+=1
                det=[x for x in e['competitions'][0].get('details',[]) if x.get('scoringPlay')]
                g+=sum(int(t.get('score') or 0) for t in e['competitions'][0]['competitors']); mins+=len(det)
            except Exception as ex: zero+=1
        print('últimos 25: con córners:',ok,'| sin dato:',zero,'| goles marcador',g,'| goles con minuto',mins)
    for e in fut[:6]:
        c=e['competitions'][0]; print('próximo:',e['name'],e['date'],'| odds' ,bool(c.get('odds')))
