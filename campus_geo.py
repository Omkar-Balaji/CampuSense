"""Location checks for CampuSense. No login: your phone's location decides who can post.

A post only counts when the browser reports a location that is
  - precise enough           (accuracy <= MAX_ACCURACY_M)
  - recent                   (fix is at most MAX_AGE_S old)
  - on campus                (within CAMPUS_MARGIN_M of a mapped location)
  - for crowd reports, close to the place being reported (within PLACE_RADIUS_M).

Coordinates are used only to answer "is this person on campus / near X?" and to start the
route. They are never written to the database.

Honest limit: a browser location can be faked by someone determined (developer tools or a
fake-GPS app). These checks stop casual abuse and people who are simply not on campus.
"""
import math
import time

CAMPUS_MARGIN_M = 200   # "on campus" = within this distance of any mapped location
PLACE_RADIUS_M = 120    # crowd reports must be this close to the place
MAX_ACCURACY_M = 100    # readings less precise than this are rejected (typical for PCs without GPS)
MAX_AGE_S = 600         # ask for a fresh fix after 10 minutes


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000
    la1, lo1, la2, lo2 = map(math.radians, (lat1, lon1, lat2, lon2))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def nearest(nodes, lat, lon):
    """(name, distance in metres) of the closest mapped location."""
    return min(((n, haversine_m(lat, lon, d["lat"], d["lon"])) for n, d in nodes.items()), key=lambda x: x[1])


def places_near(nodes, fix, radius=PLACE_RADIUS_M):
    """Places within `radius` metres of the fix, closest first: [(name, metres), ...]"""
    out = [(n, haversine_m(fix["lat"], fix["lon"], d["lat"], d["lon"])) for n, d in nodes.items()]
    return sorted(((n, round(m)) for n, m in out if m <= radius), key=lambda x: x[1])


def check(fix, nodes, now=None):
    """Classify a location fix. status is one of: none, stale, imprecise, outside, ok."""
    if not fix:
        return {"status": "none"}
    now = now or time.time()
    name, dist = nearest(nodes, fix["lat"], fix["lon"])
    info = {"nearest": name, "dist": round(dist), "acc": round(fix["acc"])}
    if now - fix["ts"] > MAX_AGE_S:
        return {**info, "status": "stale"}
    if fix["acc"] > MAX_ACCURACY_M:
        return {**info, "status": "imprecise"}
    if dist > CAMPUS_MARGIN_M:
        return {**info, "status": "outside"}
    return {**info, "status": "ok"}


def validate_report(fix, nodes, place, now=None):
    """Server-side re-check before a crowd report is saved. Returns (ok, message)."""
    c = check(fix, nodes, now)
    if c["status"] != "ok":
        return False, "Your location could not be verified on campus. Tap Locate me again."
    d = nodes[place]
    dist = haversine_m(fix["lat"], fix["lon"], d["lat"], d["lon"])
    if dist > PLACE_RADIUS_M:
        return False, f"You are about {round(dist)} m from {place}. Crowd reports must be sent from within {PLACE_RADIUS_M} m of the place."
    return True, "ok"


STATUS_TEXT = {
    "none": "Tap the button to share your location. It is used only to check you are on campus and to start your route, and is never stored.",
    "stale": "⏱️ Your location is out of date. Tap the button again.",
    "imprecise": "⚠️ Location is too imprecise (±{acc} m). Phones with GPS work best. On a PC, turn on Windows location services and Wi-Fi.",
    "outside": "🌍 You are about {km} km from campus. You can use everything, but posting is only for people on campus.",
    "ok": "✅ On campus, near {nearest} ({dist} m away, ±{acc} m)",
}


def status_message(c):
    return STATUS_TEXT[c["status"]].format(
        acc=c.get("acc"), nearest=c.get("nearest"), dist=c.get("dist"), km=round(c.get("dist", 0) / 1000, 1))


def read_location():
    """Show the Locate button (the browser asks permission) and return the latest fix:
    {'lat', 'lon', 'acc', 'ts'} or None. Needs https or localhost, plus: pip install streamlit-geolocation"""
    import streamlit as st
    try:
        from streamlit_geolocation import streamlit_geolocation
    except ImportError:
        st.warning("Location needs one extra install:  pip install streamlit-geolocation")
        return st.session_state.get("geo_fix")
    raw = streamlit_geolocation()
    if raw and raw.get("latitude") is not None and raw.get("longitude") is not None:
        key = (round(raw["latitude"], 6), round(raw["longitude"], 6), raw.get("accuracy"))
        if st.session_state.get("geo_key") != key:  # a new reading arrived
            st.session_state["geo_key"] = key
            st.session_state["geo_fix"] = {"lat": float(raw["latitude"]), "lon": float(raw["longitude"]),
                                           "acc": float(raw.get("accuracy") or 99999), "ts": time.time()}
    return st.session_state.get("geo_fix")