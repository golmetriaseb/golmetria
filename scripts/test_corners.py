# PRUEBA (no toca data.json): ¿ESPN trae córners (y remates) por partido en las ligas sin historial?
import json, time, urllib.request, datetime as dt, collections
H={'User-Agent':'Mozilla/5.0'}
def get(u,t=2):
    for i in range(t):
        try: return json.loads(urllib.request.urlopen(urllib.request.Request(u,headers=H),timeout=25).read())
        except Exception as e: err=e; time.sleep(1.5)
    raise err
LG={'bra.1':'Brasil','mex.1':'Liga MX','usa.1':'MLS','arg.1':'Argentina','jpn.1':'Japón'}
today=dt.date.today()
for code,name in LG.items():
    print('\n=====',name,code)
    evs=[]
    d=today
    while len(evs)<40 and (today-d).days<90:
        try: evs+=[e for e in get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{code}/scoreboard?dates={d:%Y%m%d}",1).get('events',[]) if e['status']['type'].get('completed')]
        except Exception: pass
        d-=dt.timedelta(days=1)
    evs=evs[:40]; ok=zero=none=err=0; ex=None; sot=0
    for e in evs:
        try:
            j=get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{code}/summary?event={e['id']}")
            got={}
            for t in j['boxscore']['teams']:
                for st in t.get('statistics',[]):
                    if st.get('name') in('wonCorners','shotsOnTarget'):
                        got.setdefault(st['name'],[]).append(st.get('displayValue'))
            c=got.get('wonCorners')
            if not c or len(c)<2: none+=1
            else:
                v=[int(float(x)) for x in c]
                if sum(v)==0: zero+=1
                else:
                    ok+=1
                    if ex is None: ex=(e['name'],v)
            if got.get('shotsOnTarget') and sum(int(float(x)) for x in got['shotsOnTarget'])>0: sot+=1
        except Exception as x: err+=1
    n=len(evs)
    print(f'partidos revisados: {n} | con córners válidos: {ok} | en 0-0 (sin dato): {zero} | sin el campo: {none} | error: {err} | con remates al arco: {sot}')
    print('ejemplo:',ex)
