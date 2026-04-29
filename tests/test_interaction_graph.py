from app.algorithms.interaction_graph import InteractionGraph


def test_graph_upsert_and_lookup() -> None:
    graph = InteractionGraph()
    graph.upsert_interaction(
        "aspirin",
        "warfarin",
        severity="D",
        risk="increased bleeding",
        recommendation="avoid combination",
        source="Lexicomp",
    )

    edge = graph.get_interaction("warfarin", "aspirin")
    assert edge is not None
    assert edge.severity == "D"
    assert edge.risk == "increased bleeding"
    assert graph.size() == 1
