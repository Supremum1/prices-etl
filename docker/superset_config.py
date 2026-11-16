import os
from cachelib.simple import SimpleCache

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]
SQLALCHEMY_DATABASE_URI = "sqlite:////app/superset_home/superset.db"
# Local, single-user showcase. No Redis, Celery, browser or scheduled jobs.
SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"check_same_thread": False, "timeout": 30}}
WTF_CSRF_ENABLED = True
TALISMAN_ENABLED = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
FEATURE_FLAGS = {"DASHBOARD_CROSS_FILTERS": True, "ENABLE_TEMPLATE_PROCESSING": True}
CACHE_CONFIG = {"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 300}
DATA_CACHE_CONFIG = {"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 300}
FILTER_STATE_CACHE_CONFIG = {"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 86400}
EXPLORE_FORM_DATA_CACHE_CONFIG = {"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 86400}
RESULTS_BACKEND = SimpleCache()
APP_NAME = "Цены на продукты"
HTML_SANITIZATION_SCHEMA_EXTENSIONS = {
    "tagNames": ["abbr"],
    "attributes": {"abbr": ["title", "tabIndex"]},
}
D3_FORMAT = {"decimal": ",", "thousands": " ", "grouping": [3], "currency": ["", " ₸"]}
THEME_DEFAULT = {
    "algorithm": "default",
    "token": {
        "colorPrimary": "#0f766e",
        "fontFamily": "Inter, Segoe UI, Arial, sans-serif",
        "borderRadius": 8,
    },
}
THEME_DARK = {
    "algorithm": "dark",
    "token": {
        "colorPrimary": "#2dd4bf",
        "fontFamily": "Inter, Segoe UI, Arial, sans-serif",
        "borderRadius": 8,
    },
}
ENABLE_PROXY_FIX = False
ROW_LIMIT = 100000
SQL_MAX_ROW = 100000
SUPERSET_WEBSERVER_TIMEOUT = 120
EXTRA_CATEGORICAL_COLOR_SCHEMES = [
    {
        "id": "food_observatory",
        "description": "Food Observatory",
        "label": "Food Observatory",
        "colors": [
            "#14b8a6",
            "#6366f1",
            "#f59e0b",
            "#f43f5e",
            "#3b82f6",
            "#a855f7",
            "#84cc16",
            "#06b6d4",
            "#f97316",
            "#ec4899",
            "#64748b",
            "#eab308",
        ],
        "isDefault": True,
    }
]
