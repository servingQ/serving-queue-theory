/-
# The prefill queue with a finite population: M/M/1//N

Proposition (paper `prop:finite`, §2.4).  A replica with `N` live sessions
is a finite-source system: each session thinks for an exponential time of
mean `Z` and then submits a turn of exponential work with mean `1/μ` to one
FIFO server.  Mean value analysis (the arrival theorem for this closed
network) gives the mean number at the server exactly by the recursion

  `Q 0 = 0`,  `Q (n+1) = (n+1) (1 + Q n) / (c + 1 + Q n)`,  `c = μ Z`,

with response time `R (n+1) = (1 + Q n) / μ`, throughput
`X (n+1) = (n+1) / (Z + R (n+1))`, utilisation `ρ (n+1) = X (n+1) / μ`
and mean wait in queue `W (n+1) = Q n / μ` (an arriving turn finds, in
expectation, the `n`-session mean number `Q n` ahead of it).

We prove:
* `mvaQ_nonneg`, `mvaQ_le_card` : `0 ≤ Q n ≤ n`.
* `mvaQ_mono`                  : `Q n ≤ Q (n+1)` (more sessions, more at the server).
* `mvaQ_gt_sub`                : `n - c < Q n`, hence `ρ (n+1) < 1`.
* `finite_source_rho_lt_one`   : the utilisation of the finite-source system is below one.
* `finite_source_wait_le_open` : `W (n+1) ≤ ρ (n+1) / (μ (1 - ρ (n+1)))`,
  the open M/M/1 wait at the same utilisation.  The open formula of
  Prop. price is therefore an upper bound for a finite live population.
* `closed_price_cap`           : any change of policy at fixed population
  `N` changes the mean number at the server by at most `N - L`.
-/
import Mathlib.Tactic

namespace ServingQueueTheory

/-- `g c q = (1 + q) / (c + 1 + q)`: the fraction of a session's cycle spent
at the server when the others leave `q` turns there on average. -/
noncomputable def mvaG (c q : ℝ) : ℝ := (1 + q) / (c + 1 + q)

/-- Mean number at the server with `n` sessions (mean value analysis). -/
noncomputable def mvaQ (c : ℝ) : ℕ → ℝ
  | 0 => 0
  | n + 1 => (n + 1 : ℝ) * mvaG c (mvaQ c n)

theorem mvaQ_zero (c : ℝ) : mvaQ c 0 = 0 := rfl

theorem mvaQ_succ (c : ℝ) (n : ℕ) : mvaQ c (n + 1) = (n + 1 : ℝ) * mvaG c (mvaQ c n) := rfl

theorem mvaG_nonneg {c q : ℝ} (hc : 0 < c) (hq : 0 ≤ q) : 0 ≤ mvaG c q := by
  unfold mvaG; positivity

theorem mvaG_le_one {c q : ℝ} (hc : 0 < c) (hq : 0 ≤ q) : mvaG c q ≤ 1 := by
  unfold mvaG
  rw [div_le_one (by positivity)]
  linarith

/-- `g` is nondecreasing on `q ≥ 0`. -/
theorem mvaG_mono {c q q' : ℝ} (hc : 0 < c) (hq : 0 ≤ q) (hqq : q ≤ q') :
    mvaG c q ≤ mvaG c q' := by
  unfold mvaG
  have h1 : 0 < c + 1 + q := by positivity
  have h2 : 0 < c + 1 + q' := by linarith
  rw [div_le_div_iff₀ h1 h2]
  nlinarith

theorem mvaQ_nonneg {c : ℝ} (hc : 0 < c) : ∀ n, 0 ≤ mvaQ c n
  | 0 => le_rfl
  | n + 1 => by
    rw [mvaQ_succ]
    exact mul_nonneg (by positivity) (mvaG_nonneg hc (mvaQ_nonneg hc n))

/-- At most `n` turns are at the server with `n` sessions. -/
theorem mvaQ_le_card {c : ℝ} (hc : 0 < c) : ∀ n : ℕ, mvaQ c n ≤ n
  | 0 => by simp [mvaQ_zero]
  | n + 1 => by
    rw [mvaQ_succ]
    have := mvaG_le_one hc (mvaQ_nonneg hc n)
    have hn : (0 : ℝ) ≤ n + 1 := by positivity
    calc (n + 1 : ℝ) * mvaG c (mvaQ c n) ≤ (n + 1 : ℝ) * 1 := by
          exact mul_le_mul_of_nonneg_left this hn
      _ = ((n + 1 : ℕ) : ℝ) := by push_cast; ring

/-- **More sessions, more turns at the server.** -/
theorem mvaQ_mono {c : ℝ} (hc : 0 < c) : ∀ n, mvaQ c n ≤ mvaQ c (n + 1)
  | 0 => by
    rw [mvaQ_zero, mvaQ_succ]
    exact mul_nonneg (by norm_num) (mvaG_nonneg hc le_rfl)
  | n + 1 => by
    have ih := mvaQ_mono hc n
    rw [mvaQ_succ, mvaQ_succ]
    have hg := mvaG_mono hc (mvaQ_nonneg hc n) ih
    have hg0 := mvaG_nonneg hc (mvaQ_nonneg hc (n + 1))
    calc (n + 1 : ℝ) * mvaG c (mvaQ c n) ≤ (n + 1 : ℝ) * mvaG c (mvaQ c (n + 1)) :=
          mul_le_mul_of_nonneg_left hg (by positivity)
      _ ≤ ((n + 1 : ℕ) + 1 : ℝ) * mvaG c (mvaQ c (n + 1)) := by
          apply mul_le_mul_of_nonneg_right _ hg0
          push_cast; linarith

/-- `Q n > n - c`: with `c = μZ` this is the finite-source utilisation
being below one (`finite_source_rho_lt_one`). -/
theorem mvaQ_gt_sub {c : ℝ} (hc : 0 < c) : ∀ n : ℕ, (n : ℝ) - c < mvaQ c n
  | 0 => by simp [mvaQ_zero]; exact hc
  | n + 1 => by
    have ih := mvaQ_gt_sub hc n
    have hq := mvaQ_nonneg hc n
    rw [mvaQ_succ]
    unfold mvaG
    have hd : 0 < c + 1 + mvaQ c n := by positivity
    rw [← mul_div_assoc, lt_div_iff₀ hd]
    push_cast
    nlinarith

/-- `g` is nonincreasing in `c` on `q ≥ 0`: more think time relative to
service, a smaller fraction of the cycle at the server. -/
theorem mvaG_anti_c {c c' q : ℝ} (hc : 0 < c) (hcc : c ≤ c') (hq : 0 ≤ q) :
    mvaG c' q ≤ mvaG c q := by
  unfold mvaG
  have h1 : 0 < c + 1 + q := by positivity
  have h2 : 0 < c' + 1 + q := by linarith
  rw [div_le_div_iff₀ h2 h1]
  nlinarith

/-- **The mean number at the server is nonincreasing in `c = μZ`.** With
`n` sessions, longer think time or shorter service leaves fewer turns at
the server; read with `c = Z/E[S]`, a rise of the mean work from `1/μ` to
`1/μ'` raises `Q n` by the exact finite-source price of the longer job. -/
theorem mvaQ_anti_c {c c' : ℝ} (hc : 0 < c) (hcc : c ≤ c') : ∀ n, mvaQ c' n ≤ mvaQ c n
  | 0 => le_rfl
  | n + 1 => by
    have ih := mvaQ_anti_c hc hcc n
    have hc' : 0 < c' := by linarith
    rw [mvaQ_succ, mvaQ_succ]
    apply mul_le_mul_of_nonneg_left _ (by positivity)
    calc mvaG c' (mvaQ c' n) ≤ mvaG c' (mvaQ c n) := mvaG_mono hc' (mvaQ_nonneg hc' n) ih
      _ ≤ mvaG c (mvaQ c n) := mvaG_anti_c hc hcc (mvaQ_nonneg hc n)

/-! ### Throughput, utilisation and the wait with `n + 1` sessions -/

/-- Response time with `n + 1` sessions: `(1 + Q n) / μ` (arrival theorem). -/
noncomputable def mvaR (mu c : ℝ) (n : ℕ) : ℝ := (1 + mvaQ c n) / mu

/-- Throughput with `n + 1` sessions: `(n+1) / (Z + R)`. -/
noncomputable def mvaX (mu Z : ℝ) (n : ℕ) : ℝ := (n + 1 : ℝ) / (Z + mvaR mu (mu * Z) n)

/-- Utilisation with `n + 1` sessions: `X / μ`. -/
noncomputable def mvaRho (mu Z : ℝ) (n : ℕ) : ℝ := mvaX mu Z n / mu

/-- Mean wait in queue with `n + 1` sessions: `Q n / μ`. -/
noncomputable def mvaW (mu Z : ℝ) (n : ℕ) : ℝ := mvaQ (mu * Z) n / mu

theorem mvaRho_eq {mu Z : ℝ} (hmu : 0 < mu) (hZ : 0 < Z) (n : ℕ) :
    mvaRho mu Z n = (n + 1 : ℝ) / (mu * Z + 1 + mvaQ (mu * Z) n) := by
  unfold mvaRho mvaX mvaR
  have hc : 0 < mu * Z := by positivity
  have hq := mvaQ_nonneg hc n
  have h1 : Z + (1 + mvaQ (mu * Z) n) / mu ≠ 0 := by positivity
  have h2 : mu * Z + 1 + mvaQ (mu * Z) n ≠ 0 := by positivity
  field_simp
  ring

/-- Little's law inside the recursion: `Q (n+1) = X R`. -/
theorem mvaQ_succ_eq_rho_mul {mu Z : ℝ} (hmu : 0 < mu) (hZ : 0 < Z) (n : ℕ) :
    mvaQ (mu * Z) (n + 1) = mvaRho mu Z n * (1 + mvaQ (mu * Z) n) := by
  rw [mvaRho_eq hmu hZ, mvaQ_succ]
  unfold mvaG
  have hc : 0 < mu * Z := by positivity
  have hq := mvaQ_nonneg hc n
  have h2 : mu * Z + 1 + mvaQ (mu * Z) n ≠ 0 := by positivity
  field_simp

/-- **The finite-source utilisation is below one.** -/
theorem finite_source_rho_lt_one {mu Z : ℝ} (hmu : 0 < mu) (hZ : 0 < Z) (n : ℕ) :
    mvaRho mu Z n < 1 := by
  rw [mvaRho_eq hmu hZ]
  have hc : 0 < mu * Z := by positivity
  have hq := mvaQ_nonneg hc n
  have hgt := mvaQ_gt_sub hc n
  rw [div_lt_one (by positivity)]
  linarith

theorem finite_source_rho_nonneg {mu Z : ℝ} (hmu : 0 < mu) (hZ : 0 < Z) (n : ℕ) :
    0 ≤ mvaRho mu Z n := by
  rw [mvaRho_eq hmu hZ]
  have hc : 0 < mu * Z := by positivity
  have hq := mvaQ_nonneg hc n
  positivity

/-- **The open M/M/1 wait at the same utilisation is an upper bound on the
finite-source wait.**  `W (n+1) = Q n / μ ≤ ρ / (μ (1 - ρ))` with
`ρ = ρ (n+1) < 1`.  The inequality is `Q n ≤ Q (n+1)`. -/
theorem finite_source_wait_le_open {mu Z : ℝ} (hmu : 0 < mu) (hZ : 0 < Z) (n : ℕ) :
    mvaW mu Z n ≤ mvaRho mu Z n / (mu * (1 - mvaRho mu Z n)) := by
  have hc : 0 < mu * Z := by positivity
  have hρ1 := finite_source_rho_lt_one hmu hZ n
  have hρ0 := finite_source_rho_nonneg hmu hZ n
  have hmono := mvaQ_mono hc n
  have hlit := mvaQ_succ_eq_rho_mul hmu hZ n
  have hq := mvaQ_nonneg hc n
  set q := mvaQ (mu * Z) n with hqdef
  set ρ := mvaRho mu Z n with hρdef
  have hu : 0 < 1 - ρ := by linarith
  unfold mvaW
  rw [← hqdef, div_le_div_iff₀ hmu (by positivity)]
  -- q * (mu * (1 - ρ)) ≤ ρ * mu  ⟸  q * (1 - ρ) ≤ ρ  ⟸  q ≤ ρ (1 + q) = Q (n+1)
  have key : q * (1 - ρ) ≤ ρ := by nlinarith [hmono, hlit]
  nlinarith [key, hmu]

/-- **A policy change at fixed population `N` moves the mean number at the
server by at most `N - L`.**  Any stationary mean `L'` of a closed system
of `N` sessions lies in `[0, N]`. -/
theorem closed_price_cap {N L L' : ℝ} (hL' : L' ≤ N) : L' - L ≤ N - L := by
  linarith

/-- The first row of the paper's finite-source table: `μ = 1`, `Z = 2` s,
two sessions (`n + 1 = 2`). `Q 1 = 1/3`, so the wait is `1/3` s, the
utilisation `ρ = 2/(c + 1 + Q 1) = 3/5`, and the open M/M/1 wait at that
utilisation is `3/2` s: 4.5 times the finite-source wait. -/
theorem finite_source_two_sessions_example :
    mvaW 1 2 1 = 1 / 3 ∧ mvaRho 1 2 1 = 3 / 5 ∧
      mvaRho 1 2 1 / (1 * (1 - mvaRho 1 2 1)) = 3 / 2 := by
  have h1 : mvaQ (1 * 2) 1 = 1 / 3 := by
    rw [mvaQ_succ, mvaQ_zero]; unfold mvaG; norm_num
  refine ⟨?_, ?_, ?_⟩
  · unfold mvaW; rw [h1]; norm_num
  · rw [mvaRho_eq (by norm_num) (by norm_num), h1]; norm_num
  · rw [mvaRho_eq (by norm_num) (by norm_num), h1]; norm_num

end ServingQueueTheory
