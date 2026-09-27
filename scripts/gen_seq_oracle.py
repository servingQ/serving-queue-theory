#!/usr/bin/env python3
"""Generate lean/ServingQueueTheory/SeqOracle.lean from the IR of the vLLM
scheduler scenarios in the pinned seQ release (.seq/src/tools/oracle/
<name>.ir.json: programs/vllm_request.seq compiled with the scenario's
engine, the requests as explicit sessions; checked out by
scripts/fetch_seq.sh; SEQ_SRC overrides the checkout) and the real
scheduler's answers (<name>.out.json).

The program `vllmRequest`, every scenario's deployment and its request
table are translated from the IR, not written by hand: the Lean theorems
are about the same IR the seQ tests run. The translation accepts the
fragment of the IR the executable semantics (SeqExec.lean) covers and
fails on anything else. One theorem per scenario: the executable semantics
gives the same first-token step, last-token step and preemption count for
every request as the real scheduler. `--check` fails if the committed file
is stale. The multi-turn cache scenario (`vllmTurn`) is still written
here by hand: its turns read a trace, which the Lean fragment lacks."""
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
SEQ_SRC = os.environ.get("SEQ_SRC", os.path.join(ROOT, ".seq", "src"))
ODIR = os.path.join(SEQ_SRC, "tools", "oracle")
OUT = os.path.join(ROOT, "lean", "ServingQueueTheory", "SeqOracle.lean")

class Fragment(Exception):
    """An IR construct outside the Lean executable fragment."""


def nat(v, what):
    if not (isinstance(v, (int, float)) and v >= 0 and float(v).is_integer()):
        raise Fragment(f"{what}: {v} is not a natural number")
    return int(v)


def one_ref(r, what):
    if r["count"] != 1 or r["index"] is not None:
        raise Fragment(f"{what}: families of pools/stages are outside the fragment")
    return r["base"]


class Lean:
    """IR (a seQ program as JSON) to the Lean surface syntax `[route| … ]`
    of `Route Exec.Env ℕ`. `attr_ix` maps IR attribute slots to Lean
    attribute indices (the columns of the scenario's request table)."""

    def __init__(self, ir, attr_ix):
        self.ir = ir
        self.attr_ix = attr_ix
        self.builtin = {ir["slot_cached"]: "x.cached", ir["slot_serial"]: "x.serial"}

    def arg(self, a):
        if "Expr" not in a:
            raise Fragment(f"argument {a}")
        return self.expr(a["Expr"])

    def expr(self, e):
        if "Num" in e:
            return str(nat(e["Num"], "constant"))
        if "Attr" in e:
            k = e["Attr"]
            if k in self.builtin:
                return self.builtin[k]
            if k not in self.attr_ix:
                raise Fragment(f"attribute `{self.ir['attrs'][k]}` is not in the request table")
            return f"(x.attr {self.attr_ix[k]})"
        if "Ctx" in e:
            if e["Ctx"] == "Now":
                return "x.now"
            raise Fragment(f"context variable {e['Ctx']}")
        if "Call" in e:
            f, args = e["Call"]
            if f in ("Min", "Max") and len(args) == 2:
                return f"({f.lower()} {self.arg(args[0])} {self.arg(args[1])})"
            if f == "BudgetLeft" and len(args) == 1 and "Stage" in args[0]:
                if one_ref(args[0]["Stage"], "budget_left") != 0:
                    raise Fragment("budget_left of a stage other than the engine")
                return "x.budgetLeft"
            if f == "CachedIn" and len(args) == 1 and "Pool" in args[0]:
                return f"(x.cachedIn {one_ref(args[0]['Pool'], 'cachedin')})"
            if f == "Floor" and len(args) == 1 and "Binary" in args[0].get("Expr", {}):
                op, a, b = args[0]["Expr"]["Binary"]
                if op == "Div":
                    return f"({self.expr(a)} / {self.expr(b)})"
            raise Fragment(f"call {f}")
        if "Binary" in e:
            op, a, b = e["Binary"]
            sym = {"Add": "+", "Sub": "-", "Mul": "*"}.get(op)
            if sym is None:
                raise Fragment(f"operator {op}")
            return f"({self.expr(a)} {sym} {self.expr(b)})"
        raise Fragment(f"expression {e}")

    def top(self, e):
        """An expression in statement position: drop one pair of outer parentheses."""
        t = self.expr(e)
        return t[1:-1] if t.startswith("(") and t.endswith(")") else t

    def block(self, b, ind):
        pad = "  " * ind
        out = []
        for st in self.ir["blocks"][b]:
            if st == "End":
                out.append(pad + "stop")
                return "\n".join(out)
            if st == "Turn":
                out.append(pad + "turn;")
                continue
            (kind, v), = st.items()
            if kind == "Set":
                slot, e = v
                if slot not in self.attr_ix:
                    raise Fragment(f"set of `{self.ir['attrs'][slot]}`")
                out.append(f"{pad}set {self.attr_ix[slot]} = {self.top(e)};")
            elif kind == "Observe":
                k, e = v
                out.append(f"{pad}observe {k} = {self.top(e)};")
            elif kind == "Run":
                s = one_ref(v["stage"], "run")
                mode = {"Plain": "", "Prefill": " prefill", "Decode": " decode"}[v["mode"]]
                g = f" growing {one_ref(v['growing'], 'growing')}" if v["growing"] else ""
                if not mode and g:
                    raise Fragment("plain run growing a pool")
                out.append(f"{pad}run {s}{mode} ({self.top(v['work'])}){g};")
            elif kind == "Hold":
                ps = []
                for r, u, fits in v["pools"]:
                    f = f" fits ({self.top(fits)})" if fits is not None else ""
                    ps.append(f"{one_ref(r, 'hold')} ({self.top(u)}){f}")
                ru = f" reuse ({self.top(v['reuse'])})" if v["reuse"] is not None else ""
                ca = f" cache ({self.top(v['cache'])})" if v["cache"] is not None else ""
                out.append(f"{pad}hold {', '.join(ps)}{ru} {{")
                out.append(self.block(v["body"], ind + 1))
                out.append(f"{pad}}}{ca};")
            elif kind == "Branch":
                c, t, f = v
                out.append(f"{pad}branch ({self.top(c)}) {{")
                out.append(self.block(t, ind + 1))
                out.append(f"{pad}}} else {{")
                out.append(self.block(f, ind + 1))
                out.append(f"{pad}}};")
            elif kind == "Loop":
                out.append(f"{pad}loop {{")
                out.append(self.block(v, ind + 1))
                out.append(f"{pad}}}")
                return "\n".join(out)
            else:
                raise Fragment(f"statement {kind}")
        out.append(pad + "done")
        return "\n".join(out)

    def deployment(self):
        ir = self.ir
        st = ir["stages"]
        if len(st) != 2 or "Step" not in st[0]["kind"] or st[1]["kind"] != "Delay":
            raise Fragment("stages must be one step engine (0) and one delay (1)")
        step = st[0]["kind"]["Step"]
        if step["cost"] != {"Num": 1.0}:
            raise Fragment("the engine's iteration cost must be 1 (the step clock)")
        if step["exclusive_prefill"] or step["decode_first"]:
            raise Fragment("exclusive prefill / decode first")
        pools = []
        for i, p in enumerate(ir["pools"]):
            if p["evict"] != "Lru" or p["queue"] is not None or p["spill"] is not None:
                raise Fragment(f"pool {p['name']}: only LRU eviction, FIFO queue, no spill")
            via = p["admit_via"] is not None
            if via and p["admit_via"] != 0:
                raise Fragment(f"pool {p['name']}: admitted by a stage other than the engine")
            if p["preempt"] != ("None" if via else "Lifo"):
                raise Fragment(f"pool {p['name']}: preemption {p['preempt']}")
            if not via and step["memory"] != i:
                raise Fragment(f"pool {p['name']}: not the engine's memory")
            pools.append(f"⟨{nat(p['cap'], 'cap')}, {nat(p['block'] or 1, 'block')}, {'true' if via else 'false'}⟩")
        return (f"⟨[{', '.join(pools)}], {nat(step['budget'].get('Num'), 'budget')}, "
                f"{nat(step['chunk'].get('Num'), 'chunk')}⟩")


def load_ir(name):
    ir = json.load(open(os.path.join(ODIR, name + ".ir.json")))
    if ir["version"] != 1:
        raise Fragment(f"{name}: IR version {ir['version']}")
    ss = ir["arrival"].get("Sessions") if isinstance(ir["arrival"], dict) else None
    if not ss:
        raise Fragment(f"{name}: the scenario's requests must be explicit sessions")
    cols = [slot for slot, _ in ss[0]["attrs"]]
    if any([slot for slot, _ in s["attrs"]] != cols for s in ss):
        raise Fragment(f"{name}: sessions preset different attributes")
    # `init` must be entirely overridden by the presets (Lean has no `init`)
    for st in ir["blocks"][ir["init"]]:
        if "Set" not in st or st["Set"][0] not in cols:
            raise Fragment(f"{name}: `init` does more than the presets override")
    if ir["blocks"][ir["turn"]]:
        raise Fragment(f"{name}: a `turn` block is outside the fragment")
    lean = Lean(ir, {slot: i for i, slot in enumerate(cols)})
    table = [tuple(nat(v, "request attribute") for _, v in s["attrs"]) for s in ss]
    names = [ir["attrs"][slot] for slot in cols]
    return ir, lean, table, names


def request_program(scenarios):
    """`vllmRequest` from the IR: the route of every scenario must be the
    same program (only the engine's constants and the requests differ)."""
    progs = {}
    for name in scenarios:
        ir, lean, _, names = load_ir(name)
        progs[name] = (lean.block(ir["route"], 1), names, ir["observes"], [p["name"] for p in ir["pools"]],
                       [s["name"] for s in ir["stages"]])
    first = next(iter(progs.values()))
    for name, p in progs.items():
        if p != first:
            raise Fragment(f"{name}: its route differs from the other scenarios'")
    body, names, obs, pools, stages = first
    attrs = ", ".join(f"{i} = {n}" for i, n in enumerate(names))
    observes = ", ".join(f"{i} = {n}" for i, n in enumerate(obs))
    return f"""/-- The vLLM request program, translated from the IR of the oracle
scenarios (seQ `programs/vllm_request.seq`, `tools/oracle/*.ir.json`).
Attributes: {attrs}. Observations: {observes}. Pools: {", ".join(f"{i} = {n}" for i, n in enumerate(pools))}.
Stages: {", ".join(f"{i} = {n}" for i, n in enumerate(stages))}. -/
def vllmRequest : Prog := [route|
{body}]

theorem vllmRequest_wf : vllmRequest.wf = true := by decide
"""


HEAD = '''/-
# vLLM scheduler scenarios as theorems about seQ programs

Generated by `scripts/gen_seq_oracle.py` from the IR of seQ's oracle
scenarios (`tools/oracle/*.ir.json`: `programs/vllm_request.seq` compiled
with each scenario's engine, the requests as explicit sessions) and
`*.out.json` (what the real vLLM v1 scheduler does: seQ
`tools/vllm_oracle.py`, upstream `ref/vllm` at 0c87a197). Do not edit.
The program, the deployments and the request tables below are
translations of that IR, the same IR the seQ tests run.

Each scenario is a deployment (a request-slot pool served by the engine, a
KV pool of blocks, the engine's budget and chunk cap) and a set of requests
(prompt, output tokens, arrival step). Every request runs the same seQ
program, `vllmRequest`: wait until its arrival, hold a slot and the KV
blocks of the chunk the engine's budget leaves (admission needs room for
the whole prompt), prefill growing the hold, decode growing it. The
theorems say that the executable semantics gives, for every request, the
step of its first token and of its last token, and the number of
preemptions, that the real scheduler gives. They are checked by evaluation
in the kernel (`decide +kernel`: no axiom beyond the standard three).
-/
import ServingQueueTheory.SeqExec

set_option maxRecDepth 100000

namespace ServingQueueTheory
namespace SeqLang
namespace Oracle

open Exec

{REQUEST}
/-- A vLLM engine: `max_num_seqs` slots, `num_blocks` blocks of `bs` tokens
(one is the null block), `max_num_batched_tokens`, chunk cap. -/
def engine (maxSeqs blocks bs budget chunk : ℕ) : Deployment :=
  ⟨[⟨maxSeqs, 1, true⟩, ⟨(blocks - 1) * bs, bs, false⟩], budget, chunk⟩

/-- Request attributes from a table of (prompt, out, arrive). -/
def reqs (t : List (ℕ × ℕ × ℕ)) (i slot : ℕ) : ℕ :=
  match t[i]?, slot with
  | some (p, _, _), 0 => p
  | some (_, o, _), 1 => o
  | some (_, _, a), 2 => a
  | _, _ => 0

/-- (first-token steps, last-token steps, preemptions). -/
def outcome (D : Deployment) (ticks : ℕ) (t : List (ℕ × ℕ × ℕ)) :
    List (ℕ × ℕ) × List (ℕ × ℕ) × ℕ :=
  let m := Exec.run D ticks t.length (reqs t) vllmRequest
  (observed m 0, observed m 1, m.preempts)
'''


def scenario_names():
    return sorted(f[:-8] for f in os.listdir(ODIR) if f.endswith(".ir.json"))


def gen():
    names = scenario_names()
    out = [HEAD.replace("{REQUEST}", request_program(names))]
    for f in sorted(os.listdir(ODIR)):
        if not f.endswith(".json") or f.endswith(".out.json"):
            continue
        name = f[:-5]
        if not os.path.exists(os.path.join(ODIR, name + ".out.json")):
            continue  # not a scenario (e.g. a100_engine.json)
        sc = json.load(open(os.path.join(ODIR, f)))
        ans = json.load(open(os.path.join(ODIR, name + ".out.json")))
        n = len(sc["requests"])
        first = sorted((int(k), v) for k, v in ans["first"].items())
        done = sorted((int(k), v) for k, v in ans["done"].items())
        ticks = max([v for _, v in done] + [0]) + 5
        if name not in names:
            raise Fragment(f"{name}: no IR file ({name}.ir.json)")
        ir, lean, table, _ = load_ir(name)
        if len(table) != n:
            raise Fragment(f"{name}: {len(table)} sessions in the IR, {n} requests in the scenario")
        dep = lean.deployment()
        tbl = ", ".join("(" + ", ".join(map(str, r)) + ")" for r in table)
        fs = ", ".join(f"({k}, {v})" for k, v in first)
        ds = ", ".join(f"({k}, {v})" for k, v in done)
        out.append(f'''
/-- seQ `tools/oracle/{name}.ir.json`: {n} requests, {sc["num_blocks"]} blocks of {sc["block_size"]}, budget {sc["budget"]}, {sc["max_seqs"]} slots, chunk {sc.get("chunk", 0)}; the deployment and the request table are the IR's. -/
theorem vllm_{name} :
    outcome {dep} {ticks}
      [{tbl}] =
    ([{fs}], [{ds}], {ans["preemptions"]}) := by
  decide +kernel
''')
    out.append(gen_cache())
    out.append("\nend Oracle\nend SeqLang\nend ServingQueueTheory\n")
    return "".join(out)


def gen_cache():
    """The multi-turn prefix-cache scenario: cache_trace.jsonl answered by the
    real scheduler and KV-cache manager on the step clock (cache_trace.out.csv,
    tools/vllm_replay_oracle.py with a unit step cost)."""
    sess = [json.loads(l) for l in open(os.path.join(ODIR, "cache_trace.jsonl")) if l.strip()]
    rows = {}
    for l in open(os.path.join(ODIR, "cache_trace.out.csv")).read().splitlines()[1:]:
        s, k, sent, first, done, prompt, cached, o = l.split(",")
        rows[(int(s), int(k))] = (int(float(first)), int(float(done)), int(cached))
    tbl = "[" + ", ".join("[" + ", ".join(str(q["in"]) for q in x["requests"]) + "]" for x in sess) + "]"
    arr = "[" + ", ".join(str(int(x["arrive"])) for x in sess) + "]"
    keys = sorted(rows)
    first = ", ".join(f"({s}, {rows[(s, k)][0]})" for s, k in keys)
    done = ", ".join(f"({s}, {rows[(s, k)][1]})" for s, k in keys)
    cached = ", ".join(f"({s}, {rows[(s, k)][2]})" for s, k in keys)
    turns = len(sess[0]["requests"])
    return f'''
/-! ### A multi-turn scenario with a prefix cache

seQ `tools/oracle/cache_trace.jsonl`: three sessions of {turns} turns, every
prompt extending the previous one, 3 output tokens, 2 steps of think time,
on 20 blocks of 16 tokens, a budget of 64 and 4 slots. The real vLLM
scheduler's answer (`cache_trace.out.csv`) has hits, a partial hit and
misses caused by eviction. The seQ program is the vLLM engine's rule for
a turn: the scheduler admits (`viaEngine`) with the whole prompt as the
gate and the first chunk allocated; the turn reuses at most the full blocks
of its previous prompt, the rest of its cached entry stays dead; every
computed token is cached; a finished session's cache stays. Attributes:
0 = turn index, 1 = previous prompt. Observations: 0 = first-token step,
1 = last-token step, 2 = cached tokens at admission. -/

def cachePrompts : List (List ℕ) := {tbl}
def cacheArrive : List ℕ := {arr}
def cachePrompt (x : Env) : ℕ := (cachePrompts.getD x.serial []).getD (x.attr 0) 0
def cacheHitMax (x : Env) : ℕ := min (x.attr 1) (cachePrompt x - 1) / 16 * 16

def vllmTurn : Prog := [route|
  run 1 (cacheArrive.getD x.serial 0);
  loop {{
    hold 0 (1), 1 (min (x.cachedIn 1) (cacheHitMax x)
        + min (cachePrompt x - min (x.cachedIn 1) (cacheHitMax x)) x.budgetLeft)
        fits (cachePrompt x) reuse (cacheHitMax x) {{
      run 0 prefill (cachePrompt x - x.cached) growing 1;
      observe 0 = x.now;
      run 0 decode (2) growing 1;
      done
    }} cache (cachePrompt x + 2);
    observe 1 = x.now;
    observe 2 = x.cached;
    set 1 = cachePrompt x;
    set 0 = x.attr 0 + 1;
    branch (if x.attr 0 < {turns} then 1 else 0) {{ run 1 (2); done }} else {{ stop }};
    done
  }}]

theorem vllm_cache_trace :
    let m := Exec.run (engine 4 21 16 64 0) 45 3 (fun _ _ => 0) vllmTurn
    (observed m 0, observed m 1, observed m 2) =
      ([{first}], [{done}], [{cached}]) := by
  decide +kernel
'''



if __name__ == "__main__":
    try:
        txt = gen()
    except Fragment as e:
        print("FAIL: outside the Lean fragment:", e)
        sys.exit(1)
    if "--check" in sys.argv:
        if open(OUT).read() != txt:
            print("STALE: lean/ServingQueueTheory/SeqOracle.lean; run scripts/gen_seq_oracle.py")
            sys.exit(1)
        print("SeqOracle.lean is current")
    else:
        open(OUT, "w").write(txt)
        print("wrote", OUT)
