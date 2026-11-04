"""Energy-harvesting packet scheduling: exact CVXPY and conservative LP solvers.

Convention: transmit from beginning-of-slot backlog, then arrivals/harvest occur;
no use of same-slot harvested energy. All quantities are continuous packet equivalents.
"""
from dataclasses import dataclass
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import lil_matrix

@dataclass(frozen=True)
class Config:
    buffer_max: float = 32.0
    energy_max: float = 12.0
    power_max: float = 3.0
    data_max: float = 10.0
    tau: float = 1.0
    slot_seconds: float = 5.0
    bandwidth_hz: float = 3000.0
    packet_bits: float = 1000.0
    noise_psd: float = 1e-9
    drop_weight: float = 35.0
    energy_weight: float = 0.15
    terminal_weight: float = 6.0
    horizon: int = 10
    segments: int = 12

    @property
    def rate_scale(self):
        return self.bandwidth_hz * self.tau / self.packet_bits


def capacity(power, gain, cfg):
    """gain = h / (N0 * B), the effective SNR per watt."""
    return cfg.rate_scale * np.log2(1 + np.asarray(gain) * np.asarray(power))


def _arrays(gain, arrival, harvest):
    g, l, H = map(lambda z: np.asarray(z, dtype=float), (gain, arrival, harvest))
    assert g.ndim == l.ndim == H.ndim == 1 and len(g) == len(l) == len(H)
    assert np.all(g >= 0) and np.all(l >= 0) and np.all(H >= 0)
    return g, l, H


def solve_cvxpy(b0, e0, gain, arrival, harvest, cfg=Config(), first_slot_drop_cap=None, solver_preference=None):
    """Exact convex model. Requires `pip install cvxpy clarabel` locally."""
    import cvxpy as cp
    g, l, H = _arrays(gain, arrival, harvest)
    n = len(g)
    p = cp.Variable(n, nonneg=True)
    d = cp.Variable(n, nonneg=True)
    b = cp.Variable(n + 1)
    E = cp.Variable(n + 1)
    o = cp.Variable(n, nonneg=True)
    w = cp.Variable(n, nonneg=True)
    cons = [b[0] == b0, E[0] == e0, b >= 0, b <= cfg.buffer_max,
            E >= 0, E <= cfg.energy_max, p <= cfg.power_max,
            d <= cfg.data_max, d <= b[:-1], o <= l,
            p * cfg.tau <= E[:-1],
            b[1:] == b[:-1] - d + l - o,
            E[1:] == E[:-1] - p * cfg.tau + H - w,
            d <= cfg.rate_scale * cp.log1p(cp.multiply(g, p)) / np.log(2)]
    if first_slot_drop_cap is not None:
        if not np.isfinite(first_slot_drop_cap) or first_slot_drop_cap < 0:
            raise ValueError('first_slot_drop_cap must be finite and nonnegative')
        cons.append(o[0] <= first_slot_drop_cap)
    objective = cp.Minimize(cp.sum(b[:-1]) + cfg.drop_weight * cp.sum(o)
                            + cfg.energy_weight * cfg.tau * cp.sum(p)
                            + cfg.terminal_weight * b[-1])
    prob = cp.Problem(objective, cons)
    assert prob.is_dcp(), 'Problem must satisfy DCP rules'
    # Try both solvers and independently check primal physical feasibility.
    # An 'optimal_inaccurate' status is NOT equivalent to certified optimality.
    attempts = []
    candidates = []
    
    
    # Try increasingly accurate numerical configurations.
    solver_settings = [
        ("CLARABEL", {
            "max_iter": 1000,
            "tol_gap_abs": 1e-8,
            "tol_feas": 1e-8,
        }),
        ("SCS", {
            "eps": 1e-5,
            "max_iters": 30000,
        }),
        ("SCS", {
            "eps": 1e-7,
            "max_iters": 100000,
            "acceleration_lookback": 0,
        }),
    ]

    if solver_preference is not None:
        if solver_preference not in ('CLARABEL', 'SCS'):
            raise ValueError('solver_preference must be CLARABEL, SCS, or None')
        solver_settings = [(solver, opts) for solver, opts in solver_settings if solver == solver_preference]

    for solver, options in solver_settings:

        if solver not in cp.installed_solvers():
            attempts.append(f"{solver}: not installed")
            continue

        try:
            prob.solve(
                solver=solver,
                verbose=False,
                **options
            )
            status = str(prob.status)

        except cp.error.SolverError as exc:
            attempts.append(f"{solver}: {exc}")
            continue

        if status not in ("optimal", "optimal_inaccurate"):
            attempts.append(
                f"{solver}: status={status}"
            )
            continue

        var_dict = {
            "p": p,
            "d": d,
            "b": b,
            "E": E,
            "o": o,
            "w": w,
        }

        if any(
            v.value is None
            or not np.all(np.isfinite(v.value))
            for v in var_dict.values()
        ):
            attempts.append(
                f"{solver}: missing/nonfinite variables"
            )
            continue

        result = {
            k: np.array(v.value, dtype=float, copy=True)
            for k, v in var_dict.items()
        }

        residuals = verify_plan(
            result, b0, e0, g, l, H, cfg
        )

        if first_slot_drop_cap is not None:
            residuals['first_slot_drop_cap'] = max(0., float(result['o'][0])-first_slot_drop_cap)
        violation = max(residuals.values())

        if not np.isfinite(violation) or violation > 1e-4:
            attempts.append(
                f"{solver}: status={status}, "
                f"max_violation={violation:.6g}, "
                f"residuals={residuals}"
            )
            continue

        result.update(
            objective=float(prob.value),
            status=status,
            solver=solver,
            max_violation=violation,
            backend="cvxpy-exact",
        )

        candidates.append(result)

        if status == "optimal":
            return result

    # Accept only a numerically feasible candidate.
    # An inaccurate status is retained for reporting.
    if candidates:
        return min(
            candidates,
            key=lambda z: z["max_violation"]
        )

    raise RuntimeError(
        "No feasible CVXPY solution:\n"
        + "\n".join(attempts)
    )



def solve_lp(b0, e0, gain, arrival, harvest, cfg=Config()):
    """Executed fallback: conservative *inner approximation* of Shannon capacity.

    Linear secants interpolate concave capacity from below. Taking their minimum
    produces a feasible piecewise-linear rate limit. `linprog(method='highs')`
    solves the resulting LP globally, NOT the original smooth convex program.
    """
    g, l, H = _arrays(gain, arrival, harvest)
    n = len(g)
    starts = {}
    ix = 0
    for key, num in [('p',n),('d',n),('b',n+1),('E',n+1),('o',n),('w',n)]:
        starts[key] = np.arange(ix, ix+num); ix += num
    m = ix
    c = np.zeros(m)
    c[starts['b'][:-1]] = 1
    c[starts['b'][-1]] = cfg.terminal_weight
    c[starts['o']] = cfg.drop_weight
    c[starts['p']] = cfg.energy_weight * cfg.tau
    bounds = [(0,None)]*m
    for t in range(n):
        bounds[int(starts['p'][t])] = (0,cfg.power_max)
        bounds[int(starts['d'][t])] = (0,cfg.data_max)
        bounds[int(starts['o'][t])] = (0,float(l[t]))
    for t in range(n+1):
        bounds[int(starts['b'][t])] = (0,cfg.buffer_max)
        bounds[int(starts['E'][t])] = (0,cfg.energy_max)
    eq_rows, eq_rhs, ub_rows, ub_rhs = [], [], [], []
    def eq(row, rhs): eq_rows.append(row); eq_rhs.append(rhs)
    def le(row, rhs): ub_rows.append(row); ub_rhs.append(rhs)
    eq({int(starts['b'][0]):1},b0)
    eq({int(starts['E'][0]):1},e0)
    x_points = np.linspace(0, cfg.power_max, cfg.segments+1)
    for t in range(n):
        p,d = int(starts['p'][t]),int(starts['d'][t])
        b, bn = int(starts['b'][t]),int(starts['b'][t+1])
        E,En = int(starts['E'][t]),int(starts['E'][t+1])
        o,w = int(starts['o'][t]),int(starts['w'][t])
        eq({bn:1,b:-1,d:1,o:1},float(l[t]))
        eq({En:1,E:-1,p:cfg.tau,w:1},float(H[t]))
        le({d:1,b:-1},0)
        le({p:cfg.tau,E:-1},0)
        y = capacity(x_points,g[t],cfg)
        for k in range(cfg.segments):
            slope=(y[k+1]-y[k])/(x_points[k+1]-x_points[k])
            intercept=y[k]-slope*x_points[k]
            le({d:1,p:-float(slope)},float(intercept))
    def matrix(rows):
        a=lil_matrix((len(rows),m), dtype=float)
        for i,row in enumerate(rows):
            for j,val in row.items():a[i,j]=val
        return a.tocsr()
    res=linprog(c, A_ub=matrix(ub_rows),b_ub=np.array(ub_rhs),
                A_eq=matrix(eq_rows),b_eq=np.array(eq_rhs),bounds=bounds, method='highs')
    if not res.success: raise RuntimeError(f'LP failed: {res.message}')
    result={k:res.x[idx] for k,idx in starts.items()}
    result.update(objective=float(res.fun),status='optimal',backend='scipy-conservative-LP')
    return result


def verify_plan(sol,b0,e0,gain,arrival,harvest,cfg=Config()):
    """Return worst *positive* violation, including exact physical capacity."""
    p,d,b,E,o,w = [np.asarray(sol[k]) for k in ('p','d','b','E','o','w')]
    g,l,H = _arrays(gain,arrival,harvest)
    residuals = {
        'queue_balance':np.max(np.abs(b[1:] - b[:-1]+d-l+o)),
        'energy_balance':np.max(np.abs(E[1:] - E[:-1]+cfg.tau*p-H+w)),
        'rate':np.max(d-capacity(p,g,cfg)),
        'data_availability':np.max(d-b[:-1]),
        'power_cap':np.max(p-cfg.power_max),
        'data_cap':np.max(d-cfg.data_max),
        'energy_causality':np.max(cfg.tau*p-E[:-1]),
        'buffer_cap':np.max(b-cfg.buffer_max),
        'battery_cap':np.max(E-cfg.energy_max),
        'drop_exceeds_arrivals':np.max(o-l),
        'nonnegativity':np.max(-np.concatenate((p,d,b,E,o,w))),
        'initial_b':abs(b[0]-b0), 'initial_E':abs(E[0]-e0)
    }
    return {k:float(max(0,v)) for k,v in residuals.items()}
