//! Print affinity vs lookahead mean response by rate and link bandwidth.
use libqueuingsim::models::routing::{self, RoutePolicy, RoutingConfig};
use libqueuingsim::validation::{INVERSION_BANDWIDTHS, INVERSION_RATES};
fn main() {
    print!("{:>5}", "rate");
    print!(" {:>12}", "affinity");
    for bw in INVERSION_BANDWIDTHS {
        print!(" {:>12}", format!("move@{bw:.0e}"));
    }
    println!(" {:>8} {:>8}", "hotutil", "ctx");
    for r in INVERSION_RATES {
        let a = routing::simulate(&RoutingConfig::example(r, RoutePolicy::Affinity));
        print!("{r:>5.1} {:>12.3}", a.response.mean);
        for bw in INVERSION_BANDWIDTHS {
            let mut cfg = RoutingConfig::example(r, RoutePolicy::LeastLoadedFetch);
            cfg.migrate_bandwidth = bw;
            let l = routing::simulate(&cfg);
            print!(" {:>12.3}", l.response.mean);
        }
        println!(
            " {:>8.2} {:>8.0} E[S]={:.3}",
            a.utilization[0],
            a.mean_context,
            a.service.mean()
        );
    }
}
