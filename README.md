### Gateway demo

A smoke test of the whole path (HTTP request, routing policy, model call, verifier, SQLite log).
Eight prompts say nothing about accuracy; this only shows which tier each request was sent to.

```powershell
$env:AUTOPILOT_POLICY = "router"
uvicorn app.main:app          # terminal 1
python -m eval.demo_gateway   # terminal 2
```

```
task_type   tier used esc       cost   secs  answer
knowledge   large       0   0.000077    1.0  แม่น้ำเจ้าพระยา.
knowledge   large       0   0.000042    0.6  Leonardo da Vinci.
math        medium      0   0.000025    0.6  ANSWER: 540
math        medium      0   0.000016    0.4  60
reasoning   medium      0   0.000035    1.2  ANSWER: Tuesday
extraction  small       0   0.000004   25.3  {"name": "Mali", "city": "Phuket"}
-           medium      0   0.000033    0.7  การออมเงินเป็นประจำช่วยสร้างนิสัยการใช้จ่ายที่มีสติและลดความ
-           medium      0   0.000011    0.3  Ottawa.
total                   0   0.000243
```

- Knowledge questions went straight to the large model, math and reasoning to the medium model,
  and a request without a `task_type` took the default route (medium, then large).
- Costs are simulated from reference prices, not money spent.
- The extraction request ran on the small model locally on a CPU and took 25 s, against about 1 s
  for the hosted tiers. Routing extraction to the small tier saves roughly 0.00001 to 0.00003 of
  simulated cost per request on this data, so it only makes sense where that latency is acceptable or the
  small model is hosted somewhere faster. Medium and small scored the same on the extraction items
  (16 of 17), so this route was chosen for cost, not accuracy.
- Every attempt is stored in `autopilot.db` (tables `requests` and `attempts`), for example:

```powershell
python -c "import sqlite3; c=sqlite3.connect('autopilot.db'); [print(r) for r in c.execute('SELECT id, task_type, final_tier, total_cost, escalations FROM requests ORDER BY id DESC LIMIT 8')]"
```
