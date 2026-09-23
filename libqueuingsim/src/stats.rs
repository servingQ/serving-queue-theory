//! Output analysis: running moments, time averages, batch-means intervals.

/// Running mean and variance (Welford). Also reports the raw second moment,
/// which is what the PK formula consumes.
#[derive(Clone, Debug, Default)]
pub struct Welford {
    n: u64,
    mean: f64,
    m2: f64,
}

impl Welford {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn push(&mut self, x: f64) {
        self.n += 1;
        let d = x - self.mean;
        self.mean += d / self.n as f64;
        self.m2 += d * (x - self.mean);
    }

    pub fn n(&self) -> u64 {
        self.n
    }

    pub fn mean(&self) -> f64 {
        self.mean
    }

    /// Population variance `E[(X - E X)^2]`.
    pub fn variance(&self) -> f64 {
        if self.n == 0 {
            0.0
        } else {
            self.m2 / self.n as f64
        }
    }

    /// `E[X^2]`.
    pub fn second_moment(&self) -> f64 {
        self.variance() + self.mean * self.mean
    }

    /// Squared coefficient of variation `Var/E^2`.
    pub fn cv2(&self) -> f64 {
        self.variance() / (self.mean * self.mean)
    }
}

/// Time-weighted average of a piecewise-constant signal (queue length,
/// resident KV, busy servers).
#[derive(Clone, Debug)]
pub struct TimeAverage {
    start: f64,
    last_t: f64,
    value: f64,
    area: f64,
}

impl TimeAverage {
    pub fn new(t0: f64, v0: f64) -> Self {
        Self {
            start: t0,
            last_t: t0,
            value: v0,
            area: 0.0,
        }
    }

    /// The signal takes value `v` from time `t` on.
    pub fn set(&mut self, t: f64, v: f64) {
        debug_assert!(t >= self.last_t);
        self.area += self.value * (t - self.last_t);
        self.last_t = t;
        self.value = v;
    }

    /// Change the signal by `dv` at time `t`.
    pub fn add(&mut self, t: f64, dv: f64) {
        let v = self.value + dv;
        self.set(t, v);
    }

    pub fn value(&self) -> f64 {
        self.value
    }

    /// Forget the history before `t` (end of warm-up).
    pub fn reset(&mut self, t: f64) {
        self.set(t, self.value);
        self.start = t;
        self.area = 0.0;
    }

    /// Average over `[start, t_end]`.
    pub fn mean(&self, t_end: f64) -> f64 {
        let span = t_end - self.start;
        if span <= 0.0 {
            return self.value;
        }
        (self.area + self.value * (t_end - self.last_t)) / span
    }
}

/// A point estimate with a 95 % confidence half-width.
#[derive(Clone, Copy, Debug)]
pub struct Estimate {
    pub mean: f64,
    pub half_width: f64,
}

impl Estimate {
    pub fn lo(&self) -> f64 {
        self.mean - self.half_width
    }

    pub fn hi(&self) -> f64 {
        self.mean + self.half_width
    }

    /// Does the interval, widened by a relative slack `rel`, contain `x`?
    /// The slack absorbs finite-horizon bias that batch means do not cover.
    pub fn agrees_with(&self, x: f64, rel: f64) -> bool {
        let slack = rel * x.abs();
        self.lo() - slack <= x && x <= self.hi() + slack
    }

    pub fn relative_error(&self, x: f64) -> f64 {
        (self.mean - x).abs() / x.abs()
    }
}

impl std::fmt::Display for Estimate {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{:.4} ± {:.4}", self.mean, self.half_width)
    }
}

/// Two-sided 97.5 % Student-t quantile.
pub fn t975(df: usize) -> f64 {
    const T: [f64; 30] = [
        12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160,
        2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056,
        2.052, 2.048, 2.045, 2.042,
    ];
    match df {
        0 => f64::INFINITY,
        1..=30 => T[df - 1],
        31..=60 => 2.000,
        61..=120 => 1.980,
        _ => 1.960,
    }
}

/// Batch-means estimate of the steady-state mean of a (possibly
/// autocorrelated) output sequence, split into `batches` contiguous batches.
pub fn batch_means(xs: &[f64], batches: usize) -> Estimate {
    assert!(batches >= 2, "need at least two batches");
    let size = xs.len() / batches;
    assert!(size >= 1, "{} observations < {batches} batches", xs.len());
    let means: Vec<f64> = xs
        .chunks_exact(size)
        .take(batches)
        .map(|c| c.iter().sum::<f64>() / size as f64)
        .collect();
    let k = means.len() as f64;
    let m = means.iter().sum::<f64>() / k;
    let var = means.iter().map(|x| (x - m).powi(2)).sum::<f64>() / (k - 1.0);
    Estimate {
        mean: m,
        half_width: t975(means.len() - 1) * (var / k).sqrt(),
    }
}

/// Mean and 95 % half-width across independent replications.
pub fn replications(xs: &[f64]) -> Estimate {
    let k = xs.len();
    assert!(k >= 2, "need at least two replications");
    let m = xs.iter().sum::<f64>() / k as f64;
    let var = xs.iter().map(|x| (x - m).powi(2)).sum::<f64>() / (k as f64 - 1.0);
    Estimate {
        mean: m,
        half_width: t975(k - 1) * (var / k as f64).sqrt(),
    }
}

/// Empirical quantile (nearest-rank) of an unsorted slice.
pub fn quantile(xs: &[f64], q: f64) -> f64 {
    assert!(!xs.is_empty());
    let mut v = xs.to_vec();
    v.sort_by(f64::total_cmp);
    let idx = ((q * v.len() as f64).ceil() as usize).clamp(1, v.len()) - 1;
    v[idx]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn welford_matches_direct() {
        let xs = [1.0, 2.0, 4.0, 7.0];
        let mut w = Welford::new();
        xs.iter().for_each(|&x| w.push(x));
        assert!((w.mean() - 3.5).abs() < 1e-12);
        assert!((w.variance() - 5.25).abs() < 1e-12);
        assert!((w.second_moment() - 17.5).abs() < 1e-12);
    }

    #[test]
    fn time_average_of_step() {
        let mut a = TimeAverage::new(0.0, 0.0);
        a.set(1.0, 2.0);
        a.set(3.0, 0.0);
        assert!((a.mean(4.0) - 1.0).abs() < 1e-12);
        a.reset(4.0);
        a.set(5.0, 3.0);
        assert!((a.mean(6.0) - 1.5).abs() < 1e-12);
    }

    #[test]
    fn batch_means_of_constant_has_zero_width() {
        let e = batch_means(&[2.0; 100], 10);
        assert_eq!(e.mean, 2.0);
        assert_eq!(e.half_width, 0.0);
    }

    #[test]
    fn quantile_nearest_rank() {
        let xs = [5.0, 1.0, 3.0, 2.0, 4.0];
        assert_eq!(quantile(&xs, 0.5), 3.0);
        assert_eq!(quantile(&xs, 1.0), 5.0);
        assert_eq!(quantile(&xs, 0.0), 1.0);
    }
}
