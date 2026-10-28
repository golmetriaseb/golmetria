import urllib.request, json, datetime as dt
UA={'User-Agent':'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1','Accept':'application/json'}
out=[]
def p(*a): out.append(' '.join(str(x) for x in a))
def get(u):
    try: return json.loads(urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=30).read())
    except Exception as e: return {'err':str(e)[:100]}
today=dt.date.today()
for slug in ['eng.2','ger.2','sco.1','sui.1','bra.1']:
    tot=0;ex=None;days={}
    for i in range(8):
        d=today+dt.timedelta(days=i)
        j=get(f'https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard?dates={d:%Y%m%d}')
        if 'err' in j: p(slug,d,j['err']);continue
        ev=j.get('events',[]);days[str(d)]=len(ev);tot+=len(ev)
        if ev and not ex: ex=ev[0]
    p(slug,'total',tot,days)
    if ex:
        c=ex['competitions'][0]
        p('  ejemplo',ex['date'],[(x['homeAway'],x['team']['displayName']) for x in c['competitors']],'status',ex['status']['type']['name'])
        p('  odds',json.dumps(c.get('odds'))[:600])
open('probe_out.txt','w').write('\n'.join(out));print('\n'.join(out))
