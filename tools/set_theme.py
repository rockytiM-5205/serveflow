"""Choose ServeFlow's look: the earlier ("classic") design, or the premium one.

    python tools/set_theme.py classic     # the earlier design (the launch default)
    python tools/set_theme.py premium     # the premium redesign
    python tools/set_theme.py             # show which one is active

Both designs live in frontend/shared/css/themes/<name>/. This copies the chosen one over the live stylesheets, so pages load exactly the same
files as before (no extra requests, no build step). Edit a theme's files in its folder, then run this again; a test fails if they drift apart.
The markup, scripts, icons and the order animation are shared, so switching changes the look only.
"""
import shutil
import sys
from pathlib import Path

FE = Path(__file__).resolve().parent.parent / "frontend"
THEMES = FE / "shared" / "css" / "themes"
FILES = {
    "tokens.css": "shared/css/tokens.css", "base.css": "shared/css/base.css", "layout.css": "shared/css/layout.css",
    "components.css": "shared/css/components.css", "plans.css": "shared/css/plans.css",
    "customer.css": "customer/css/customer.css", "marketplace.css": "customer/css/marketplace.css",
    "dashboard.css": "restaurant-dashboard/css/dashboard.css", "owner.css": "owner-control-centre/css/owner.css",
}


def available():
    return sorted(p.name for p in THEMES.iterdir() if p.is_dir())


def active():
    return (THEMES / "ACTIVE").read_text().strip()


def apply(name):
    if name not in available():
        sys.exit(f"Unknown theme {name!r}. Choose one of: {', '.join(available())}")
    for source, target in FILES.items():
        shutil.copyfile(THEMES / name / source, FE / target)
    (THEMES / "ACTIVE").write_text(name + "\n")
    print(f"The {name} design is now active ({len(FILES)} stylesheets updated). Reload the pages.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        apply(sys.argv[1].lower())
    else:
        print(f"Active design: {active()}. Available: {', '.join(available())}")
