# Case 22 Arena Student V&V Plan

This document is the executable specification for the short experiments that can run under the Arena Student entity limit. It is intentionally separate from the 2400-minute performance experiments. Student runs are used for structural verification, accounting calibration, and evidence capture only.

## Model preparation gate

Create `Model1_student_vv_base_v1.doe` from the repaired Arena copy. Keep the original and the repaired long-run candidate unchanged.

The validation model must identify the eight physical machines separately:

`M1_1, M1_2, M2_1, M3_1, M3_2, M4_1, M5_1, M5_2`.

For each physical machine, retain its own last-product type, setup counter, setup time, processing time, failure count, repair time, blocked time, and idle time. A single shared `LastProduct` for a capacity-two resource is not acceptable unless the parallel-machine tests prove that the state is per resource unit.

Required entity fields:

- `ProdType`
- `BatchSize`
- `ArrivalTime`
- `SelectedMachine`
- optional fixed validation processing time

Required global outputs:

- arrived item count
- completed item count
- P1/P2/P3/P4 completed counts
- product value
- in-system WIP
- external waiting count
- conservation gap

Required per-machine outputs:

- processing minutes
- setup minutes and setup count
- repair minutes and failure count
- blocked minutes
- idle minutes
- last-product state
- state-time accounting gap

## Acceptance tolerances

- Counts and event counts: exact equality.
- Conservation gap: exactly zero.
- Deterministic time results: absolute error <= 0.01 minutes.
- Monetary results: absolute error <= 0.01 yuan.
- Queue maximum: no greater than configured capacity.
- State-time accounting gap: absolute error <= 0.01 minutes.
- No compile error, deadlock, negative processing time, lost entity, or Student-limit stop.

## Experiment sequence

The experiments are gates. Do not run a later experiment when an earlier structural gate fails.

### S01 - Batch split and item-level type assignment

Settings:

- one batch at time 0
- fixed batch size 20
- split before product typing
- deterministic type sequence: P1=6, P2=5, P3=5, P4=4
- bypass processing and record each item directly
- run length: 1 minute

Expected:

- arrived items: 20
- completed items: 20
- product counts: 6, 5, 5, 4
- conservation: `20 = 20 + 0 + 0`
- no batch-level product count is used as item output

### S02 - Route, counters, and economic calibration

Settings:

- P1 arrival at 0 minutes
- P2 arrival at 50 minutes
- P3 arrival at 100 minutes
- P4 arrival at 150 minutes
- deterministic processing at the task-book means
- setup off
- failures off
- buffer capacity 50
- run length: 200 minutes

Expected route times:

| Product | Route | Processing minutes | Completion time |
|---|---|---:|---:|
| P1 | M1-M2-M3-M4-M5 | 26 | 26 |
| P2 | M1-M3-M4-M5 | 22 | 72 |
| P3 | M2-M3-M5 | 19 | 119 |
| P4 | M1-M4-M5 | 16 | 166 |

Expected accounting:

- total completed: 4
- P1/P2/P3/P4 completed: 1/1/1/1
- total processing time: 83 machine-minutes
- value: 930 yuan
- running cost: `83 / 60 * 100 = 138.33` yuan
- simplified contribution: 791.67 yuan
- conservation gap: 0

### S03 - Serial setup logic

Use one isolated machine. All processing times are 1 minute. Submit five items in this order:

`P1, P1, P2, P2, P1`

Arrival times:

`0, 0.1, 0.2, 0.3, 0.4`

Expected:

- first P1: no setup
- P1 to P1: no setup
- P1 to P2: one 15-minute setup
- P2 to P2: no setup
- P2 to P1: one 15-minute setup
- setup count: 2
- setup time: 30 minutes
- completion times: 1, 2, 18, 19, 35 minutes
- processing plus setup billing time: 35 minutes

### S04 - Parallel-machine setup independence

Use an M1 resource set with two physical members. The intended assignment is:

| Entity | Type | Arrival | Processing | Intended member |
|---|---|---:|---:|---|
| A | P1 | 0 | 5 | M1_1 |
| B | P2 | 0.01 | 10 | M1_2 |
| C | P1 | 5.1 | 20 | M1_1 |
| D | P2 | 10.1 | 1 | M1_2 |
| E | P1 | 11.2 | 1 | M1_2 |

Expected:

- A and B are first jobs and have no setup
- C continues P1 on M1_1 with no setup
- D continues P2 on M1_2 with no setup
- E changes M1_2 from P2 to P1 and has one setup
- total setup count: 1
- total setup time: 15 minutes
- E completion time: 27.2 minutes

Any setup on C or D indicates an incorrectly shared last-product state.

### S05 - Failure resume and independent failure

Use two physical machines. Each job has a deterministic five-minute processing time. M1_1 fails after three minutes and repairs for four minutes. M1_2 has no failure. Setup is off.

Expected:

- M1_2 job completes at approximately 5.01 minutes
- M1_1 job pauses at minute 3, resumes at minute 7, and completes at minute 9
- total processing time: 10 minutes
- repair time: 4 minutes
- failure count: 1
- M1_2 is not delayed by M1_1's failure

### S06 - Finite buffer and blocking

Use a simplified M1-buffer-M2 flow:

- three arrivals at 0, 0.1, and 0.2 minutes
- M1 processing: 1 minute
- M2 processing: 20 minutes
- intermediate buffer capacity: 1
- setup and failures off
- run length: 65 minutes

Expected:

- first item occupies M2 from approximately 1 to 21 minutes
- second item waits in the one-slot buffer
- third item blocks M1 after approximately minute 3
- M1 blocked time: approximately 18 minutes
- maximum buffer length: 1
- completion times: approximately 21, 41, and 61 minutes

The blocked machine must remain seized until downstream capacity becomes available. Blocked time must not be counted as processing time.

### S07 - Conservation, external waiting, and state accounting

Settings:

- 30 items at time 0
- product counts: P1=9, P2=8, P3=7, P4=6
- all buffers temporarily set to capacity 2
- deterministic mean processing times
- setup on
- failures off
- run length: 60 minutes

Expected invariants:

- `30 = completed + in-system WIP + external waiting`
- every queue maximum <= 2
- external waiting is observed
- total completed equals P1+P2+P3+P4 completed
- per-machine processing + setup + blocked + idle time equals the run horizon for each physical member

### S08 - Bounded stochastic smoke run

Restore the real stochastic rules:

- inter-batch time: EXPO(10)
- batch size: DU(5,20)
- split before independent item-level product typing
- processing: Normal(mean, 10% standard deviation), resample nonpositive values
- setup: 15 minutes for a type change, zero for same type, first job free
- MTBF: 6000 minutes
- MTTR: EXPO(240 minutes)
- buffer capacity: 50
- run length: 120 minutes
- no warm-up
- maximum of 7 batches per replication
- five replications with recorded fixed seeds

The maximum generated item count is 140, which remains below the Student limit. Every replication must pass conservation, queue capacity, state-time accounting, nonnegative processing, no-deadlock, and no-entity-loss checks. These results are smoke-test evidence only and must not be reported as a 2400-minute throughput estimate.

## Evidence package

For each scenario, save:

- `.doe` model file
- database or report output
- parameter snapshot
- Arena report
- model/animation screenshots
- expected-versus-actual table
- pass/fail result
- correction note and model version if failed

Suggested names:

`Arena_Student_VV_S01_BatchSplit_v1` through `Arena_Student_VV_S08_Smoke_v1`.

The final V&V table must contain:

`experiment_id, model_version, input_settings, expected_result, actual_result, error, pass, evidence_path, notes`

## Gate order

1. Compile the base model.
2. Pass S01.
3. Pass S02.
4. Pass S03 and S04.
5. Pass S05.
6. Pass S06.
7. Pass S07.
8. Run S08 five times.

When a gate fails, record the actual result, fix the base model, increment its version, and rerun from the earliest affected gate.

Student runs are complete only when S01-S07 pass, all five S08 replications pass, every run stays below 150 entities, and every conclusion is supported by an Arena report or screenshot.
