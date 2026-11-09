import json, urllib.request
for d in ('20261108','20261109','20261110'):
    try:
        j = json.load(urllib.request.urlopen(urllib.request.Request(f'https://site.api.espn.com/apis/site/v2/sports/soccer/esp.2/scoreboard?dates={d}', headers={'User-Agent': 'Mozilla/5.0'}), timeout=30))
    except Exception as e:
        print(d, 'ERR', e); continue
    for ev in j.get('events', []):
        c = ev['competitions'][0]['competitors']
        print(d, ev['date'], [x['team']['displayName'] for x in c], ev['status']['type']['name'], ev['status']['type'].get('completed'), ev['status'].get('displayClock'))
