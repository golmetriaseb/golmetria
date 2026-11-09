import sys
sys.path.insert(0, 'scripts')
import build as B
print('NOW', B.NOW, 'HORIZON', B.HORIZON)
fx = B.load_fixtures()['LL2']
for f in fx: print('FD', f['k'], f['h'], '-', f['a'])
l = [x for x in B.LEAGUES if x['code'] == 'LL2'][0]
hist = B.load_history(l)
teams = sorted({m['h'] for m in hist} | {m['a'] for m in hist})
print('has Las Palmas', 'Las Palmas' in teams, 'has Eldense', 'Eldense' in teams, len(teams))
ef, miss = B.espn_fixtures(l, teams)
print('miss', miss)
for f in ef: print('ESPN', f['k'], f['h'], '-', f['a'])
