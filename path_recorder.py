"""Path Recorder: trace the real walkway for each edge -> data/campus_paths.json

Run from the project root:   streamlit run path_recorder.py
Needs data/campus_nodes.json and data/campus_edges.json (run make_edges.py first).
"""
import json
import os
import re

import folium
import streamlit as st
from streamlit_folium import st_folium

st.set_page_config(page_title="Path Recorder", layout="wide")

PATHS = "data/campus_paths.json"
EDGES_FILE = "data/campus_edges.json"

with open("data/campus_nodes.json") as f:
    nodes = json.load(f)
if not os.path.exists(EDGES_FILE):
    st.error("data/campus_edges.json not found. Run  python make_edges.py  first.")
    st.stop()
with open(EDGES_FILE) as f:
    edges = [tuple(e) for e in json.load(f)]
paths = json.load(open(PATHS)) if os.path.exists(PATHS) else {}


def done(e):
    return f"{e[0]}|{e[1]}" in paths or f"{e[1]}|{e[0]}" in paths


# --- sidebar: choose the edge ---
if st.session_state.pop("goto_next", False):  # after Save, jump to the next unrecorded edge
    todo = [i for i, e in enumerate(edges) if not done(e)]
    if todo:
        st.session_state["edge_pick"] = todo[0]

n_done = sum(done(e) for e in edges)
st.sidebar.progress(n_done / len(edges), text=f"{n_done}/{len(edges)} edges recorded")
if "edge_pick" not in st.session_state:  # first load: open on the first unrecorded edge
    st.session_state["edge_pick"] = next((i for i, e in enumerate(edges) if not done(e)), 0)
pick = st.sidebar.selectbox(
    "① Choose an edge to record",
    range(len(edges)),
    format_func=lambda i: f"{'✅' if done(edges[i]) else '⬜'} {edges[i][0]} → {edges[i][1]}",
    key="edge_pick",
)
a, b = edges[pick]
A, B = nodes[a], nodes[b]
key = f"{a}|{b}"

if st.session_state.get("key") != key:  # edge changed: start fresh and re-centre the map
    st.session_state.key = key
    st.session_state.pts = []
    st.session_state.last = None
    st.session_state.just_switched = True
    st.session_state.center = ((A["lat"] + B["lat"]) / 2, (A["lon"] + B["lon"]) / 2)
    st.session_state.zoom = 18

# --- page header + instructions ---
st.title("🛣️ Path Recorder")
st.info(
    f"**Trace the walkway from 🟢 {a} to 🔴 {b}.**\n\n"
    "1. Zoom the map until you can see the real paths (use the satellite layer).\n"
    "2. Click on the map **along the walkway**, starting near the green START dot and "
    "moving toward the red END dot. Click at every turn, and every 15 to 30 metres on straight parts. "
    "Each click adds a yellow dot and extends the red line.\n"
    "3. Wrong click? Press **Undo**. When the red line follows the walkway, press **Save**."
)

pts = st.session_state.pts

# --- map: the base map never changes, only the feature group does (this prevents flicker) ---
lat0 = sum(n["lat"] for n in nodes.values()) / len(nodes)
lon0 = sum(n["lon"] for n in nodes.values()) / len(nodes)
m = folium.Map(location=[lat0, lon0], zoom_start=17, max_zoom=19, tiles=None)
folium.TileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Esri", name="Satellite", max_zoom=19,
).add_to(m)
folium.TileLayer("OpenStreetMap", name="Street map", max_zoom=19).add_to(m)
folium.LayerControl().add_to(m)


def tag(text, color, dot=10, dx=8, dy=-8, size=11):
    return folium.DivIcon(
        html=(
            f'<div style="pointer-events:none;white-space:nowrap;position:relative;">'
            f'<span style="position:absolute;left:-{dot // 2}px;top:-{dot // 2}px;width:{dot}px;height:{dot}px;'
            f'border-radius:50%;background:{color};border:2px solid #fff;"></span>'
            f'<b style="position:absolute;left:{dx}px;top:{dy}px;color:#fff;font:700 {size}px sans-serif;'
            f'text-shadow:0 0 3px #000,0 0 3px #000;">{text}</b></div>'
        ),
        icon_size=(0, 0),
    )


for n, d in nodes.items():  # all locations, not clickable so they never block your clicks
    folium.Marker([d["lat"], d["lon"]], icon=tag(n, "#9ca3af", dot=8), interactive=False).add_to(m)

fg = folium.FeatureGroup(name="current edge")
line = [[A["lat"], A["lon"]]] + pts + [[B["lat"], B["lon"]]]
folium.PolyLine(line, color="red", weight=5, opacity=0.9, interactive=False).add_to(fg)
for p in pts:
    folium.CircleMarker(p, radius=5, color="#facc15", fill=True, fill_opacity=1, interactive=False).add_to(fg)
folium.Marker([A["lat"], A["lon"]], icon=tag("START", "#22c55e", dot=18, dy=-26, size=13), interactive=False).add_to(fg)
folium.Marker([B["lat"], B["lon"]], icon=tag("END", "#ef4444", dot=18, dy=-26, size=13), interactive=False).add_to(fg)

out = st_folium(
    m,
    feature_group_to_add=fg,
    center=st.session_state.center,
    zoom=st.session_state.zoom,
    height=580,
    use_container_width=True,
    key="rec_map",
    returned_objects=["last_clicked"],
)

# --- handle clicks ---
click = (out or {}).get("last_clicked")
p = [round(click["lat"], 7), round(click["lng"], 7)] if click else None
if st.session_state.pop("just_switched", False):
    st.session_state.last = p  # ignore the click left over from the previous edge
elif p and p != st.session_state.last:
    st.session_state.last = p
    st.session_state.pts.append(p)
    st.rerun()

# --- buttons ---
st.write(f"**{len(pts)} points** added for {a} → {b}")
c1, c2, c3 = st.columns(3)
if c1.button("↩️ Undo last point", use_container_width=True):
    if st.session_state.pts:
        st.session_state.pts.pop()
    st.rerun()
if c2.button("🗑️ Clear all points", use_container_width=True):
    st.session_state.pts = []
    st.rerun()
if c3.button("💾 Save this edge", type="primary", use_container_width=True):
    paths[key] = line
    with open(PATHS, "w") as f:
        json.dump(paths, f, indent=1)
    st.session_state.goto_next = True
    st.toast(f"Saved {a} → {b} ({len(pts)} points)", icon="✅")
    st.rerun()

# --- fallback: paste coordinates instead of clicking ---
with st.expander("Map clicking not working? Paste coordinates from Google Maps instead"):
    st.markdown(
        "In **Google Maps** (satellite view), **right-click** a spot on the walkway. The first menu item "
        "shows its coordinates, such as `12.873577, 80.219247`. Click it to copy. Do this along the walkway, "
        "from START to END, and paste one coordinate per line below."
    )
    pasted = st.text_area("One 'lat, lon' per line", height=150, key="pasted")
    if st.button("Use these points"):
        got = []
        for ln in pasted.splitlines():
            nums = re.findall(r"-?\d+\.\d+", ln)
            if len(nums) >= 2:
                got.append([float(nums[0]), float(nums[1])])
        st.session_state.pts = got
        st.rerun()