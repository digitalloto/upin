"""Tests for upin/swarm/consensus.py. Run: python test_swarm_consensus.py"""
import time
import sys; sys.path.insert(0, ".")
import numpy as np
from upin.swarm.consensus import (
    build_adjacency, laplacian, algebraic_connectivity, delay_bound,
    consensus_first_order, Gains, SwarmState, swarm_step,
    shape_ring, shape_sphere, rotate_shape, reassign_after_loss,
    auction_assignment, is_infinitesimally_rigid, distance_formation_control,
    KCFState, kalman_consensus_step, mahalanobis_gate, cbf_filter, event_trigger,
)

rng = np.random.default_rng(7)
N = 60


def min_pair_dist(p):
    from scipy.spatial import cKDTree
    d, _ = cKDTree(p).query(p, k=2)
    return d[:, 1].min()


def test_first_order_bound():
    p = rng.uniform(-10, 10, (N, 3))
    A = build_adjacency(p, r=12.0, k_max=8, smooth=False)
    L = laplacian(A)
    lam2 = algebraic_connectivity(L)
    assert lam2 > 0, "graph must be connected"
    x = rng.uniform(-5, 5, (N, 1))
    xbar = x.mean()
    e0 = np.linalg.norm(x - xbar)
    dt = 0.01
    for k in range(1, 301):
        x = consensus_first_order(x, L, dt)
        e = np.linalg.norm(x - xbar)
        bound = np.exp(-lam2 * k * dt) * e0
        assert e <= bound * 1.05 + 1e-9, f"step {k}: {e:.4f} > bound {bound:.4f}"
    print(f"[ok] first-order consensus, lambda2={lam2:.3f}, final err={e:.2e}")


def test_ring_formation_and_rotation():
    p = rng.uniform(-15, 15, (N, 3))
    v = np.zeros_like(p)
    delta0 = shape_ring(N, radius=12.0)
    assign = auction_assignment(p, delta0)
    delta = delta0[assign]
    st = SwarmState(p=p, v=v, delta=delta, alive=np.ones(N, bool),
                    gains=Gains(k_p=1.5, k_v=2.5, r_min=0.8, r_s=1.5))
    c = np.zeros(3)
    for _ in range(1200):
        st = swarm_step(st, 0.02, r_sense=40.0, k_max=8, leader=c)
    err = np.linalg.norm((st.p - st.delta) - c, axis=1).max()
    assert err < 0.1, f"formation error {err:.3f}"
    # rotate the shape about z for 3 s
    axis = np.array([0, 0, 1.0])
    dt, w = 0.02, 0.3
    for k in range(600):
        d0 = rotate_shape(delta, axis, w, k * dt)
        d1 = rotate_shape(delta, axis, w, (k + 1) * dt)
        d2 = rotate_shape(delta, axis, w, (k + 2) * dt)
        st.delta = d0
        st.delta_dot = (d1 - d0) / dt
        st.delta_ddot = (d2 - 2 * d1 + d0) / dt ** 2
        st = swarm_step(st, dt, r_sense=40.0, k_max=8, leader=c)
    err = np.linalg.norm((st.p - st.delta) - c, axis=1).max()
    assert err < 0.3, f"rotation tracking error {err:.3f}"
    print(f"[ok] 60-node ring formed and rotated, tracking err={err:.3f} m, "
          f"lambda2={st.lambda2:.2f}, cbf hits={st.cbf_activations}")


def test_lose_ten_keep_flying():
    p = rng.uniform(-15, 15, (N, 3))
    st = SwarmState(p=p, v=np.zeros_like(p), delta=np.zeros_like(p),
                    alive=np.ones(N, bool), gains=Gains(k_p=1.5, k_v=2.5))
    st.delta, _ = reassign_after_loss(st.p, st.alive, lambda n: shape_sphere(n, 10.0))
    c = np.zeros(3)
    for _ in range(800):
        st = swarm_step(st, 0.02, r_sense=40.0, k_max=8, leader=c)
    st.alive[rng.choice(N, 10, replace=False)] = False
    st.delta, live = reassign_after_loss(st.p, st.alive, lambda n: shape_sphere(n, 10.0))
    for _ in range(800):
        st = swarm_step(st, 0.02, r_sense=40.0, k_max=8, leader=c)
    assert st.lambda2 > 0
    err = np.linalg.norm((st.p[live] - st.delta[live]) - c, axis=1).max()
    assert err < 0.2, f"post-loss formation error {err:.3f}"
    print(f"[ok] lost 10 of 60, lambda2={st.lambda2:.2f}, re-formed sphere err={err:.3f} m")


def test_link_loss():
    p = rng.uniform(-10, 10, (N, 3))
    st = SwarmState(p=p, v=np.zeros_like(p), delta=shape_ring(N, 15.0),
                    alive=np.ones(N, bool), gains=Gains(k_p=1.5, k_v=2.5, r_s=1.0, r_min=0.6))
    for _ in range(1500):
        st = swarm_step(st, 0.02, r_sense=40.0, k_max=8, leader=np.zeros(3),
                        link_loss=0.3, rng=rng)
    err = np.linalg.norm(st.p - st.delta, axis=1).max()
    assert err < 0.3, f"error under 30% link loss {err:.3f}"
    print(f"[ok] 30% random link loss per step, formation err={err:.3f} m")


def test_cbf_never_violates():
    g = Gains(r_min=1.0, r_s=1.5, a_max=4.0, v_max=4.0)
    p = rng.uniform(-3, 3, (N, 3))          # deliberately crowded
    v = rng.normal(0, 1.0, (N, 3))
    delta = shape_ring(N, 8.0)
    st = SwarmState(p=p, v=v, delta=delta, alive=np.ones(N, bool), gains=g)
    # first let the filter push them apart, then track the minimum
    min_after = np.inf
    for k in range(1500):
        st = swarm_step(st, 0.01, r_sense=40.0, k_max=8, leader=np.zeros(3))
        if k > 300:
            min_after = min(min_after, min_pair_dist(st.p))
    assert min_after >= 0.9 * g.r_min, f"min distance {min_after:.3f} < r_min"
    print(f"[ok] CBF: min pairwise distance after settling = {min_after:.3f} m (r_min={g.r_min})")


def test_kalman_consensus():
    truth = np.array([100.0, 50.0, 20.0])
    noise_std = 5.0
    p = truth + rng.normal(0, 3.0, (N, 3))         # nodes spread around truth
    A = build_adjacency(p, r=15.0, k_max=8)
    st = KCFState(x_hat=p.copy(), P=np.full(N, noise_std ** 2))
    R = np.full(N, noise_std ** 2)
    for _ in range(60):
        meas = truth + rng.normal(0, noise_std, (N, 3))
        st = kalman_consensus_step(st, meas, R, A)
    err = np.linalg.norm(st.x_hat - truth, axis=1)
    assert err.mean() < 1.0, f"mean consensus error {err.mean():.3f}"
    # inject a spoofed node
    st.x_hat[0] += np.array([80.0, 0, 0])
    flags = mahalanobis_gate(st, A)
    assert flags[0], "spoofed node not flagged"
    print(f"[ok] Kalman consensus: individual noise {noise_std} m, "
          f"swarm error {err.mean():.2f} m mean, {err.max():.2f} m max; spoof flagged")


def test_rigidity_and_distance_formation():
    tri = np.array([[0, 0, 0], [1, 0, 0], [0.5, 0.87, 0], [0.5, 0.29, 0.8]], float)
    edges = np.array([(0, 1), (0, 2), (1, 2), (0, 3), (1, 3), (2, 3)])
    assert is_infinitesimally_rigid(tri, edges)
    d_star = np.linalg.norm(tri[edges[:, 0]] - tri[edges[:, 1]], axis=1)
    p = tri + rng.normal(0, 0.2, tri.shape)
    for _ in range(3000):
        p = p + 0.01 * distance_formation_control(p, edges, d_star, k=1.0)
    d = np.linalg.norm(p[edges[:, 0]] - p[edges[:, 1]], axis=1)
    assert np.abs(d - d_star).max() < 0.01
    print("[ok] rigidity test passes, distance-only formation converges")


def test_event_trigger_and_delay_bound():
    p = rng.uniform(-10, 10, (N, 3))
    A = build_adjacency(p, 12.0, 8)
    tau = delay_bound(laplacian(A))
    assert tau > 0
    sent = event_trigger(p + rng.normal(0, 0.15, p.shape), p, threshold=0.25)
    assert 0.0 < sent.mean() < 0.9
    print(f"[ok] delay bound {tau*1000:.0f} ms; event trigger sent {sent.mean()*100:.0f}% of nodes")


def test_performance_100_nodes():
    n = 100
    p = rng.uniform(-20, 20, (n, 3))
    st = SwarmState(p=p, v=np.zeros_like(p), delta=shape_sphere(n, 15.0),
                    alive=np.ones(n, bool))
    swarm_step(st, 0.02, r_sense=40.0, k_max=8, leader=np.zeros(3))
    t0 = time.perf_counter()
    for _ in range(20):
        st = swarm_step(st, 0.02, r_sense=40.0, k_max=8, leader=np.zeros(3))
    ms = (time.perf_counter() - t0) / 20 * 1000
    assert ms < 50, f"{ms:.1f} ms per step"
    print(f"[ok] performance: {ms:.1f} ms per step for 100 nodes (gate 50 ms)")


if __name__ == "__main__":
    for t in [test_first_order_bound, test_ring_formation_and_rotation,
              test_lose_ten_keep_flying, test_link_loss, test_cbf_never_violates,
              test_kalman_consensus, test_rigidity_and_distance_formation,
              test_event_trigger_and_delay_bound, test_performance_100_nodes]:
        t()
    print("\nall swarm tests passed")
