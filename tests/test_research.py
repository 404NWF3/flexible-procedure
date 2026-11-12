import unittest
from dataclasses import fields

from soft_procedure import SimulationConfig, run_simulation
from soft_procedure.research import Design, DecisionView, JobView, OnlinePolicy, ResearchSimulation


class ResearchTests(unittest.TestCase):
    def test_original_engine_compatibility(self):
        for rule,original in (("fifo","fifo"),("family","same_family")):
            c=SimulationConfig(sample_interval=2400,policy_name=original)
            a=run_simulation(c,42)
            b=ResearchSimulation(Design("compat",rule=rule,admission="fifo"),42,config=c).run()
            for old,new in (("completed","completed"),("external","external"),("operating_cost","operating_cost"),("sales_revenue","revenue"),("mean_cycle_time","mean_cycle_time")):
                self.assertAlmostEqual(a["summary"][old],b["summary"][new],places=7)
            self.assertEqual({p:v["completed"] for p,v in a["products"].items()}, {p:v["completed"] for p,v in b["products"].items()})
            for x,y in zip(a["stations"],b["stations"]):
                self.assertAlmostEqual(x["mean_queue"],y["mean_queue"],places=7)
                for state in x["states"]:
                    self.assertAlmostEqual(x["states"][state],y["states"][state],places=7)

    def test_frozen_policy_observations_exclude_hidden_state(self):
        self.assertEqual({f.name for f in fields(DecisionView)}, {"now","remaining","station","last_product","completed","arrived"})
        self.assertEqual({f.name for f in fields(JobView)}, {"id","product","request","internal","queue_entered","wait","remaining_mean","current_mean","price"})
        policy=OnlinePolicy(Design("causal",rule="hybrid",admission="value",fairness=10))
        self.assertEqual(set(vars(policy)),{"design"})
        o=DecisionView(100,1000,"M2","P3",(1,2,3,4),(30,25,25,20))
        j=JobView(8,"P1",2,True,90,10,21,8,200)
        before=policy.rank(j,o,admission=False)
        # Different future realizations have no representation in the input.
        self.assertEqual(before,policy.rank(j,o,admission=False))
        with self.assertRaises((AttributeError,TypeError)):
            o.seed=42

    def test_capital_ledgers_and_dynamic_activation(self):
        d=Design("cap",regime="upfront",counts=(3,1,2,1,2))
        r=ResearchSimulation(d,42,horizon=2400).run()
        self.assertEqual(r["summary"]["capex"],500000)
        self.assertAlmostEqual(r["summary"]["capital_allocated"],500000)
        self.assertAlmostEqual(r["summary"]["net"],r["summary"]["revenue"]-r["summary"]["operating_cost"]-500000)
        dynamic=Design("dyn",regime="dynamic",counts=(3,2,3,2,3),review_minutes=1200,buy_threshold=0)
        r=ResearchSimulation(dynamic,42,horizon=4800,project_horizon=1_200_000).run()
        self.assertTrue(r["purchases"])
        self.assertTrue(all(p["time"]>=1200 for p in r["purchases"]))
        self.assertGreater(r["summary"]["capital_unallocated"],0)
        self.assertTrue(r["checks"]["state_time"])

    def test_future_failure_information_does_not_change_decisions(self):
        traces=[]
        results=[]
        for future_life in (10000,20000):
            sim=ResearchSimulation(Design('causal_trace',rule='hybrid',admission='value'),42,horizon=600,project_horizon=1200000)
            for machine in sim.machines:
                machine.life=future_life
            trace=[]
            original_rank=sim.policy.rank
            def rank(job,observation,*,admission):
                decision=original_rank(job,observation,admission=admission)
                trace.append((job,observation,admission,decision))
                return decision
            sim.policy.rank=rank
            results.append(sim.run()['summary'])
            traces.append(trace)
        self.assertTrue(traces[0])
        self.assertEqual(traces[0],traces[1])
        self.assertEqual(results[0],results[1])


if __name__=="__main__":
    unittest.main()
