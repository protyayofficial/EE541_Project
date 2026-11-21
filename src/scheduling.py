"""Energy-harvesting packet scheduling: exact CVXPY and conservative LP solvers.

Convention: transmit from beginning-of-slot backlog, then arrivals/harvest occur;
no use of same-slot harvested energy. Planning uses continuous attempted service
and expected successful service; simulation executes identifiable whole packets.
"""
from dataclasses import dataclass
from math import fsum
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import lil_matrix
from .channel import ChannelModel

INITIAL_QUEUE = 12
INITIAL_ENERGY = 7.0

@dataclass(frozen=True)
class Config:
    buffer_max: float = 32.0
    energy_max: float = 12.0
    power_max: float = 3.0
    data_max: float = 5.0
    tau: float = 1.0
    slot_seconds: float = 5.0
    bandwidth_hz: float = 3000.0
    packet_bits: float = 256.0
    bit_error_probability: float = 9.89e-6
    probe_seconds: float = 0.30
    channel_report_seconds: float = 0.30
    decision_seconds: float = 1.0
    ack_seconds: float = 1.0
    update_seconds: float = 1.0
    probe_energy: float = 0.2
    channel_report_energy: float = 0.0
    ack_energy: float = 0.0
    noise_psd: float = 1e-9
    drop_weight: float = 35.0
    energy_weight: float = 0.15
    terminal_weight: float = 6.0
    horizon: int = 10
    segments: int = 12
    channel_rho: float = .68
    channel_sigma: float = .45
    channel_mean_normalize: bool = True

    def __post_init__(self):
        self.channel_model  # Validate explicitly configured channel parameters.
        positive = (self.tau, self.slot_seconds, self.packet_bits, self.bandwidth_hz,
                    self.power_max, self.data_max, self.energy_max)
        controls = (self.probe_seconds, self.channel_report_seconds, self.ack_seconds,
                    self.decision_seconds, self.update_seconds,
                    self.probe_energy, self.channel_report_energy, self.ack_energy)
        if any(not np.isfinite(x) or x <= 0 for x in positive):
            raise ValueError('radio scales and limits must be finite and positive')
        if any(not np.isfinite(x) or x < 0 for x in controls):
            raise ValueError('control durations and energy must be finite and nonnegative')
        if not 0 <= self.bit_error_probability <= 1:
            raise ValueError('bit_error_probability must be in [0, 1]')
        if (not np.isfinite(self.buffer_max) or self.buffer_max < 0
                or self.buffer_max != int(self.buffer_max)):
            raise ValueError('buffer_max must be a nonnegative whole packet count')
        if any(not np.isfinite(x) or x < 0 for x in
               (self.drop_weight,self.energy_weight,self.terminal_weight,self.noise_psd)):
            raise ValueError('objective weights and noise_psd must be finite and nonnegative')
        if any(not np.isfinite(x) or x < 1 or x != int(x)
               for x in (self.horizon,self.segments)):
            raise ValueError('horizon and segments must be positive integers')
        if self.active_seconds > self.slot_seconds:
            raise ValueError('configured phases exceed scheduling interval')

    @property
    def channel_model(self):
        return ChannelModel(self.channel_rho,self.channel_sigma,self.channel_mean_normalize)

    @property
    def success_probability(self):
        return (1.0 - self.bit_error_probability) ** self.packet_bits

    @property
    def control_energy(self):
        return fsum((self.probe_energy, self.channel_report_energy, self.ack_energy))

    @property
    def control_seconds(self):
        return fsum((self.probe_seconds, self.channel_report_seconds, self.ack_seconds))

    @property
    def active_seconds(self):
        return fsum((self.probe_seconds, self.channel_report_seconds, self.decision_seconds,
                     self.tau, self.ack_seconds, self.update_seconds))

    @property
    def guard_seconds(self):
        return self.slot_seconds-self.active_seconds

    def phase_boundaries(self, start_s=0.0):
        """Reserved virtual windows, including A0 and inactive intervals.

        Times are seconds from simulation origin. No wall-clock waits occur.
        Durations do not imply additional energy consumption.
        """
        if not np.isfinite(start_s) or start_s < 0:
            raise ValueError('phase origin must be finite and nonnegative')
        result = dict(interval_start_s=float(start_s))
        durations = []
        for phase, duration in (('probe', self.probe_seconds),
                                ('channel_report', self.channel_report_seconds),
                                ('decision', self.decision_seconds), ('data', self.tau),
                                ('ack', self.ack_seconds), ('update', self.update_seconds),
                                ('guard', self.guard_seconds)):
            result[phase+'_start_s'] = fsum((start_s, *durations))
            durations.append(duration)
            result[phase+'_end_s'] = fsum((start_s, *durations))
        result['interval_end_s'] = result['guard_end_s'] = start_s+self.slot_seconds
        return result

    @property
    def rate_scale(self):
        return self.bandwidth_hz * self.tau / self.packet_bits


def capacity(power, gain, cfg):
    """gain = h / (N0 * B), the effective SNR per watt."""
    return cfg.rate_scale * np.log2(1 + np.asarray(gain) * np.asarray(power))


def control_budget(energy, cfg):
    """Execute affordable control stages in order; reserve ACK before data."""
    probe = energy >= cfg.probe_energy
    probe_cost = cfg.probe_energy if probe else 0.
    report = probe and energy >= fsum((cfg.probe_energy,cfg.channel_report_energy))
    report_cost = cfg.channel_report_energy if report else 0.
    ack = report and energy >= cfg.control_energy
    ack_cost = cfg.ack_energy if ack else 0.
    return dict(probe_executed=probe, report_available=report, exchange_available=ack,
                probe_energy=probe_cost, channel_report_energy=report_cost,
                ack_energy=ack_cost, other_control_energy=report_cost+ack_cost,
                control_energy=fsum((probe_cost,report_cost,ack_cost)),
                control_seconds=(cfg.probe_seconds if probe else 0.)
                +(cfg.channel_report_seconds if report else 0.)+(cfg.ack_seconds if ack else 0.))


def planned_control_offset(e0, n, cfg):
    """Partial first-slot controls are fixed costs; future full controls relax."""
    budget = control_budget(e0, cfg)
    first_exchange = float(budget['exchange_available'])
    offset = np.zeros(n)
    offset[0] = budget['control_energy']-cfg.control_energy*first_exchange
    return first_exchange, offset


def planned_energy(sol, e0, cfg):
    _, offset = planned_control_offset(e0, len(sol['p']), cfg)
    return cfg.tau*np.asarray(sol['p'])+cfg.control_energy*np.asarray(sol['u'])+offset


def validate_packet_inputs(arrivals, b0, cfg):
    """Actual counts must be integral; forecasts and planner states may be fluid."""
    for name, values in (("arrivals", arrivals), ("initial queue", b0),
                         ("buffer capacity", cfg.buffer_max)):
        values = np.asarray(values, dtype=float)
        if (not np.all(np.isfinite(values)) or np.any(values < 0)
                or np.any(values != np.floor(values))):
            raise ValueError(f"{name} must contain finite nonnegative whole packets")
    if b0 > cfg.buffer_max:
        raise ValueError("initial queue exceeds buffer capacity")


def execute_packets(recommended, power, queue, energy, gain, cfg, *, fixed_power=False):
    """Floor a continuous recommendation within actual physical limits.

    Fixed-power heuristics keep their selected power when sending. MPC and
    greedy use the minimum Shannon power for the executed whole packets.
    """
    power = float(np.clip(power, 0., min(cfg.power_max, energy / cfg.tau)))
    limit = max(0., min(recommended, queue, cfg.data_max,
                        float(capacity(power, gain, cfg))))
    packets = int(np.floor(limit))
    if packets == 0:
        return 0, 0.0
    required = float(np.expm1(np.log(2) * packets / cfg.rate_scale) / gain)
    # Protect the physical budget against inverse-rate roundoff, without
    # rounding a fractional recommendation upward.
    while packets and required > power:
        packets -= 1
        required = float(np.expm1(np.log(2) * packets / cfg.rate_scale) / gain)
    if packets == 0:
        return 0, 0.0
    return packets, power if fixed_power else required


def planner_action(sol,queue,energy,gain,cfg):
    """Normalize solver roundoff only, with an independent physical budget check.

    Generic execution still floors fractions. Conic solvers can return k-eps
    at an active integer bound, causing an unintended full packet loss per slot.
    """
    max_power=min(cfg.power_max,max(0.,energy)/cfg.tau)
    p=float(np.clip(sol['p'][0],0.,max_power))
    d=float(np.clip(sol['d'][0],0.,min(queue,cfg.data_max)))
    nearest=int(np.rint(d))
    tolerance=1e-6
    if gain>0 and 0<nearest<=min(queue,cfg.data_max) and abs(d-nearest)<=tolerance:
        required=float(np.expm1(np.log(2)*nearest/cfg.rate_scale)/gain)
        if (required<=max_power and required<=p+tolerance
                and (nearest>d or required>p or capacity(p,gain,cfg)<nearest)):
            # This is only an execution ceiling. execute_packets recomputes the
            # applied minimum power for the normalized whole-packet action.
            return float(nearest),max_power
    return d,p


def _arrays(gain, arrival, harvest):
    g, l, H = map(lambda z: np.asarray(z, dtype=float), (gain, arrival, harvest))
    if not (g.ndim == l.ndim == H.ndim == 1 and len(g) == len(l) == len(H) and len(g)>0):
        raise ValueError('planning inputs must be nonempty one-dimensional arrays of equal length')
    if any(not np.all(np.isfinite(x)) or np.any(x<0) for x in (g,l,H)):
        raise ValueError('planning inputs must be finite and nonnegative')
    return g, l, H


def solve_cvxpy(b0, e0, gain, arrival, harvest, cfg=Config(), first_slot_drop_cap=None, solver_preference=None):
    """Convex expected-goodput model with relaxed future control activation."""
    import cvxpy as cp
    g, l, H = _arrays(gain, arrival, harvest)
    n = len(g)
    p = cp.Variable(n, nonneg=True)
    d = cp.Variable(n, nonneg=True)
    b = cp.Variable(n + 1)
    E = cp.Variable(n + 1)
    o = cp.Variable(n, nonneg=True)
    w = cp.Variable(n, nonneg=True)
    u = cp.Variable(n, nonneg=True)
    # Future exchanges use a continuous activation relaxation. The first
    # exchange is fixed to the actual beginning-slot affordability decision.
    first_exchange, offset = planned_control_offset(e0, n, cfg)
    spent = p * cfg.tau + cfg.control_energy * u + offset
    cons = [b[0] == b0, E[0] == e0, b >= 0, b <= cfg.buffer_max,
            E >= 0, E <= cfg.energy_max, u <= 1, u[0] == first_exchange,
            p <= cfg.power_max * u, d <= cfg.data_max * u,
            d <= b[:-1], o <= l, spent <= E[:-1],
            b[1:] == b[:-1] - cfg.success_probability * d + l - o,
            E[1:] == E[:-1] - spent + H - w,
            d <= cfg.rate_scale * cp.log1p(cp.multiply(g, p)) / np.log(2)]
    if first_slot_drop_cap is not None:
        if not np.isfinite(first_slot_drop_cap) or first_slot_drop_cap < 0:
            raise ValueError('first_slot_drop_cap must be finite and nonnegative')
        cons.append(o[0] <= first_slot_drop_cap)
    cost = (cp.sum(b[:-1]) + cfg.drop_weight * cp.sum(o)
            + cfg.energy_weight * cp.sum(spent) + cfg.terminal_weight * b[-1])
    # Positive constant normalization preserves the minimizers and constraints.
    # Large rejection/energy weights otherwise destabilize conic dual scaling.
    # Always report the original model objective, not the solver's scaled cost.
    objective_scale = max(1., cfg.drop_weight, cfg.energy_weight, cfg.terminal_weight)
    objective = cp.Minimize(cost / objective_scale)
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
            "u": u,
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
            objective=float(cost.value),
            objective_scale=objective_scale,
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
    for key, num in [('p',n),('d',n),('b',n+1),('E',n+1),('o',n),('w',n),('u',n)]:
        starts[key] = np.arange(ix, ix+num); ix += num
    m = ix
    c = np.zeros(m)
    c[starts['b'][:-1]] = 1
    c[starts['b'][-1]] = cfg.terminal_weight
    c[starts['o']] = cfg.drop_weight
    c[starts['p']] = cfg.energy_weight * cfg.tau
    c[starts['u']] = cfg.energy_weight * cfg.control_energy
    bounds = [(0,None)]*m
    for t in range(n):
        bounds[int(starts['p'][t])] = (0,cfg.power_max)
        bounds[int(starts['d'][t])] = (0,cfg.data_max)
        bounds[int(starts['o'][t])] = (0,float(l[t]))
        bounds[int(starts['u'][t])] = (0,1)
    first_exchange, offset = planned_control_offset(e0, n, cfg)
    bounds[int(starts['u'][0])] = (first_exchange, first_exchange)
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
        u = int(starts['u'][t])
        eq({bn:1,b:-1,d:cfg.success_probability,o:1},float(l[t]))
        eq({En:1,E:-1,p:cfg.tau,u:cfg.control_energy,w:1},float(H[t]-offset[t]))
        le({d:1,b:-1},0)
        le({p:cfg.tau,u:cfg.control_energy,E:-1},-offset[t])
        le({p:1,u:-cfg.power_max},0)
        le({d:1,u:-cfg.data_max},0)
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
    result.update(objective=float(res.fun+cfg.energy_weight*offset.sum()),status='optimal',backend='scipy-conservative-LP')
    return result


def verify_plan(sol,b0,e0,gain,arrival,harvest,cfg=Config()):
    """Check expected queue dynamics, control relaxation and Shannon capacity."""
    if not np.all(np.isfinite([b0,e0])):
        raise ValueError('initial planning state must be finite')
    p,d,b,E,o,w = [np.asarray(sol[k]) for k in ('p','d','b','E','o','w')]
    g,l,H = _arrays(gain,arrival,harvest)
    u = np.asarray(sol['u'])
    n=len(g)
    for name,x,length in zip(('p','d','b','E','o','w','u'),(p,d,b,E,o,w,u),
                             (n,n,n+1,n+1,n,n,n)):
        if x.shape != (length,) or not np.all(np.isfinite(x)):
            raise ValueError(f'plan {name} has invalid shape or nonfinite values')
    spent = planned_energy(sol,e0,cfg)
    residuals = {
        'queue_balance':np.max(np.abs(b[1:] - b[:-1]+cfg.success_probability*d-l+o)),
        'energy_balance':np.max(np.abs(E[1:] - E[:-1]+spent-H+w)),
        'rate':np.max(d-capacity(p,g,cfg)),
        'data_availability':np.max(d-b[:-1]),
        'power_cap':np.max(p-cfg.power_max),
        'data_cap':np.max(d-cfg.data_max),
        'energy_causality':np.max(spent-E[:-1]),
        'exchange_cap':np.max(u-1),
        'exchange_power':np.max(p-cfg.power_max*u),
        'exchange_data':np.max(d-cfg.data_max*u),
        'first_exchange':abs(u[0]-planned_control_offset(e0,len(p),cfg)[0]),
        'buffer_cap':np.max(b-cfg.buffer_max),
        'battery_cap':np.max(E-cfg.energy_max),
        'drop_exceeds_arrivals':np.max(o-l),
        'nonnegativity':np.max(-np.concatenate((p,d,b,E,o,w,u))),
        'initial_b':abs(b[0]-b0), 'initial_E':abs(E[0]-e0)
    }
    return {k:float(max(0,v)) for k,v in residuals.items()}
