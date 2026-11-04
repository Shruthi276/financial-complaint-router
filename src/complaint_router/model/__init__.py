"""Model package: the ComplaintRouter estimator and its MLflow pyfunc wrapper."""

from complaint_router.model.router_model import ComplaintRouter, RouterConfig

__all__ = ["ComplaintRouter", "RouterConfig"]
