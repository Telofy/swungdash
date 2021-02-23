from squigglypy.dsl import mixture, normal, uniform
from squigglypy.tree import Value, bfs, _tracer


def test_bfs():
    def model(x: float) -> Value:
        weight = mixture([normal(2, 0.1), normal(0, 0.1)])
        bias = uniform(100, 200)
        return weight * x ** 2 + bias / 5

    parts, tracer = bfs(model)
    constants = [str(part) for part in parts if part.constant]
    variables = [str(part) for part in parts if not part.constant]
    assert tracer is not _tracer
    assert all(part.constant is not None for part in parts)
    assert constants == [
        "Mixture([normal(2, 0.1), normal(0, 0.1)])",
        "normal(2, 0.1)",
        "normal(0, 0.1)",
        "2",
        "uniform(100, 200) / 5",
        "uniform(100, 200)",
        "5",
    ]
    assert variables == [
        "Mixture([normal(2, 0.1), normal(0, 0.1)]) * x ** 2 + uniform(100, 200) / 5",
        "Mixture([normal(2, 0.1), normal(0, 0.1)]) * x ** 2",
        "x ** 2",
        "x",
    ]
