//! WEKA trace inputs and summaries for the paper's scenarios.
//!
//! The session and turn data types and CSV parser come from seQ. This module
//! only selects the bundled corpora and computes the scheduler estimates and
//! table inputs used by the research scenarios.
//!
//! The bundled WEKA corpus contains 183 production Claude Code sessions,
//! exported from `semianalysisai/cc-traces-weka-061326` by
//! `scripts/trace_stats_weka.py --export-csv`. It includes main-agent
//! requests, measures `new` as tokens beyond the longest earlier prefix in a
//! session, and splits sessions at gaps over ten minutes.

pub use seq::trace::{Corpus as TraceCorpus, TraceSession, Turn as TraceTurn};

/// Paper-specific corpus selections and summary statistics.
///
/// These methods are kept here because the bundled WEKA files and the
/// scheduler estimates derived from them belong to this research project.
pub trait TraceCorpusExt: Sized {
    fn weka() -> Self;
    fn weka_split_30min() -> Self;
    fn mean_turns(&self) -> f64;
    fn mean_think(&self) -> f64;
    fn resume_fraction(&self) -> f64;
    fn mean_final_context(&self) -> f64;
}

impl TraceCorpusExt for TraceCorpus {
    fn weka() -> Self {
        Self::from_csv(include_str!("../data/weka-sessions.csv")).expect("valid WEKA trace")
    }

    fn weka_split_30min() -> Self {
        Self::from_csv(include_str!("../data/weka-sessions-1800.csv"))
            .expect("valid 30-minute WEKA trace")
    }

    fn mean_turns(&self) -> f64 {
        self.turns() as f64 / self.sessions.len() as f64
    }

    fn mean_think(&self) -> f64 {
        let (sum, count) = self.sessions.iter().fold((0.0, 0usize), |(sum, count), s| {
            let n = s.turns.len().saturating_sub(1);
            (
                sum + s.turns.iter().take(n).map(|t| t.think).sum::<f64>(),
                count + n,
            )
        });
        sum / count.max(1) as f64
    }

    fn resume_fraction(&self) -> f64 {
        let n = self.turns() as f64;
        (n - self.sessions.len() as f64) / n
    }

    fn mean_final_context(&self) -> f64 {
        let total: f64 = self
            .sessions
            .iter()
            .map(|s| s.turns.iter().map(|t| t.new + t.out).sum::<f64>())
            .sum();
        total / self.sessions.len() as f64
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn seq_parser_and_summaries() {
        let c = TraceCorpus::from_csv(
            "# c\nsession,turn,new,out,think,forced\n0,1,100,10,5,0\n0,2,20,10,0,1\n1,1,50,5,0,0\n",
        )
        .unwrap();
        assert_eq!(c.sessions.len(), 2);
        assert_eq!(c.turns(), 3);
        assert_eq!(c.sessions[0].turns[1].new, 20.0);
        assert_eq!(c.sessions[0].turns[1].forced, 1.0);
        assert!((c.mean_turns() - 1.5).abs() < 1e-12);
        assert!((c.mean_think() - 5.0).abs() < 1e-12);
        assert!((c.resume_fraction() - 1.0 / 3.0).abs() < 1e-12);
        assert!((c.mean_final_context() - 97.5).abs() < 1e-12);
    }

    #[test]
    fn bundled_corpus_is_sane() {
        let c = TraceCorpus::weka();
        assert!(c.sessions.len() > 100);
        assert!(c.mean_turns() > 5.0);
        assert!(c.sessions.iter().all(|s| s.turns.len() >= 2));
        assert!(
            c.sessions
                .iter()
                .all(|s| s.turns.last().unwrap().think == 0.0)
        );
    }
}
