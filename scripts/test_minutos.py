# PRUEBA (no toca data.json): ¿ESPN trae el minuto de cada gol, y cuántos partidos por equipo alcanzamos?
import json, re, sys, time, urllib.request, datetime as dt, collections
H={'User-Agent':'Mozilla/5.0'}
def get(u,t=2):
    for i in range(t):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=25).read())
        except Exception as e:
            err=e; time.sleep(1.5)
    raise err
def minute(s):
    m=re.match(r"\s*(\d+)'?(?:\s*\+\s*(\d+))?",str(s or ''))
    return (int(m.group(1)),int(m.group(2) or 0)) if m else None
LG={'mex.1':'Liga MX','usa.1':'MLS','bra.1':'Brasileirão','arg.1':'Argentina','eng.1':'Premier','eng.2':'Championship','ger.2':'Bundesliga 2'}
DAYS=int(sys.argv[1]) if len(sys.argv)>1 else 60
today=dt.date.today()
for code,name in LG.items():
    print('\n=====',name,code)
    evs=[]
    a=today-dt.timedelta(days=DAYS)
    try:
        evs=get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{code}/scoreboard?dates={a:%Y%m%d}-{today:%Y%m%d}")['events']
    except Exception as e:
        print('rango falló, voy día por día:',str(e)[:60]); evs=[]
        d=a
        while d<=today:
            try: evs+=get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{code}/scoreboard?dates={d:%Y%m%d}",1).get('events',[])
            except Exception: pass
            d+=dt.timedelta(days=1)
    done=[e for e in evs if e.get('status',{}).get('type',{}).get('completed')]
    print('partidos terminados en',DAYS,'días:',len(done))
    if not done: continue
    withd=0; goals=0; goalsmin=0; per=collections.defaultdict(int); tr=collections.defaultdict(lambda:[0]*7)
    sample=None; viasum=0
    for e in done:
        c=e['competitions'][0]; det=c.get('details') or []
        sc=[d for d in det if d.get('scoringPlay')]
        tot=sum(int(t.get('score') or 0) for t in c['competitors'])
        src='scoreboard'
        if tot>0 and not sc:
            try:
                s=get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{code}/summary?event={e['id']}")
                sc=[d for d in (s.get('keyEvents') or []) if d.get('scoringPlay')] or [d for d in (s.get('details') or []) if d.get('scoringPlay')]
                src='summary'; viasum+=1
            except Exception as ex: pass
        goals+=tot
        ok=0
        tid={t['team']['id']:t['team']['displayName'] for t in c['competitors']}
        for d in sc:
            mm=minute((d.get('clock') or {}).get('displayValue'))
            if mm is None: continue
            ok+=1
            b=min(mm[0]//15,5) if mm[0]<90 else 5
            tm=(d.get('team') or {}).get('id')
            if tm in tid:
                other=[x for x in tid if x!=tm]
                per[tid[tm]]+=1
                tr[tid[tm]][b]+=1
        goalsmin+=ok
        if sample is None and sc: sample=(src,e['name'],[ (x.get('clock',{}).get('displayValue'),(x.get('team') or {}).get('id'),x.get('type',{}).get('text')) for x in sc])
        if tot>0: withd+= (ok>=tot-0) and 1 or 0
    print('goles totales (marcador):',goals,'| con minuto:',goalsmin,f'({100*goalsmin//max(goals,1)}%)','| partidos con TODOS sus goles con minuto:',withd,'de',len(done),'| detalle pedido a summary:',viasum)
    print('ejemplo:',sample)
    npart=collections.Counter()
    for e in done:
        for t in e['competitions'][0]['competitors']: npart[t['team']['displayName']]+=1
    v=sorted(npart.values())
    print('partidos por equipo: min',v[0],'mediana',v[len(v)//2],'max',v[-1],'| equipos',len(v))
    top=sorted(tr.items(),key=lambda x:-sum(x[1]))[:3]
    for n,b in top: print('  ',n,'goles a favor por tramo 0-15,15-30,30-45,45-60,60-75,75-90+:',b[:6])
