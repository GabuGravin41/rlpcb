from rlpcb.kicad.sexpr import parse, dump, QStr

def test_roundtrip_and_spans():
    t = '(kicad_sch (version 20231120) (property "Ref" "R\\"1" (at 1 2 0)) (flag) hide)'
    n = parse(t)
    assert n.head == "kicad_sch"
    p = n.child("property")
    assert p.items[2] == 'R"1' and isinstance(p.items[2], QStr)
    assert t[p.start:p.end].startswith("(property")
    assert parse(dump(n)).child("property").xy() == [1.0, 2.0, 0.0]
    assert n.has_flag("hide")
