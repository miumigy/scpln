"""FastAPI アプリのAPI/UIモジュールパッケージ。

主要APIモジュールはインポート副作用によりルート登録します。
"""

# Ensure API modules are imported for side-effect route registrations
from app import simulation_api as _simulation_api  # noqa: F401
from app import jobs_api as _jobs_api  # noqa: F401
from app import config_api as _config_api  # noqa: F401
from app import scenario_api as _scenario_api  # noqa: F401
from app import run_compare_api as _run_compare_api  # noqa: F401
from app import plans_api as _plans_api  # noqa: F401
from app import run_meta_api as _run_meta_api  # noqa: F401
