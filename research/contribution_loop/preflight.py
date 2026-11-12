import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from adapter import Policy, ControlledSimulation
from evaluator import run_one, audit, ROOT, OUT, atomic_json
from soft_procedure.config import SimulationConfig
from soft_procedure.model.source import Arrival


class BoundaryTests(unittest.TestCase):
    def policy(self, code):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        path=Path(folder.name)/'candidate.py';path.write_text(code)
        p=Policy(path);self.addCleanup(p.close)
        return p

    def test_forbidden_io(self):
        p=self.policy('''import os, socket\ndef decide(o):\n    for fn in [lambda:open('/etc/hostname'),lambda:open('/tmp/loop-escape','w'),lambda:os.fork(),lambda:socket.socket(),lambda:open('/proc/self/environ')]:\n        try: fn()\n        except PermissionError: pass\n        else: raise AssertionError('boundary failure')\n    return {'job':o['jobs'][0]['id']}\n''')
        self.assertEqual(p.decide({'jobs':[{'id':1}]}),{'job':1})

    def test_illegal_membership(self):
        p=self.policy('def decide(o): return {"job":999}')
        with self.assertRaises(ValueError):p.decide({'jobs':[{'id':1}]})

    def test_invalid_waits(self):
        for v in [0,-1,16]:
            p=self.policy('def decide(o): return {"wait":'+str(v)+'}')
            with self.assertRaises(ValueError):p.decide({'jobs':[{'id':1}]})

    def test_unfinished_cost_and_terminal(self):
        path=OUT/'evaluator/references/fifo.py';p=Policy(path);self.addCleanup(p.close)
        sim=ControlledSimulation(SimulationConfig(horizon=2,failures_enabled=False,processing_cv=0),42,p,[Arrival(1,1,('P1',))])
        r=sim.run();m=audit(r)
        self.assertEqual(m['completed'],0)
        self.assertAlmostEqual(m['operating_contribution'],-100/60)

    def test_capped_release_keeps_external_arrivals(self):
        template=(Path(__file__).parent/'policy_template.py').read_text()
        p=self.policy(template.replace('P = {}',"P = {'dispatch':'family','admission':'internal','cap':2}",1))
        sim=ControlledSimulation(SimulationConfig(horizon=100,failures_enabled=False,processing_cv=0),42,p,[Arrival(1,1,('P1','P2','P3','P4')*3)])
        r=sim.run();m=audit(r)
        self.assertEqual(r['summary']['arrived'],12)
        self.assertTrue(all(s['wip']<=2 for s in r['samples']))
        self.assertEqual(sim.tokens,m['wip'])

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(BoundaryTests))
    atomic_json(OUT/'evaluator/boundary_tests.json',{'passed':result.wasSuccessful(),'tests':result.testsRun,'errors':len(result.errors),'failures':len(result.failures)})
    raise SystemExit(0 if result.wasSuccessful() else 1)
