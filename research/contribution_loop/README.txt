Contribution loop · campaign 01

This research harness leaves src/soft_procedure and its lockfile unchanged.
Recovered source contract: outputs/contribution_loop_20261022/loop_contract.json
Recovered search instructions: outputs/contribution_loop_20261022/agent_prompt.txt

Model: 2400 minutes, empty start, original arrivals, machines, routes, failures,
prices and 100 CNY / active machine hour. Objective is mean operating contribution.
Every candidate executes in a fresh Python 3.13 process with a libseccomp syscall
allowlist. File access, networking, exec/fork, process memory and signalling are
blocked before its source executes. Only JSON public observations and validated
actions cross stdin/stdout. Evaluator uses Python 3.12, original SimPy 4.1.2 and
SciPy 1.17.0 for arbitrary Student-t quantiles. No third-party source installation.

Implemented interface: choose an eligible waiting job for the first idle machine,
rank pending admission requests, or defer with a trusted timer (0 < delay <= 15).
A request remains on its upstream machine until accepted. External jobs continue
arriving. A shared counter audits global in-line WIP. Opaque handles are stable
job IDs; no source schedule, seed, phase, lifetime or future work duration is sent.
Joint machine matching and learned policies were not exercised in this campaign.

Start (only once per new, authorized campaign):
  PYTHONPATH=src:.venv/lib/python3.12/site-packages python research/contribution_loop/prepare.py
  PYTHONPATH=src:.venv/lib/python3.12/site-packages python research/contribution_loop/preflight.py
  PYTHONPATH=src:.venv/lib/python3.12/site-packages python research/contribution_loop/runner.py init

Continue the registered, unsealed campaign with a batch JSON:
  PYTHONPATH=src:.venv/lib/python3.12/site-packages python research/contribution_loop/runner.py batch search_workspace/notes/batch-02.json

The following seals the top 3 development candidates once, evaluates 50 held-out
paths alongside both references, selects by validation mean (ties favor references),
then confirms the winner and references on 100 fresh paths with no intervening
feedback. It terminates the campaign and will refuse an automatic second attempt:
  PYTHONPATH=src:.venv/lib/python3.12/site-packages python research/contribution_loop/runner.py seal

No automatic resume after interruption: preserve all receipts and inspect the
failure first. An infrastructure replay must use the exact same source and seed,
be audited, and retain the failed attempt. Never delete a candidate failure or
regenerate a hidden bank. A new campaign requires new authorization and the next
alpha allocation; init refuses this campaign's existing state.

Records:
  evaluator/ready_receipt.json       preflight gates and frozen source digest
  evaluator/ledger/events.jsonl      append-only hash chained events
  evaluator/receipts/*.json          per-candidate stage receipts, including failures
  evaluator/raw/**/*.json.gz         all jobs and machine-state trajectories
  evaluator/private/seeds.json       committed private banks, never passed to policies
  evaluator/alpha_ledger.json        fixed research-line significance accounting
  state.json                        reconstructable experiment tree and statistics

Site: native static HTML/JS, no CDN or third-party assets. It polls progress.json
for published snapshots every 15 seconds. Source is pushed and deployed at
milestones; it does not execute simulations in the browser. Publication permission
covers HTML/CSS/JS, experiment summaries and contract files only; raw trajectories
and hidden seed banks remain local. The official Sites/Data build helpers were not
installed in the selected image, so this operational tracker uses a portable
static renderer and an explicit allowlisted Git/archive publication path.
