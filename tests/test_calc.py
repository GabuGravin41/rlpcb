from rlpcb.calc import formulas as f

def test_trace_width_ipc2221():
    assert abs(f.trace_width(3, 10, 1, "external")["min_width_mm"] - 1.37) < 0.05

def test_microstrip_50ohm_on_1p6mm():
    assert 48 < f.microstrip(2.9, 1.5, 4.3)["z0_ohm"] < 52

def test_divider():
    r = f.divider(5, vref=0.8)
    assert abs(r["error_percent"]) < 1

def test_solver_hits_target():
    assert abs(f.solve_width_for_impedance(50, 0.2)["achieved_ohm"] - 50) < 0.5
