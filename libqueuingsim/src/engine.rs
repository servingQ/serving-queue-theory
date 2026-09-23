//! Event-scheduling core.
//!
//! A [`Scheduler`] is a min-heap of `(time, seq, event)`. Ties in time are
//! broken by insertion order (`seq`), so a run is fully determined by the
//! model and its RNG seed.

use std::cmp::Ordering;
use std::collections::BinaryHeap;

struct Entry<E> {
    time: f64,
    seq: u64,
    event: E,
}

impl<E> PartialEq for Entry<E> {
    fn eq(&self, other: &Self) -> bool {
        self.seq == other.seq
    }
}

impl<E> Eq for Entry<E> {}

impl<E> Ord for Entry<E> {
    // Reversed so that `BinaryHeap` (a max-heap) pops the earliest event.
    fn cmp(&self, other: &Self) -> Ordering {
        other
            .time
            .total_cmp(&self.time)
            .then_with(|| other.seq.cmp(&self.seq))
    }
}

impl<E> PartialOrd for Entry<E> {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

/// Future-event list plus the simulation clock.
pub struct Scheduler<E> {
    now: f64,
    seq: u64,
    processed: u64,
    heap: BinaryHeap<Entry<E>>,
}

impl<E> Default for Scheduler<E> {
    fn default() -> Self {
        Self::new()
    }
}

impl<E> Scheduler<E> {
    pub fn new() -> Self {
        Self {
            now: 0.0,
            seq: 0,
            processed: 0,
            heap: BinaryHeap::new(),
        }
    }

    /// Current simulation time.
    pub fn now(&self) -> f64 {
        self.now
    }

    /// Schedule `event` at absolute time `time` (must not be in the past).
    pub fn at(&mut self, time: f64, event: E) {
        assert!(
            time.is_finite() && time >= self.now,
            "event scheduled at {time} but clock is {}",
            self.now
        );
        self.heap.push(Entry {
            time,
            seq: self.seq,
            event,
        });
        self.seq += 1;
    }

    /// Schedule `event` after a non-negative `delay`.
    pub fn after(&mut self, delay: f64, event: E) {
        assert!(delay >= 0.0, "negative delay {delay}");
        self.at(self.now + delay, event);
    }

    /// Number of events still pending.
    pub fn pending(&self) -> usize {
        self.heap.len()
    }

    /// Number of events handled so far.
    pub fn processed(&self) -> u64 {
        self.processed
    }

    fn peek_time(&self) -> Option<f64> {
        self.heap.peek().map(|e| e.time)
    }

    fn pop(&mut self) -> Option<E> {
        let e = self.heap.pop()?;
        self.now = e.time;
        self.processed += 1;
        Some(e.event)
    }
}

/// A simulated system: reacts to events and schedules new ones.
pub trait Model {
    type Event;

    fn handle(&mut self, event: Self::Event, sched: &mut Scheduler<Self::Event>);

    /// Checked after every event; return `true` to stop early.
    fn finished(&self) -> bool {
        false
    }
}

/// Run until the event list is empty, the next event is after `horizon`,
/// or [`Model::finished`] returns true. Returns the final clock value.
pub fn run<M: Model>(model: &mut M, sched: &mut Scheduler<M::Event>, horizon: f64) -> f64 {
    while let Some(t) = sched.peek_time() {
        if t > horizon {
            break;
        }
        let ev = sched.pop().expect("peeked");
        model.handle(ev, sched);
        if model.finished() {
            break;
        }
    }
    sched.now()
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Recorder(Vec<(f64, u32)>);

    impl Model for Recorder {
        type Event = u32;
        fn handle(&mut self, ev: u32, s: &mut Scheduler<u32>) {
            self.0.push((s.now(), ev));
            if ev == 0 {
                s.after(1.0, 10);
                s.after(0.0, 11);
            }
        }
    }

    #[test]
    fn events_are_time_ordered_and_ties_fifo() {
        let mut s = Scheduler::new();
        s.at(2.0, 2);
        s.at(1.0, 1);
        s.at(1.0, 0);
        let mut m = Recorder(vec![]);
        let end = run(&mut m, &mut s, f64::INFINITY);
        assert_eq!(
            m.0,
            vec![(1.0, 1), (1.0, 0), (1.0, 11), (2.0, 2), (2.0, 10)]
        );
        assert_eq!(end, 2.0);
        assert_eq!(s.processed(), 5);
    }

    #[test]
    fn horizon_stops_run() {
        let mut s = Scheduler::new();
        s.at(1.0, 1);
        s.at(5.0, 5);
        let mut m = Recorder(vec![]);
        run(&mut m, &mut s, 3.0);
        assert_eq!(m.0, vec![(1.0, 1)]);
        assert_eq!(s.pending(), 1);
    }

    #[test]
    #[should_panic]
    fn scheduling_in_the_past_panics() {
        let mut s: Scheduler<u32> = Scheduler::new();
        s.at(1.0, 0);
        s.pop();
        s.at(0.5, 1);
    }
}
