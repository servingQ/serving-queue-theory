//! seQ programs against the closed forms the paper proves (mirrors the
//! in-model checks of `libqueuingsim::validation`).

use libqueuingsim::analytic::{finite_source_mm1, mm1_wait, pk_wait};
use seq::run_program;

#[test]
fn mm1_sojourn_is_one_over_mu_minus_lambda() {
    for (i, lam) in [0.5, 0.8, 0.9].into_iter().enumerate() {
        let r = run_program(
            "mg1",
            &[&format!("lam={lam}"), "law=1"],
            Some(10 + i as u64),
            None,
        );
        let o = r.observe("sojourn").unwrap();
        let want = mm1_wait(1.0, lam);
        assert!(o.ci.agrees_with(want, 0.02), "λ={lam}: {} vs {want}", o.ci);
        // Little's law between the stage's time average and the sojourn.
        let l = r.stage("svc").unwrap().mean_number;
        assert!(
            (l - lam * o.mean).abs() / l < 0.03,
            "Little: {l} vs {}",
            lam * o.mean
        );
    }
}

#[test]
fn pk_wait_for_four_service_laws() {
    let lam = 0.8;
    for (law, m2) in [(0, 1.0), (1, 2.0), (2, 1.25), (3, 5.0)] {
        let r = run_program("mg1", &[&format!("law={law}"), "cv2=4"], Some(3), None);
        let o = r.observe("wait").unwrap();
        let want = pk_wait(lam, m2, lam);
        assert!(
            o.ci.agrees_with(want, 0.03),
            "law {law}: {} vs {want}",
            o.ci
        );
    }
}

#[test]
fn ps_mean_number_is_insensitive() {
    let lam = 0.7;
    let want = lam / (1.0 - lam);
    for law in [0, 1, 3] {
        let r = run_program("ps", &[&format!("law={law}")], Some(5), None);
        let l = r.stage("svc").unwrap().mean_number;
        assert!((l - want).abs() / want < 0.03, "law {law}: {l} vs {want}");
        let o = r.observe("sojourn").unwrap();
        assert!(
            o.ci.agrees_with(want / lam, 0.03),
            "law {law}: {} vs {}",
            o.ci,
            want / lam
        );
    }
}

#[test]
fn finite_source_wait_matches_mva() {
    for n in [2usize, 8, 32] {
        let r = run_program("closed", &[&format!("N={n}")], Some(7), None);
        let (l, x, wq) = finite_source_mm1(n, 1.0 / 4.0, 1.0);
        let o = r.observe("wait").unwrap();
        assert!(o.ci.agrees_with(wq, 0.05), "N={n}: wait {} vs {wq}", o.ci);
        let thru = r.stage("svc").unwrap().throughput;
        assert!((thru - x).abs() / x < 0.03, "N={n}: X {thru} vs {x}");
        let ln = r.stage("svc").unwrap().mean_number;
        assert!((ln - l).abs() / l < 0.05, "N={n}: L {ln} vs {l}");
    }
}
