import urllib.request, json, datetime as dt
UA={'User-Agent':'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1','Accept':'application/json'}
def get(u):
    try: return json.loads(urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=30).read())
    except Exception as e: return {'err':str(e)[:100]}
def strip(o):
    if isinstance(o,dict): return {k:strip(v) for k,v in o.items() if k not in('link','logos','provider')}
    if isinstance(o,list): return [strip(x) for x in o]
    return o
out=[]
j=get('https://site.api.espn.com/apis/site/v2/sports/soccer/eng.2/scoreboard?dates=20261031')
ev=j['events'][0];out.append(json.dumps(strip(ev['competitions'][0].get('odds')),indent=0)[:2500])
for slug in ['sui.1','swz.1','sui.super_league']:
    j=get(f'https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard');out.append(slug+' '+str(j.get('leagues',[{}])[0].get('name') if 'leagues' in j else j)+' eventos '+str(len(j.get('events',[]))) + ' calendar ' + str(j.get('leagues',[{}])[0].get('calendarStartDate') if 'leagues' in j else ''))
open('probe_out.txt','w').write('\n'.join(out));print('\n'.join(out))
