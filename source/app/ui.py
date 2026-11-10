"""Presentation helpers for the templates (icons, initials, score classes).

Icons are inline SVG paths, so no external icon font or script is needed and
the strict Content Security Policy stays unchanged.
"""

ICONS = {
    "shield": ["M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"],
    "shield-check": ["M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z", "M9 12l2 2 4-4"],
    "shield-alert": ["M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z", "M12 8v4", "M12 16h.01"],
    "home": ["M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"],
    "user": ["M20 21a8 8 0 0 0-16 0", "M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z"],
    "users": ["M17 21a6 6 0 0 0-12 0", "M11 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
              "M22 21a5 5 0 0 0-4-4.9", "M16 3.1a4 4 0 0 1 0 7.8"],
    "user-plus": ["M16 21a6 6 0 0 0-12 0", "M10 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", "M19 8v6", "M22 11h-6"],
    "user-x": ["M16 21a6 6 0 0 0-12 0", "M10 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", "M17 8l5 5", "M22 8l-5 5"],
    "book": ["M4 19.5A2.5 2.5 0 0 1 6.5 17H20V2H6.5A2.5 2.5 0 0 0 4 4.5z", "M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"],
    "graduation": ["M22 10 12 5 2 10l10 5 10-5z", "M6 12v5c3 2 9 2 12 0v-5"],
    "clipboard": ["M9 3h6a1 1 0 0 1 1 1v2H8V4a1 1 0 0 1 1-1z",
                  "M8 5H6a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2", "M9 14l2 2 4-4"],
    "list": ["M8 6h13", "M8 12h13", "M8 18h13", "M3 6h.01", "M3 12h.01", "M3 18h.01"],
    "key": ["M10.7 12.3 21 2", "M16 7l3 3", "M7.5 21a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9z"],
    "activity": ["M22 12h-4l-3 9L9 3l-3 9H2"],
    "lock": ["M7 11V7a5 5 0 0 1 10 0v4", "M5 11h14a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1z"],
    "unlock": ["M7 11V7a5 5 0 0 1 9.9-1",
               "M5 11h14a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-8a1 1 0 0 1 1-1z"],
    "logout": ["M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4", "M16 17l5-5-5-5", "M21 12H9"],
    "login": ["M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4", "M10 17l5-5-5-5", "M15 12H3"],
    "search": ["M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16z", "M21 21l-4.3-4.3"],
    "plus": ["M12 5v14", "M5 12h14"],
    "check": ["M20 6 9 17l-5-5"],
    "check-circle": ["M22 11.1V12a10 10 0 1 1-5.9-9.1", "M22 4 12 14l-3-3"],
    "x": ["M18 6 6 18", "M6 6l12 12"],
    "alert": ["M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z", "M12 9v4", "M12 17h.01"],
    "ban": ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z", "M4.9 4.9l14.2 14.2"],
    "eye": ["M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z", "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"],
    "mail": ["M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z", "M22 6l-10 7L2 6"],
    "phone": ["M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 "
              "2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 "
              "2 0 0 1 2.1-.4c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z"],
    "map-pin": ["M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z", "M12 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6z"],
    "calendar": ["M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z", "M16 2v4", "M8 2v4", "M3 10h18"],
    "save": ["M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z", "M17 21v-8H7v8", "M7 3v5h8"],
    "edit": ["M12 20h9", "M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"],
    "trash": ["M3 6h18", "M8 6V4h8v2", "M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"],
    "layers": ["M12 2 2 7l10 5 10-5-10-5z", "M2 17l10 5 10-5", "M2 12l10 5 10-5"],
    "filter": ["M22 3H2l8 9.5V19l4 2v-8.5z"],
    "arrow-right": ["M5 12h14", "M12 5l7 7-7 7"],
    "chevron-right": ["M9 18l6-6-6-6"],
    "menu": ["M3 6h18", "M3 12h18", "M3 18h18"],
    "database": ["M12 8c4.4 0 8-1.3 8-3s-3.6-3-8-3-8 1.3-8 3 3.6 3 8 3z", "M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5",
                 "M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"],
    "hash": ["M4 9h16", "M4 15h16", "M10 3 8 21", "M16 3l-2 18"],
    "clock": ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z", "M12 6v6l4 2"],
    "file": ["M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z", "M14 2v6h6", "M16 13H8", "M16 17H8"],
    "trending": ["M22 7 13.5 15.5l-5-5L2 17", "M16 7h6v6"],
    "compass": ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z", "M16.2 7.8l-2.1 6.3-6.3 2.1 2.1-6.3z"],
    "link": ["M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7", "M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"],
}


def initials(name):
    parts = [p for p in str(name or "?").replace("-", " ").split() if p[:1].isalnum()]
    if not parts:
        return "?"
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()


def score_class(score):
    if score is None:
        return "none"
    score = float(score)
    if score >= 8.5:
        return "excellent"
    if score >= 7:
        return "good"
    if score >= 5:
        return "pass"
    return "fail"


def init_app(app):
    app.jinja_env.globals["ICONS"] = ICONS
    app.jinja_env.filters["initials"] = initials
    app.jinja_env.filters["score_class"] = score_class
