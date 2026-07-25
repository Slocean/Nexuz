from backend.core.registry import register_all_blocks

register_all_blocks()
from backend.core.ai.eval_runner import run_eval_suite

r = run_eval_suite()
print(r["passed"], r["total"], round(r["pass_rate"], 3))
for x in r["results"]:
    if not x["ok"]:
        print("FAIL", x["id"], x["errors"], "types=", x["types"])
