"""Propose walking-graph edges from node coordinates -> data/campus_edges.json

Run:  python make_edges.py
It connects every location to its nearest neighbours and guarantees the whole campus is
connected (minimum spanning tree). This is only a STARTING POINT based on distance.
Open data/campus_edges.json and delete any edge that is not a real walkway, or add
missing ones. Fewer, accurate edges are better: each edge needs one recorded path.
"""
import json
import math

import networkx as nx

NEAREST = 2  # extra links per location (on top of the spanning tree)
MAX_M = 330  # ignore extra links longer than this (metres)

with open("data/campus_nodes.json") as f:
    nodes = json.load(f)


def dist_m(a, b):
    r = 6371000
    la1, lo1 = math.radians(nodes[a]["lat"]), math.radians(nodes[a]["lon"])
    la2, lo2 = math.radians(nodes[b]["lat"]), math.radians(nodes[b]["lon"])
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


names = list(nodes)
full = nx.Graph()
for i, a in enumerate(names):
    for b in names[i + 1:]:
        full.add_edge(a, b, weight=dist_m(a, b))

edges = {tuple(sorted(e)) for e in nx.minimum_spanning_tree(full).edges}
for a in names:
    near = sorted((n for n in names if n != a), key=lambda n: dist_m(a, n))[:NEAREST]
    for b in near:
        if dist_m(a, b) <= MAX_M:
            edges.add(tuple(sorted((a, b))))

out = [list(e) for e in sorted(edges)]
with open("data/campus_edges.json", "w") as f:
    json.dump(out, f, indent=1)

print(f"{len(out)} edges saved to data/campus_edges.json\n")
for a, b in out:
    print(f"{a:34s} - {b:34s} {round(dist_m(a, b)):4d} m")
