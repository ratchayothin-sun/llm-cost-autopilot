import json
import sqlite3

import pytest

from eval import replay

DATASET = [
    {"id": "a", "category": "math", "prompt": "1+1? End your reply with the final number.",
     "check": {"type": "number", "value": 2}},
    {"id": "b", "category": "knowledge", "prompt": "ใครเขียนพระอภัยมณี ตอบสั้นๆ",
     "check": {"type": "contains_any", "values": ["สุนทรภู่"]}},
    {"id": "c", "category": "math", "split": "test", "prompt": "2+2? End your reply with the final number.",
     "check": {"type": "number", "value": 4}},
    {"id": "d", "category": "math", "prompt": "3+3? End your reply with the final number.",
     "check": {"type": "number", "value": 6}},
]
# item -> tier -> (output, correct, cost, latency)
RESULTS = {
    "a": {"small": ("2", 1, 1.0, 10.0), "medium": ("2", 1, 3.0, 1.0), "large": ("2", 1, 10.0, 1.0)},
    "b": {"small": ("พระเจ้าบุเรงนอง", 0, 1.0, 10.0), "medium": ("สุนทรภู่ครับ", 1, 3.0, 1.0),
          "large": ("สุนทรภู่", 1, 10.0, 1.0)},
    "c": {"small": ("5", 0, 1.0, 10.0), "medium": ("4", 1, 3.0, 1.0), "large": ("4", 1, 10.0, 1.0)},
}


@pytest.fixture
def files(tmp_path):
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("\n".join(json.dumps(i, ensure_ascii=False) for i in DATASET), encoding="utf-8")
    db = tmp_path / "results.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE results (item_id TEXT, tier TEXT, category TEXT, model TEXT, "
                "output TEXT, correct INTEGER, cost REAL, latency REAL, error TEXT, PRIMARY KEY (item_id, tier))")
    for iid, tiers in RESULTS.items():
        for tier, (out, ok, cost, lat) in tiers.items():
            con.execute("INSERT INTO results VALUES (?,?,?,?,?,?,?,?,?)",
                        (iid, tier, "x", "m", out, ok, cost, lat, None))
    # item d: large errored, small and medium fine -> must be left out
    con.execute("INSERT INTO results VALUES ('d','small','x','m','6',1,1,1,NULL)")
    con.execute("INSERT INTO results VALUES ('d','medium','x','m','6',1,1,1,NULL)")
    con.execute("INSERT INTO results VALUES ('d','large','x','m','',NULL,0,0,'rate limit')")
    con.commit()
    con.close()
    return db, dataset


def test_load_results_filters_split_and_incomplete_items(files):
    db, dataset = files
    ds = replay.load_dataset(dataset)
    dev, skipped = replay.load_results(db, ds, "dev")
    assert sorted(dev) == ["a", "b"] and skipped == ["d"]
    test, _ = replay.load_results(db, ds, "test")
    assert sorted(test) == ["c"]


def test_always_policies_and_costs(files):
    db, dataset = files
    items, _ = replay.load_results(db, replay.load_dataset(dataset), "dev")
    small = replay.evaluate(replay.always("small"), items)
    assert sum(v[1] for v in small.values()) == 1                  # right on a, wrong on b
    assert sum(v[2] for v in small.values()) == pytest.approx(2.0)


def test_oracle_pays_for_failed_attempts(files):
    db, dataset = files
    items, _ = replay.load_results(db, replay.load_dataset(dataset), "dev")
    res = replay.evaluate(replay.oracle(replay.TIERS), items)
    assert res["a"][:3] == ("small", 1, 1.0)
    assert res["b"][0] == "medium" and res["b"][2] == pytest.approx(1.0 + 3.0)   # small failed, then medium
    assert res["b"][3] == pytest.approx(11.0)                                    # latencies add up


def test_omniscient_router_pays_only_for_the_right_tier(files):
    db, dataset = files
    items, _ = replay.load_results(db, replay.load_dataset(dataset), "dev")
    res = replay.evaluate(replay.omniscient_router, items)
    assert res["b"][:3] == ("medium", 1, 3.0)


def test_gateway_policy_matches_the_gateway_definition(files):
    db, dataset = files
    items, _ = replay.load_results(db, replay.load_dataset(dataset), "dev")
    router = replay.gateway_policy(replay.POLICIES["router"], lambda item: item["category"])
    res = replay.evaluate(router, items)
    assert res["b"][0] == "large"                  # knowledge goes straight to large
    assert res["a"][0] == "medium"                 # math starts at medium


def test_agreement_policy(files):
    db, dataset = files
    items, _ = replay.load_results(db, replay.load_dataset(dataset), "dev")
    res = replay.evaluate(replay.agreement, items)
    assert res["a"][:3] == ("medium", 1, 4.0)      # "2" == "2": keep medium
    assert res["b"][0] == "large"                  # different answers: ask large too
    assert res["b"][2] == pytest.approx(14.0)
    assert res["b"][3] == pytest.approx(11.0)      # small and medium run in parallel


def test_statistics():
    lo, hi = replay.wilson(0, 0)
    assert (lo, hi) == (0.0, 0.0)
    lo, hi = replay.wilson(69, 75)
    assert 0.83 < lo < 0.85 and 0.95 < hi < 0.97
    assert replay.sign_test_p(0, 0) == 1.0
    assert replay.sign_test_p(5, 0) == pytest.approx(0.0625)
    assert replay.sign_test_p(10, 10) == 1.0


def test_main_prints_a_report(files, capsys):
    db, dataset = files
    code = replay.main(["--db", str(db), "--dataset", str(dataset)])
    out = capsys.readouterr().out
    assert code == 0
    assert "split=dev: 2 items" in out
    assert "always medium" in out and "CEILING omniscient router" in out


def test_main_reports_when_nothing_can_be_replayed(files, capsys):
    db, dataset = files
    sqlite3.connect(db).execute("DELETE FROM results").connection.commit()
    assert replay.main(["--db", str(db), "--dataset", str(dataset)]) == 1
