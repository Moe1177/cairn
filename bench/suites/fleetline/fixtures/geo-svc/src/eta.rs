/// Minutes to cover `km` at `kmh`, with a fixed pickup overhead.
pub fn eta_minutes(km: f64, kmh: f64) -> f64 {
    2.0 + km / kmh * 60.0
}
