"""Small MLflow helpers shared by the train / evaluate / register stages."""

from __future__ import annotations

import hashlib
import platform
from pathlib import Path

import mlflow

from complaint_router.config import mlflow_tracking_uri
from complaint_router.logging_utils import get_logger

logger = get_logger(__name__)


def setup_mlflow(experiment_name: str) -> str:
    """Point MLflow at the tracking server and select the experiment."""
    uri = mlflow_tracking_uri()
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment(experiment_name)
    logger.info("MLflow tracking URI: %s | experiment: %s", uri, experiment_name)
    return uri


def file_md5(path: str | Path, chunk: int = 1 << 20) -> str:
    """MD5 of a file: logged as a tag so a run can be tied to the exact data version."""
    digest = hashlib.md5()  # noqa: S324 - used for fingerprinting, not security
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def environment_tags() -> dict[str, str]:
    """Runtime information that autolog does not capture."""
    import sklearn

    return {"python_version": platform.python_version(), "platform": platform.platform(),
            "sklearn_version": sklearn.__version__, "mlflow_version": mlflow.__version__}
