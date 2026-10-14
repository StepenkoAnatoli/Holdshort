from pathlib import Path
import copy
import json
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'tools'))
import live_dispatcher as ld
import conform_spec as cs

prices={'pilot_caps':{'max_attempts_per_task':4,'max_cost_per_task_usd':1.0,
    'max_cost_per_pilot_usd':1.0,'max_elapsed_seconds_per_task':300,
    'same_profile_repairs_allowed_per_task':1},
    'profiles':{'P':{'input_rate_per_mtok':1.0,'output_rate_per_mtok':0.0}}}
result={}
with tempfile.TemporaryDirectory() as td:
    p=Path(td); calls=[]
    def fake(*args): calls.append(1); return (1_000_000,0)
    d=ld.LiveDispatcher(prices,p/'calls.jsonl',confirm_egress=True,dispatch_fn=fake)
    first=d.attempt('A','P','synthetic',work_bound=1,review_bound=0)
    second=d.attempt('A','P','synthetic',work_bound=.01,review_bound=0)
    result['remaining_task_cap']={'transport_calls':len(calls),'decisions':[first.decision,second.decision],
                                  'accounted_spend':d.pilot_spent}
with tempfile.TemporaryDirectory() as td:
    p=Path(td); path=p/'pilot.jsonl'
    accepted=[]
    for name in ('A','B'):
        d=ld.LiveDispatcher(prices,path)
        accepted.append(d.attempt(name,'P','synthetic',work_bound=.75,review_bound=0,
                                  expected_in=750_000,expected_out=0).decision)
    result['shared_pilot']={'decisions':accepted}
with tempfile.TemporaryDirectory() as td:
    d=ld.LiveDispatcher(prices,Path(td)/'nan.jsonl')
    result['nan_work_bound']={'decision':d.attempt('A','P','synthetic',work_bound=float('nan'),
                                                review_bound=.01,expected_in=0).decision}
with tempfile.TemporaryDirectory() as td:
    clock=[1000.0]
    d=ld.LiveDispatcher(prices,Path(td)/'clock.jsonl',now_fn=lambda:clock[0])
    d._task('A'); clock[0]=700.0
    result['clock_rollback']={'decision':d.attempt('A','P','synthetic',work_bound=.01,
                                                review_bound=0).decision}
brief={'objective':'synthetic','acceptance':{'checks':[{'command':'python fake.py','expect':'exit 0'}]},
       'sources':[],'permitted-effects':[],'non-goals':[], 'isolation':'worktree+branch',
       'branch-hint':'sr/a1b2c3d4/test', 'allowance':{'cash':float('nan'),'calls':1,
       'deadline':'2030-01-01T00:05:00Z'}, 'attempts':1,'stop-triggers':[],
       'ownership':'worker','nested-allowed':False,'max-nesting-depth':0}
for name,obj,check in [('nan_brief',brief,cs.check_brief),
    ('invalid_speculative_set',{'candidates':[{'profile':'P'}], 'max-parallel':0,
     'shared-budget':{'cash':.1,'calls':1},'cancel-policy':'first-success','winner-owns':True},
     cs.check_speculative)]:
    try: check(obj); result[name]={'accepted':True}
    except (cs.Violation,cs.FailClosed): result[name]={'accepted':False}
print(json.dumps(result,indent=2))
