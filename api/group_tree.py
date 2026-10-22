"""Scenario navigation hierarchy; permissions are filtered before tree creation."""


def validate_parents(parents):
    for slug, parent in parents.items():
        seen = {slug}
        while parent is not None:
            if parent not in parents:
                raise ValueError(f"Unknown parent group: {parent}")
            if parent in seen:
                raise ValueError("A group cannot contain itself or one of its ancestors")
            seen.add(parent)
            parent = parents[parent]


def build_tree(components, items, *, prune=False):
    nodes = {c.slug: {"component": c, "scenarios": items.get(c.slug, []), "children": []}
             for c in components}
    roots = []
    for c in components:
        parent = nodes.get(c.parent_group)
        (parent["children"] if parent else roots).append(nodes[c.slug])

    def count(node):
        node["children"] = [child for child in node["children"] if count(child) or not prune]
        node["count"] = len(node["scenarios"]) + sum(c["count"] for c in node["children"])
        return node["count"]
    return [node for node in roots if count(node) or not prune]
