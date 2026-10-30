import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments import SERIES,jobs,CORRECTED_HOLDOUT,REFERENCE_RUNS,HOLDOUT_KEYS,CONFIGS_BY_KEY
from src.agent import Agent
from src.tools import check_value,to_ollama,ALL_SPECS
from analyze import calculate,read,sign_test
from export_materials import initial_request
import run

class ReproductionTests(unittest.TestCase):
    def test_schedule_matches_records(self):
        for name,count in [('main',720),('q8',108),('ablation',324),('holdout',120),('general_df',72),('extra_seed',108)]:
            with self.subTest(series=name):
                schedule={(t.id,c.key,rep,seed) for t,c,rep,seed in jobs(name)}
                rows=read(ROOT/'results'/f'{name}.jsonl')
                actual={(r['task'],r['config'],r['rep'],r['seed']) for r in rows}
                self.assertEqual(len(rows),count)
                self.assertEqual(len(actual),count)
                self.assertEqual(schedule,actual)

    def test_reference_traces(self):
        for task in CORRECTED_HOLDOUT:
            with self.subTest(task=task.id):
                actor=Agent(task,CONFIGS_BY_KEY['base'],None,0)
                calls,answer=REFERENCE_RUNS[task.id]
                for step,(name,args) in enumerate(calls,1):
                    args={k:actor.ctx.created_ids[-1] if v=='$created' else v for k,v in args.items()}
                    actor.iterations=step;actor.handle_call(name,args)
                self.assertFalse(check_value(task.answer_schema,answer,'answer'))
                self.assertTrue(task.answer_ok(answer,actor.ctx))
                self.assertTrue(task.state_ok(actor.is_.tickets,actor.ctx))
                self.assertFalse(task.answer_ok({},actor.ctx))
                actor.is_.tickets['REQ-101']['priority']='низкий'
                self.assertFalse(task.state_ok(actor.is_.tickets,actor.ctx))

    def test_h05_correction(self):
        task=next(t for t in CORRECTED_HOLDOUT if t.id=='H05')
        for key in HOLDOUT_KEYS:
            actor=Agent(task,CONFIGS_BY_KEY[key],None,20004)
            for step,(name,args) in enumerate(REFERENCE_RUNS['H05'][0],1):
                args={k:actor.ctx.created_ids[-1] if v=='$created' else v for k,v in args.items()}
                actor.iterations=step;actor.handle_call(name,args)
            self.assertTrue(task.state_ok(actor.is_.tickets,actor.ctx))
            self.assertFalse(actor.events)

    def test_holdout_correction_records(self):
        fixed=[r for r in read(ROOT/'results/holdout.jsonl') if r['task']=='H05']
        self.assertEqual(len(fixed),10)
        self.assertTrue(all(r.get('etalon_correction') is True for r in fixed))
        self.assertEqual({(r['config'],r['rep']) for r in fixed},
                         {(key,rep) for key in HOLDOUT_KEYS for rep in range(2)})

    def test_paper_values(self):
        r=calculate(ROOT/'results')
        self.assertEqual(r['main']['base']['successful'],34)
        self.assertEqual(r['main']['combined2']['successful'],70)
        self.assertEqual(r['main']['combined2']['prevented'],38)
        self.assertEqual([r['holdout'][k]['successful'] for k in HOLDOUT_KEYS],[15,18,21,21,22])
        self.assertEqual(r['general_df']['det_general']['successful'],50)
        self.assertEqual(r['five_seeds']['successful'],86)
        self.assertEqual(len(r['five_seeds']['stable_tasks']),33)
        self.assertEqual(r['comparisons']['holdout_vs_base']['det_rules_mon2']['p'],0.25)
        self.assertEqual(r['comparisons']['general_vs_full_df']['p'],0.625)

    def test_exact_exports(self):
        from experiments import TASKS
        item=json.loads((ROOT/'prompts/initial_request_example.json').read_text(encoding='utf-8'))
        cfg=CONFIGS_BY_KEY[item['config']]
        task=next(t for t in TASKS if t.id==item['task'])
        self.assertEqual({k:v for k,v in item.items() if k not in ('config','task')},initial_request(task,cfg))
        self.assertEqual(json.loads((ROOT/'docs/tool_schemas.json').read_text(encoding='utf-8')),to_ollama(list(ALL_SPECS)))

    def test_sign_test_ties(self):
        rows=[{'task':'x','success':True}]
        self.assertEqual(sign_test(rows,rows),dict(better=0,worse=0,ties=1,p=1.0))

    def test_runner_resume_and_identity(self):
        class FakeLLM:
            options={'temperature':0.7};think=False
            def __init__(self,model):pass
            def chat(self,*a,**k):return {},{}
        class FakeAgent:
            def __init__(self,*a):pass
            def run(self):return {'success':True}
        digest=['first']
        def api(path,body=None):
            if path=='tags':return {'models':[{'name':'qwen3:14b','digest':digest[0],'details':{'quantization_level':'Q4_K_M'}}]}
            return {}
        with tempfile.TemporaryDirectory() as temp:
            argv=['run.py','--tasks','T1','--configs','base','--out',temp]
            with patch.object(sys,'argv',argv),patch.object(run,'api',api),patch.object(run,'LLM',FakeLLM),patch.object(run,'Agent',FakeAgent),contextlib.redirect_stdout(io.StringIO()):
                run.main();run.main()
                self.assertEqual(len(read(Path(temp)/'main/results.jsonl')),2)
                digest[0]='second'
                with self.assertRaises(ValueError):run.main()

if __name__=='__main__':unittest.main()
