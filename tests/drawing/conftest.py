import pytest


@pytest.fixture(scope="session")
def geometry_files(analyzed, tmp_path_factory):
    d = tmp_path_factory.mktemp("geo")
    out = {}
    for name, (ir, _) in analyzed.items():
        p = d / f"{name}.json"
        p.write_text(ir.model_dump_json())
        out[name] = p
    return out
