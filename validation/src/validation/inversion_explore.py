"""Print affinity vs always-move mean response by rate and link bandwidth.

uv run python -m validation.inversion_explore
"""

from .checks import INVERSION_BANDWIDTHS, INVERSION_RATES
from .fmt import fixed, sci_fixed
from .models import routing
from .models.routing import RoutePolicy, RoutingConfig


def main() -> None:
    head = f"{'rate':>5} {'affinity':>12}"
    head += "".join(f" {'move@' + sci_fixed(bw, 0):>12}" for bw in INVERSION_BANDWIDTHS)
    print(head + f" {'hotutil':>8} {'ctx':>8}")
    for r in INVERSION_RATES:
        a = routing.simulate(RoutingConfig.example(r, RoutePolicy.Affinity))
        line = f"{fixed(r, 1):>5} {fixed(a.response.mean, 3):>12}"
        for bw in INVERSION_BANDWIDTHS:
            cfg = RoutingConfig.example(r, RoutePolicy.LeastLoadedFetch)
            cfg.migrate_bandwidth = bw
            line += f" {fixed(routing.simulate(cfg).response.mean, 3):>12}"
        line += f" {fixed(a.utilization[0], 2):>8} {fixed(a.mean_context, 0):>8} E[S]={fixed(a.service.mean(), 3)}"
        print(line)


if __name__ == "__main__":
    main()
