"""
UPIN swarm consensus and formation control.
AIMCRS Intelligence Private Limited / Abheet Prem Manghnani

Scalable (50+ nodes) multi-agent control built from published results:
  Olfati-Saber and Murray 2004 (consensus, Laplacian, delay bound)
  Olfati-Saber 2006 (flocking, bump function)
  Ren and Atkins 2007 (second-order consensus)
  Krick, Broucke and Francis 2009 (distance-based formation, rigidity)
  Ames et al. 2017 (control barrier functions)
  Bertsekas 1988 / Zavlanos et al. 2008 (distributed auction assignment)
  Olfati-Saber 2007 (Kalman consensus filter)
  Dimarogonas et al. 2012 (event-triggered consensus)
  Cortes et al. 2004 (Voronoi coverage)

Pure numpy and scipy. No ROS dependency. Every per-node cost is
O(neighbours). All sources are from memory and must be verified before
citation in any external document.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

import numpy as np
from scipy.spatial import cKDTree
from scipy.sparse import csr_matrix, diags
from scipy.sparse.linalg import eigsh


# ---------------------------------------------------------------------
# 1. Graph layer
# ---------------------------------------------------------------------

def bump(z: np.ndarray, h: float = 0.2) -> np.ndarray:
    """Smooth bump function, Olfati-Saber 2006 eq. 10. z in [0,1]."""
    out = np.zeros_like(z)
    a = z < h
    out[a] = 1.0
    b = (z >= h) & (z <= 1.0)
    out[b] = 0.5 * (1.0 + np.cos(np.pi * (z[b] - h) / (1.0 - h)))
    return out


def build_adjacency(pos: np.ndarray, r: float, k_max: int = 7,
                    smooth: bool = True) -> csr_matrix:
    """r-disk adjacency capped at k_max nearest neighbours (Ballerini 2008
    topological interaction). KD-tree lookup, O(N log N) globally."""
    n = len(pos)
    tree = cKDTree(pos)
    k = min(k_max + 1, n)
    d, idx = tree.query(pos, k=k)
    rows, cols, vals = [], [], []
    for i in range(n):
        for dd, j in zip(d[i][1:], idx[i][1:]):
            if j == i or j >= n or dd >= r:
                continue
            w = float(bump(np.array([dd / r]))[0]) if smooth else 1.0
            if w > 0:
                rows.append(i); cols.append(j); vals.append(w)
    A = csr_matrix((vals, (rows, cols)), shape=(n, n))
    A = A.maximum(A.T)          # force undirected
    return A


def laplacian(A: csr_matrix) -> csr_matrix:
    deg = np.asarray(A.sum(axis=1)).ravel()
    return diags(deg) - A


def algebraic_connectivity(L: csr_matrix) -> float:
    """lambda_2 of L. > 0 means connected. Sparse eigensolver."""
    n = L.shape[0]
    if n < 3:
        return 0.0
    try:
        vals = eigsh(L.asfptype(), k=2, which="SM", return_eigenvectors=False)
        return float(np.sort(vals)[1])
    except Exception:
        vals = np.linalg.eigvalsh(L.toarray())
        return float(np.sort(vals)[1])


def delay_bound(L: csr_matrix) -> float:
    """Max tolerable uniform delay, Olfati-Saber and Murray 2004 Thm 10:
    tau < pi / (2 * lambda_max(L))."""
    lam_max = float(eigsh(L.asfptype(), k=1, which="LA",
                          return_eigenvectors=False)[0])
    return np.pi / (2.0 * lam_max) if lam_max > 0 else np.inf


# ---------------------------------------------------------------------
# 2. First-order consensus (baseline)
# ---------------------------------------------------------------------

def consensus_first_order(x: np.ndarray, L: csr_matrix, dt: float) -> np.ndarray:
    """x_dot = -L x, explicit Euler. Use for slow scalar variables."""
    return x - dt * (L @ x)


# ---------------------------------------------------------------------
# 3. Second-order consensus with formation and saturation
# ---------------------------------------------------------------------

@dataclass
class Gains:
    k_p: float = 1.0       # formation position gain
    k_v: float = 2.0       # velocity consensus gain
    k_d: float = 0.5       # absolute velocity damping
    k_s: float = 4.0       # soft separation gain
    k_l: float = 1.0       # pinning gain toward virtual leader
    k_lv: float = 1.5      # velocity feedforward gain for moving slots
    r_s: float = 2.0       # soft separation radius (m)
    r_min: float = 1.0     # hard CBF minimum distance (m)
    gamma: float = 2.0     # CBF class-K rate
    v_max: float = 5.0     # m/s
    a_max: float = 3.0     # m/s^2


def second_order_control(p: np.ndarray, v: np.ndarray, A: csr_matrix,
                         delta: np.ndarray, g: Gains,
                         leader: Optional[np.ndarray] = None,
                         pinned: Optional[np.ndarray] = None,
                         delta_dot: Optional[np.ndarray] = None,
                         delta_ddot: Optional[np.ndarray] = None) -> np.ndarray:
    """u_i = -sum_j a_ij [k_p((p_i-p_j)-(d_i-d_j)) + k_v(v_i-v_j)] - k_d v_i
    plus soft separation and optional pinning to a virtual leader.
    Ren and Atkins 2007. Undirected graph: any positive gains converge."""
    n, dim = p.shape
    A = A.tocsr()
    u = np.zeros_like(p)
    for i in range(n):
        js = A.indices[A.indptr[i]:A.indptr[i + 1]]
        ws = A.data[A.indptr[i]:A.indptr[i + 1]]
        if len(js) == 0:
            u[i] = -g.k_d * v[i]
            continue
        dp = (p[i] - p[js]) - (delta[i] - delta[js])       # formation error
        dv = v[i] - v[js]
        if delta_dot is not None:
            dv = dv - (delta_dot[i] - delta_dot[js])   # rotating shapes have real relative velocity
        u[i] = -(ws[:, None] * (g.k_p * dp + g.k_v * dv)).sum(axis=0)
        # soft separation
        rel = p[i] - p[js]
        d = np.linalg.norm(rel, axis=1) + 1e-9
        close = d < g.r_s
        if close.any():
            u[i] += (g.k_s * (g.r_s - d[close])[:, None] * rel[close] / d[close][:, None]).sum(axis=0)
    # damping is relative to the slot velocity when the shape moves
    u -= g.k_d * (v if delta_dot is None else (v - delta_dot))
    if leader is not None and pinned is not None:
        u[pinned] += -g.k_l * ((p[pinned] - delta[pinned]) - leader)
    if delta_dot is not None:
        # feedforward: track the slot velocity of a moving or rotating shape
        u += -g.k_lv * (v - delta_dot)
    if delta_ddot is not None:
        u += delta_ddot          # acceleration feedforward (centripetal etc.)
    return u


def saturate(x: np.ndarray, limit: float) -> np.ndarray:
    nrm = np.linalg.norm(x, axis=1, keepdims=True) + 1e-12
    return x * np.minimum(1.0, limit / nrm)


# ---------------------------------------------------------------------
# 4. Control barrier function safety filter
# ---------------------------------------------------------------------

def cbf_filter(p: np.ndarray, v: np.ndarray, u_nom: np.ndarray,
               A: csr_matrix, g: Gains, radius: Optional[float] = None) -> np.ndarray:
    """Pairwise CBF h_ij = d_ij^2 - r_min^2 on double-integrator dynamics.
    Enforces h_ddot + 2*gamma*h_dot + gamma^2*h >= 0 per neighbour by
    sequential projection of u_i onto each half-space (k constraints per
    node, O(k)). Exact for one active constraint, conservative for many.
    Ames et al. 2017; Wang, Ames, Egerstedt 2017."""
    rmin = (radius or g.r_min) * 1.15     # margin for sequential projection
    n = len(p)
    u = u_nom.copy()
    tree = cKDTree(p)
    pairs = tree.query_pairs(r=3.0 * rmin)
    nbrs: Dict[int, list] = {i: [] for i in range(n)}
    for i, j in pairs:
        nbrs[i].append(j); nbrs[j].append(i)
    for i in range(n):
        for _ in range(6):                       # repeated projection, converges for convex set
            for j in nbrs[i]:
                rel = p[i] - p[j]
                relv = v[i] - v[j]
                h = rel @ rel - rmin ** 2
                hd = 2.0 * rel @ relv
                # h_ddot = 2*relv.relv + 2*rel.(u_i - u_j); treat u_j as fixed
                a_coef = 2.0 * rel
                rhs = -(2.0 * relv @ relv + 2.0 * rel @ (-u[j])
                        + 2.0 * g.gamma * hd + g.gamma ** 2 * h)
                # constraint a_coef . u_i >= rhs
                viol = rhs - a_coef @ u[i]
                if viol > 0:
                    u[i] += viol * a_coef / (a_coef @ a_coef + 1e-12)
    return saturate(u, g.a_max)


# ---------------------------------------------------------------------
# 5. Formation shapes, 3D rotation, rigidity
# ---------------------------------------------------------------------

def shape_ring(n: int, radius: float, z: float = 0.0) -> np.ndarray:
    th = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.stack([radius * np.cos(th), radius * np.sin(th), np.full(n, z)], axis=1)


def shape_sphere(n: int, radius: float) -> np.ndarray:
    """Fibonacci sphere, even spacing for any n."""
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * i / n)
    th = np.pi * (1 + 5 ** 0.5) * i
    return radius * np.stack([np.cos(th) * np.sin(phi), np.sin(th) * np.sin(phi), np.cos(phi)], axis=1)


def shape_grid(n: int, spacing: float) -> np.ndarray:
    side = int(np.ceil(np.sqrt(n)))
    pts = [(i * spacing, j * spacing, 0.0) for i in range(side) for j in range(side)]
    pts = np.array(pts[:n])
    return pts - pts.mean(axis=0)


def shape_v(n: int, spacing: float, angle_deg: float = 30.0) -> np.ndarray:
    a = np.deg2rad(angle_deg)
    pts = [(0.0, 0.0, 0.0)]
    for k in range(1, n):
        side = -1 if k % 2 else 1
        m = (k + 1) // 2
        pts.append((-m * spacing * np.cos(a), side * m * spacing * np.sin(a), 0.0))
    return np.array(pts) - np.mean(pts, axis=0)


def rotation_matrix(axis: np.ndarray, angle: float) -> np.ndarray:
    """Rodrigues formula, R in SO(3)."""
    k = axis / (np.linalg.norm(axis) + 1e-12)
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * K @ K


def rotate_shape(delta: np.ndarray, axis: np.ndarray, omega: float, t: float) -> np.ndarray:
    """delta(t) = R(omega t) delta, the card's x_i*(t) = c(t) + R(wt) delta_i."""
    return delta @ rotation_matrix(axis, omega * t).T


def rigidity_matrix(p: np.ndarray, edges: np.ndarray) -> np.ndarray:
    n, dim = p.shape
    R = np.zeros((len(edges), n * dim))
    for e, (i, j) in enumerate(edges):
        d = p[i] - p[j]
        R[e, i * dim:(i + 1) * dim] = d
        R[e, j * dim:(j + 1) * dim] = -d
    return R


def is_infinitesimally_rigid(p: np.ndarray, edges: np.ndarray) -> bool:
    """rank(R) = d*n - d(d+1)/2 (Asimow and Roth). Needed for distance-only
    formation control to have a unique shape up to rigid motion."""
    n, dim = p.shape
    return np.linalg.matrix_rank(rigidity_matrix(p, edges)) == dim * n - dim * (dim + 1) // 2


def distance_formation_control(p: np.ndarray, edges: np.ndarray,
                               d_star: np.ndarray, k: float = 0.5) -> np.ndarray:
    """Gradient law u_i = -k sum_j (d_ij^2 - d_ij*^2)(p_i - p_j).
    Krick, Broucke, Francis 2009. Works from UWB ranges, no shared frame."""
    u = np.zeros_like(p)
    for (i, j), ds in zip(edges, d_star):
        rel = p[i] - p[j]
        err = rel @ rel - ds ** 2
        u[i] -= k * err * rel
        u[j] += k * err * rel
    return u


# ---------------------------------------------------------------------
# 6. Distributed auction slot assignment
# ---------------------------------------------------------------------

def auction_assignment(p: np.ndarray, slots: np.ndarray, eps: float = 0.01,
                       max_iter: int = 10000) -> np.ndarray:
    """Bertsekas auction. Returns slot index per node. Local bidding on
    cost ||p_i - slot||; ties broken by node id. Converges in
    O(N * max_cost / eps) rounds. Distributed version passes bids over
    the mesh; this reference implementation runs the same rounds centrally
    for testing."""
    n, m = len(p), len(slots)
    assert m >= n, "need at least as many slots as nodes"
    cost = np.linalg.norm(p[:, None, :] - slots[None, :, :], axis=2)
    value = -cost                                     # maximise value
    price = np.zeros(m)
    owner = -np.ones(m, dtype=int)
    assign = -np.ones(n, dtype=int)
    unassigned = list(range(n))
    it = 0
    while unassigned and it < max_iter:
        it += 1
        i = unassigned.pop(0)
        net = value[i] - price
        best = int(np.argmax(net))
        net_sorted = np.sort(net)
        second = net_sorted[-2] if m > 1 else net_sorted[-1]
        bid = net[best] - second + eps
        price[best] += bid
        prev = owner[best]
        owner[best] = i
        assign[i] = best
        if prev >= 0:
            assign[prev] = -1
            unassigned.append(int(prev))
    return assign


def reassign_after_loss(p: np.ndarray, alive: np.ndarray,
                        shape_fn: Callable[[int], np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Lose one, keep flying: rebuild the shape for the live count and
    re-auction slots among survivors."""
    live_idx = np.where(alive)[0]
    delta = shape_fn(len(live_idx))
    assign = auction_assignment(p[live_idx], delta)
    full = np.zeros_like(p)
    full[live_idx] = delta[assign]
    return full, live_idx


# ---------------------------------------------------------------------
# 7. Kalman consensus filter on position
# ---------------------------------------------------------------------

@dataclass
class KCFState:
    x_hat: np.ndarray        # (n, dim) local estimates
    P: np.ndarray            # (n,) scalar covariance per node (isotropic)


def kalman_consensus_step(st: KCFState, meas: np.ndarray, R: np.ndarray,
                          A: csr_matrix, eps: float = 0.3) -> KCFState:
    """Olfati-Saber 2007 KCF, scalar-covariance form. Each node fuses its
    own measurement, then pulls toward neighbours weighted by their
    confidence. Independent errors average out across the swarm."""
    n = len(st.x_hat)
    A = A.tocsr()
    x_new = st.x_hat.copy()
    P_new = st.P.copy()
    for i in range(n):
        K = st.P[i] / (st.P[i] + R[i])
        x_loc = st.x_hat[i] + K * (meas[i] - st.x_hat[i])
        P_loc = (1 - K) * st.P[i]
        js = A.indices[A.indptr[i]:A.indptr[i + 1]]
        if len(js):
            w = 1.0 / (st.P[js] + 1e-9)
            w = w / (w.sum() + 1e-9)
            cons = (w[:, None] * (st.x_hat[js] - x_loc)).sum(axis=0)
            x_loc = x_loc + eps * cons
            P_loc = P_loc * (1.0 - eps * 0.5)
        x_new[i] = x_loc
        P_new[i] = max(P_loc, 1e-4)
    return KCFState(x_new, P_new)


def mahalanobis_gate(st: KCFState, A: csr_matrix, thresh: float = 3.0) -> np.ndarray:
    """Flag nodes whose estimate disagrees with the neighbourhood mean by
    more than thresh sigma. Reuses the UPIN MahalanobisDetector idea."""
    n = len(st.x_hat)
    A = A.tocsr()
    flags = np.zeros(n, dtype=bool)
    for i in range(n):
        js = A.indices[A.indptr[i]:A.indptr[i + 1]]
        if len(js) < 2:
            continue
        mu = st.x_hat[js].mean(axis=0)
        sig = np.sqrt(st.P[js].mean()) + 1e-6
        flags[i] = np.linalg.norm(st.x_hat[i] - mu) / sig > thresh
    return flags


# ---------------------------------------------------------------------
# 8. Event-triggered broadcast
# ---------------------------------------------------------------------

def event_trigger(x: np.ndarray, x_last_sent: np.ndarray, threshold: float) -> np.ndarray:
    """Dimarogonas et al. 2012. Send only when the state moved enough."""
    return np.linalg.norm(x - x_last_sent, axis=1) > threshold


# ---------------------------------------------------------------------
# 9. Voronoi coverage (Lloyd)
# ---------------------------------------------------------------------

def lloyd_step(p: np.ndarray, samples: np.ndarray, density: np.ndarray,
               k: float = 0.5) -> np.ndarray:
    """Move each node toward the weighted centroid of its Voronoi cell,
    approximated on a sample cloud. Cortes et al. 2004."""
    tree = cKDTree(p)
    _, owner = tree.query(samples)
    u = np.zeros_like(p)
    for i in range(len(p)):
        m = owner == i
        if m.any():
            w = density[m]
            cen = (w[:, None] * samples[m]).sum(axis=0) / (w.sum() + 1e-9)
            u[i] = k * (cen - p[i])
    return u


# ---------------------------------------------------------------------
# 10. Swarm state and one full step
# ---------------------------------------------------------------------

@dataclass
class SwarmState:
    p: np.ndarray
    v: np.ndarray
    delta: np.ndarray
    alive: np.ndarray
    gains: Gains = field(default_factory=Gains)
    t: float = 0.0
    lambda2: float = 0.0
    cbf_activations: int = 0
    delta_dot: Optional[np.ndarray] = None   # slot velocities for moving shapes
    delta_ddot: Optional[np.ndarray] = None  # slot accelerations (feedforward)


def swarm_step(st: SwarmState, dt: float, r_sense: float, k_max: int = 7,
               leader: Optional[np.ndarray] = None,
               link_loss: float = 0.0, rng: Optional[np.random.Generator] = None) -> SwarmState:
    """One control cycle for the live nodes. O(N log N) total, O(k) per node."""
    live = np.where(st.alive)[0]
    p, v, d = st.p[live], st.v[live], st.delta[live]
    A = build_adjacency(p, r_sense, k_max)
    if link_loss > 0 and rng is not None:
        A = A.tocoo()
        keep = rng.random(len(A.data)) > link_loss
        A = csr_matrix((A.data[keep], (A.row[keep], A.col[keep])), shape=A.shape)
        A = A.maximum(A.T)
    L = laplacian(A)
    st.lambda2 = algebraic_connectivity(L)
    pinned = np.arange(len(live)) if leader is not None else None
    dd = st.delta_dot[live] if st.delta_dot is not None else None
    ddd = st.delta_ddot[live] if st.delta_ddot is not None else None
    u = second_order_control(p, v, A, d, st.gains, leader, pinned, dd, ddd)
    u = saturate(u, st.gains.a_max)
    u_safe = cbf_filter(p, v, u, A, st.gains)
    st.cbf_activations += int((np.linalg.norm(u_safe - u, axis=1) > 1e-6).sum())
    v = saturate(v + dt * u_safe, st.gains.v_max)
    p = p + dt * v
    st.p[live], st.v[live] = p, v
    st.t += dt
    return st
