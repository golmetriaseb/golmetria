# PRUEBA (no toca data.json): ¿el relato jugada por jugada de ESPN trae cada córner con su minuto?
import json, time, re, urllib.request, datetime as dt
H={'User-Agent':'Mozilla/5.0'}
def get(u,t=2):
    for i in range(t):
        try: return json.loads(urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=25).read())
        except Exception as e: err=e; time.sleep(1.5)
    raise err
LG={'bra.1':'Brasil','mex.1':'Liga MX','usa.1':'MLS','arg.1':'Argentina','eng.2':'Championship','ger.2':'Bundesliga 2'}
today=dt.date.today()
for code,name in LG.items():
    print('\n=====',name,code)
    evs=[]; d=today
    while len(evs)<20 and (today-d).days<60:
        try: evs+=[e for e in get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{code}/scoreboard?dates={d:%Y%m%d}",1).get('events',[]) if e['status']['type'].get('completed')]
        except Exception: pass
        d-=dt.timedelta(days=1)
    evs=evs[:20]; exact=near=nocomm=0; shown=0; tot=ct=c1=0
    for e in evs:
        try:
            j=get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{code}/summary?event={e['id']}")
        except Exception: continue
        stat=0
        for t in j['boxscore']['teams']:
            for s in t.get('statistics',[]):
                if s.get('name')=='wonCorners':
                    try: stat+=int(float(s['displayValue']))
                    except Exception: pass
        com=j.get('commentary') or []
        if not com: nocomm+=1; continue
        cs=[x for x in com if re.match(r'\s*corner\b',str(x.get('text','')),re.I)]
        if shown<2 and cs:
            print('  ejemplo texto:',cs[0].get('text'),'| minuto:',(cs[0].get('time') or {}).get('displayValue'),'| claves:',list(cs[0].keys())[:8]); shown+=1
        n=len(cs); first=0
        for x in cs:
            m=re.match(r"\s*(\d+)",str((x.get('time') or {}).get('displayValue','')))
            if m and int(m.group(1))<=45: first+=1
        if stat>0:
            tot+=stat; ct+=n; c1+=first
            if n==stat: exact+=1
            elif abs(n-stat)<=1: near+=1
    print(f'partidos: {len(evs)} | sin relato: {nocomm} | córners del relato = estadística exacta: {exact} | a ±1: {near} | suma estadística: {tot} | suma relato: {ct} | del relato en 1er tiempo: {c1}')
