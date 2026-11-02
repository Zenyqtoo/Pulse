"""Route trained local expert predictions using observable record metadata only."""


def route_predictions(kind, general, contextual):
    output = dict(general)
    output["geo"] = contextual["geo"]
    if kind in ("article","post"):
        output["sentiment"] = contextual["sentiment"]
        output["message_type"] = contextual["message_type"]
    return output
