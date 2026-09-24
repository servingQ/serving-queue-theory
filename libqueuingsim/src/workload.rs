//! Replayed agent sessions from real traces (paper §4.2 "What the traces
//! say", §4.1 trace replay).
//!
//! A [`TraceCorpus`] is a list of sessions, each a list of turns with the
//! tokens appended (`new`; the whole prompt on the first turn), the tokens
//! decoded (`out`) and the gap after the turn before the next one
//! (`think`, seconds; 0 on the last turn). [`super::models::batch`] can draw
//! its sessions from a corpus instead of from the class laws: arrivals stay
//! Poisson, but the turn sequence, the appends, the outputs and the think
//! times of each session are those of one real session, chosen uniformly.
//! Whether a session continues is then given by the trace, not by a resume
//! probability; the class fields still supply the scheduler's *estimates*
//! `p_i` and `τ_i`.
//!
//! The bundled corpus [`TraceCorpus::weka`] is derived from the public
//! `semianalysisai/cc-traces-weka-061326` dataset (183 production Claude
//! Code sessions) by `scripts/trace_stats_weka.py --export-csv`: main-agent
//! requests only, the append measured as prompt tokens beyond the longest
//! prefix already seen in the session, and a session split where a gap
//! exceeds ten minutes. Numbers obtained by replaying it are properties of
//! the simulated replica under a real *workload*; they are not measurements
//! of a serving system.

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct TraceTurn {
    /// Tokens prefilled on a hit: the append (turn 1: the whole prompt).
    pub new: f64,
    /// Output tokens.
    pub out: f64,
    /// Gap after this turn before the next one (s); 0 on the last turn.
    pub think: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TraceSession {
    pub turns: Vec<TraceTurn>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TraceCorpus {
    pub sessions: Vec<TraceSession>,
}

impl TraceCorpus {
    /// Parse `session,turn,new,out,think` lines (`#` comments and a header
    /// allowed). Turns of a session must be contiguous and in order.
    pub fn from_csv(text: &str) -> Self {
        let mut sessions: Vec<TraceSession> = vec![];
        let mut last: Option<u64> = None;
        for line in text.lines() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') || line.starts_with("session") {
                continue;
            }
            let f: Vec<&str> = line.split(',').collect();
            assert_eq!(f.len(), 5, "bad trace line: {line}");
            let sid: u64 = f[0].parse().expect("session id");
            if last != Some(sid) {
                sessions.push(TraceSession::default());
                last = Some(sid);
            }
            sessions.last_mut().unwrap().turns.push(TraceTurn {
                new: f[2].parse().expect("new"),
                out: f[3].parse().expect("out"),
                think: f[4].parse().expect("think"),
            });
        }
        assert!(!sessions.is_empty(), "empty trace corpus");
        Self { sessions }
    }

    /// The bundled production Claude Code corpus (see the module doc):
    /// sessions split at gaps above 10 minutes.
    pub fn weka() -> Self {
        Self::from_csv(include_str!("../data/weka-sessions.csv"))
    }

    /// The same corpus split at gaps above 30 minutes (sensitivity of the
    /// replay to the split rule).
    pub fn weka_split_30min() -> Self {
        Self::from_csv(include_str!("../data/weka-sessions-1800.csv"))
    }

    pub fn turns(&self) -> usize {
        self.sessions.iter().map(|s| s.turns.len()).sum()
    }

    pub fn mean_turns(&self) -> f64 {
        self.turns() as f64 / self.sessions.len() as f64
    }

    /// Mean think time over turns that have a successor (the `τ` a
    /// scheduler would estimate for the whole corpus).
    pub fn mean_think(&self) -> f64 {
        let xs: Vec<f64> = self
            .sessions
            .iter()
            .flat_map(|s| s.turns.iter().take(s.turns.len() - 1).map(|t| t.think))
            .collect();
        xs.iter().sum::<f64>() / xs.len().max(1) as f64
    }

    /// Fraction of turns that are followed by another turn: the corpus-wide
    /// resume probability a scheduler would estimate.
    pub fn resume_fraction(&self) -> f64 {
        let n = self.turns() as f64;
        (n - self.sessions.len() as f64) / n
    }

    /// Mean context after the last turn (tokens).
    pub fn mean_final_context(&self) -> f64 {
        let xs: Vec<f64> = self
            .sessions
            .iter()
            .map(|s| s.turns.iter().map(|t| t.new + t.out).sum::<f64>())
            .collect();
        xs.iter().sum::<f64>() / xs.len() as f64
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_and_summarises() {
        let c = TraceCorpus::from_csv(
            "# c\nsession,turn,new,out,think\n0,1,100,10,5\n0,2,20,10,0\n1,1,50,5,0\n",
        );
        assert_eq!(c.sessions.len(), 2);
        assert_eq!(c.turns(), 3);
        assert_eq!(c.sessions[0].turns[1].new, 20.0);
        assert!((c.mean_turns() - 1.5).abs() < 1e-12);
        assert!((c.resume_fraction() - 1.0 / 3.0).abs() < 1e-12);
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
