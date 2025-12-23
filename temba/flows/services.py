def set_flows_mutability(flows, is_mutable: bool):
    for flow in flows:
        if flow.is_mutable != is_mutable:
            flow.is_mutable = is_mutable
            flow.save(update_fields=["is_mutable"])
