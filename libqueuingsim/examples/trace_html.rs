//! Timeline of one simulated run as a self-contained HTML page.
//!
//! x is the session (in order of arrival), y is time, running down. Each
//! turn is drawn as its prefill (a rectangle, coloured cold / hit / miss)
//! followed by its decode (a rounded capsule), both labelled with the turn
//! index within the session. A dotted line above the rectangle is the wait
//! for admission (batch cap or KV memory), a solid one the wait in the
//! prefill FIFO. Hovering a turn shows its times and its tokens prefilled,
//! reused and decoded; the header totals them per prefill kind.
//!
//! Two models:
//!
//! * `batch` (default): the two-resource replica of `models::batch`
//!   (`Server::TwoStage`, or `--server blocking`) on the open-session
//!   scenario of the paper's simulation section
//!   (`validation::open_session_cfg`). Prefills run one at a time in FIFO
//!   order while decodes of other sessions overlap.
//! * `agentic`: the single-turn replica of `models::agentic`
//!   (`AgenticConfig::example`), one turn at a time.
//!
//! ```text
//! cargo run --release --example trace_html -- --rate 0.28 --cap 24 --from 1000 --window 300
//! cargo run --release --example trace_html -- --model agentic --programs 16 --kv 150000
//! ```
//!
//! Synthetic workloads; not measurements.

use std::fmt::Write as _;

use libqueuingsim::models::agentic::{self, AgenticConfig};
use libqueuingsim::models::batch::{self, EvictionPolicy, Server, TurnKind, TurnSpan};
use libqueuingsim::validation::open_session_cfg;

#[derive(PartialEq)]
enum ModelKind {
    Batch,
    Agentic,
}

struct Args {
    model: ModelKind,
    blocking: bool,
    rate: f64,
    cap: usize,
    batch_cap: Option<usize>,
    programs: usize,
    kv: Option<f64>,
    from: Option<f64>,
    window: f64,
    eviction: EvictionPolicy,
    seed: u64,
    out: String,
}

const USAGE: &str = "usage: trace_html [--model batch|agentic] [--out PATH] [--from SECONDS] [--window SECONDS] \
[--seed N] [--kv TOKENS] [--eviction shortest|longest|lru|random|density|priced|priced-memory|priced-memory-blocks]
  batch only:   [--server two-stage|blocking] [--rate SESSIONS_PER_S] [--cap LIVE_SESSIONS] [--batch-cap N|none]
  agentic only: [--programs N]
The run is simulated from an empty system; --from (default: the scenario's warm-up, 1000 s for
batch, 500 s for agentic) is where the shown window starts, and statistics cover the window only.";

fn parse_args() -> Args {
    let mut a = Args {
        model: ModelKind::Batch,
        blocking: false,
        rate: 0.28,
        cap: 24,
        batch_cap: Some(8),
        programs: 16,
        kv: None,
        from: None,
        window: 300.0,
        eviction: EvictionPolicy::ShortestFirst,
        seed: 1,
        out: "trace.html".into(),
    };
    let argv: Vec<String> = std::env::args().skip(1).collect();
    let mut it = argv.iter();
    while let Some(flag) = it.next() {
        let mut val = || {
            it.next()
                .unwrap_or_else(|| panic!("{flag} needs a value"))
                .clone()
        };
        match flag.as_str() {
            "--model" => {
                a.model = match val().as_str() {
                    "batch" => ModelKind::Batch,
                    "agentic" => ModelKind::Agentic,
                    other => panic!("unknown model {other}"),
                }
            }
            "--server" => {
                a.blocking = match val().as_str() {
                    "two-stage" => false,
                    "blocking" => true,
                    other => panic!("unknown server {other}"),
                }
            }
            "--rate" => a.rate = val().parse().expect("--rate"),
            "--cap" => a.cap = val().parse().expect("--cap"),
            "--batch-cap" => {
                let v = val();
                a.batch_cap = if v == "none" {
                    None
                } else {
                    Some(v.parse().expect("--batch-cap"))
                };
            }
            "--programs" => a.programs = val().parse().expect("--programs"),
            "--kv" => a.kv = Some(val().parse().expect("--kv")),
            "--from" => a.from = Some(val().parse().expect("--from")),
            "--window" => a.window = val().parse().expect("--window"),
            "--seed" => a.seed = val().parse().expect("--seed"),
            "--out" => a.out = val(),
            "--eviction" => {
                a.eviction = match val().as_str() {
                    "shortest" => EvictionPolicy::ShortestFirst,
                    "longest" => EvictionPolicy::LongestFirst,
                    "lru" => EvictionPolicy::Lru,
                    "random" => EvictionPolicy::Random,
                    "density" => EvictionPolicy::Density,
                    "priced" => EvictionPolicy::Priced,
                    "priced-memory" => EvictionPolicy::PricedMemory,
                    "priced-memory-blocks" => EvictionPolicy::PricedMemoryBlocks,
                    other => panic!("unknown eviction policy {other}"),
                }
            }
            "-h" | "--help" => {
                eprintln!("{USAGE}");
                std::process::exit(0);
            }
            other => panic!("unknown argument {other}\n{USAGE}"),
        }
    }
    a
}

fn kind_code(k: TurnKind) -> &'static str {
    match k {
        TurnKind::Cold => "c",
        TurnKind::Hit => "h",
        TurnKind::Miss => "m",
    }
}

fn to_json(trace: &[TurnSpan]) -> String {
    // [session, turn, kind, enqueued, admitted, start, prefill_end, end,
    //  context, prefill_tokens, cached_tokens, decode_tokens]
    let mut s = String::from("[");
    for (i, t) in trace.iter().enumerate() {
        if i > 0 {
            s.push(',');
        }
        write!(
            s,
            "[{},{},\"{}\",{:.6},{:.6},{:.6},{:.6},{:.6},{:.0},{:.0},{:.0},{:.0}]",
            t.session,
            t.turn,
            kind_code(t.kind),
            t.enqueued,
            t.admitted,
            t.start,
            t.prefill_end,
            t.end,
            t.context,
            t.prefill_tokens,
            t.cached_tokens,
            t.decode_tokens
        )
        .unwrap();
    }
    s.push(']');
    s
}

fn json_str(s: &str) -> String {
    format!("\"{}\"", s.replace('\\', "\\\\").replace('"', "\\\""))
}

fn main() {
    let a = parse_args();
    let (desc, stats, from, horizon, trace) = match a.model {
        ModelKind::Batch => {
            let mut cfg = open_session_cfg(a.rate, a.cap, a.eviction, a.seed);
            if a.blocking {
                cfg.server = Server::BlockingPrefill {
                    phi: batch::Phi::Constant(1.0),
                };
            }
            if let Some(kv) = a.kv {
                cfg.kv_capacity = kv;
                cfg.max_context = 0.5 * kv;
            }
            cfg.batch_cap = a.batch_cap;
            cfg.warmup = a.from.unwrap_or(cfg.warmup);
            cfg.horizon = cfg.warmup + a.window;
            let (r, trace) = batch::simulate_traced(&cfg);
            let server = if a.blocking {
                "blocking prefill"
            } else {
                "two-resource replica (prefill FIFO + decode PS)"
            };
            let desc = format!(
                "Synthetic open-session workload (validation::open_session_cfg), not a measurement · \
                 {server} · Poisson sessions {} /s, ≤ {} live · batch cap {} · KV {} tokens · \
                 eviction {:?} · seed {}",
                a.rate,
                a.cap,
                a.batch_cap.map_or("none".into(), |b| b.to_string()),
                cfg.kv_capacity,
                a.eviction,
                a.seed
            );
            let stats = format!(
                "hit rate {:.1}% · mean TTFT {:.2} s · mean decode batch {:.1} · prefill availability {:.2}",
                100.0 * r.hit_rate,
                r.ttft.mean(),
                r.mean_decode_number,
                r.mean_availability
            );
            (desc, stats, cfg.warmup, cfg.horizon, trace)
        }
        ModelKind::Agentic => {
            let kv = a.kv.unwrap_or(150_000.0);
            let mut cfg = AgenticConfig {
                eviction: a.eviction,
                seed: a.seed,
                ..AgenticConfig::example(a.programs, kv)
            };
            cfg.warmup = a.from.unwrap_or(cfg.warmup);
            cfg.horizon = cfg.warmup + a.window;
            let (r, trace) = agentic::simulate_traced(&cfg);
            let desc = format!(
                "Synthetic workload (AgenticConfig::example), not a measurement · single-turn replica · \
                 {} programs (closed) · KV {kv} tokens · eviction {:?} · seed {}",
                a.programs, a.eviction, a.seed
            );
            let stats = format!(
                "hit rate {:.1}% · utilization {:.1}%",
                100.0 * r.hit_rate,
                100.0 * r.utilization
            );
            (desc, stats, cfg.warmup, cfg.horizon, trace)
        }
    };
    // Turns that overlap the window.
    let trace: Vec<TurnSpan> = trace.into_iter().filter(|t| t.end >= from).collect();
    let sessions = {
        let mut s: Vec<u64> = trace.iter().map(|t| t.session).collect();
        s.sort_unstable();
        s.dedup();
        s.len()
    };
    let meta = format!(
        "{{\"desc\":{},\"stats\":{},\"from\":{},\"horizon\":{}}}",
        json_str(&desc),
        json_str(&stats),
        from,
        horizon
    );
    let html = TEMPLATE
        .replace("/*__META__*/null", &meta)
        .replace("/*__DATA__*/[]", &to_json(&trace));
    std::fs::write(&a.out, html).expect("write output");
    eprintln!(
        "wrote {} ({} turns, {sessions} sessions; {stats})",
        a.out,
        trace.len()
    );
}

const TEMPLATE: &str = include_str!("trace_template.html");
