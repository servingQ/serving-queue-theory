//! seQ's step stage against the closed forms of the paper's two-resource
//! replica (prefill alone is M/D/1; decode at zero context is an infinite
//! server) and the PD tandem against the capacity formulas.

use paper_validation::Dist;
use paper_validation::models::batch::{self, BatchConfig, Server, Work};
use paper_validation::models::pd;
use paper_validation::validation::pd_cfg;
use seq::{Overrides, run_program, run_source};

/// With no decode the prefill stage is an M/D/1 at rate 1 (budget omega/a
/// tokens per omega seconds).
#[test]
fn step_prefill_alone_is_md1() {
    let lam = 0.7;
    let src = format!(
        r#"
        let a = 2e-5; let omega = 2e-4;
        stage engine : step {{ budget max(ndec, omega / a); cost max(omega, ntok * a); }}
        workload {{ arrive poisson({lam}); init {{ set t0 = now; }} }}
        session {{ run engine prefill (1 / a); observe sojourn = now - t0; end; }}
        run {{ horizon 3000; warmup 300; seed 8; }}
        "#
    );
    let r = run_source(&src, &Overrides::default(), None).unwrap();
    let o = r.observe("sojourn").unwrap();
    let want = 1.0 + lam / (2.0 * (1.0 - lam));
    assert!(
        o.ci.agrees_with(want, 0.03),
        "{} vs {want}\n{}",
        o.ci,
        r.text()
    );
}

/// With K = 0 and n < omega/a every decode of 500 tokens takes 0.1 s.
#[test]
fn step_decode_is_infinite_server_at_zero_context() {
    let lam = 3.0;
    let src = format!(
        r#"
        let a = 2e-5; let omega = 2e-4;
        stage engine : step {{ budget max(ndec, omega / a); cost max(omega, ntok * a); }}
        workload {{ arrive poisson({lam}); init {{ set t0 = now; }} }}
        session {{ run engine decode (500); observe response = now - t0; end; }}
        run {{ horizon 2000; warmup 200; seed 9; }}
        "#
    );
    let r = run_source(&src, &Overrides::default(), None).unwrap();
    let o = r.observe("response").unwrap();
    assert!((o.mean - 0.1).abs() < 1e-3, "{}", o.mean);
    let n = r.stage("engine").unwrap().mean_number;
    assert!((n - 0.3).abs() < 0.02, "{n}");
}

/// `pd_capacity_matches`: saturated throughput of the aggregated pool and
/// of three splits and a slow link.
#[test]
fn pd_tandem_capacity() {
    let agg = run_program("pd_tandem", &["mode=0"], Some(2), None);
    let want = 32.0 / (1.0 + 1.0 + 0.5);
    let x = agg.stage("agg").unwrap().throughput;
    assert!((x - want).abs() / want < 0.02, "agg {x} vs {want}");
    for (np, bnet) in [(10usize, 1000.0), (11, 1000.0), (12, 1000.0), (11, 10.0)] {
        let cfg = pd_cfg(
            32,
            pd::Mode::Disaggregated {
                prefill_devices: np,
            },
            1.0,
            1.0,
            0.5,
            (2.0, 1.0),
            bnet,
        );
        let want = pd::split_capacity(&cfg, np);
        let r = run_program(
            "pd_tandem",
            &["mode=1", &format!("NP={np}"), &format!("bnet={bnet}")],
            Some(3),
            None,
        );
        let x = r.stage("decode").unwrap().throughput;
        assert!(
            (x - want).abs() / want < 0.02,
            "N_P={np} B={bnet}: {x} vs {want}"
        );
    }
}

/// The lecture's disaggregated replica runs, is stable, and its TTFT is
/// the memory wait plus the prefill wait plus the prefill work.
#[test]
fn lecture_pd_program_runs() {
    let r = run_program("lecture_pd", &[], Some(1), None);
    assert!(r.turns > 500, "{}", r.text());
    let p = r.stage("prefill").unwrap();
    assert!(p.utilization < 0.95, "unstable: {}", r.text());
    let ttft = r.observe("ttft").unwrap().mean;
    let memp = r.pool("memP").unwrap().mean_wait;
    assert!(
        ttft >= p.mean_wait + p.mean_service + memp - 1e-6,
        "{}",
        r.text()
    );
    assert!(r.observe("miss").unwrap().mean < 0.5);
}

/// A sampled-work sanity check: Poisson turns on a PS engine with a cap
/// (`Phi::Saturating` cap 8) equals `ps(min(n, 8))`.
#[test]
fn ps_capacity_matches_batch_ps_server() {
    let lam = 2.0;
    let mut cfg = BatchConfig::poisson_turns(
        lam,
        Dist::exp(1.0),
        Server::Ps {
            phi: batch::Phi::Saturating {
                beta: 0.0,
                cap: Some(8),
            },
        },
        20000.0,
        4,
    );
    cfg.work = Work::Sampled {
        prefill: Dist::exp(1.0),
        decode: Dist::Deterministic(0.0),
    };
    let r = batch::simulate(&cfg);
    let src = format!(
        r#"
        stage svc : ps(min(n, 8));
        workload {{ arrive poisson({lam}); init {{ set t0 = now; }} }}
        session {{ run svc (~exp(1)); observe response = now - t0; end; }}
        run {{ horizon 20000; warmup 1000; seed 4; }}
        "#
    );
    let o = run_source(&src, &Overrides::default(), None).unwrap();
    let (a, b) = (o.observe("response").unwrap().mean, r.response.mean());
    assert!((a - b).abs() / b < 0.05, "{a} vs {b}");
}
