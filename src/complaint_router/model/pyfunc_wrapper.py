"""MLflow pyfunc wrapper so the model can be served with `mlflow models serve`.

Request:  {"dataframe_records": [{"text": "...", "top_k_similar": 3}]}
Response: {"predictions": [{"result": "<prediction as a JSON string>"}]}
(The result is a JSON string because MLflow only returns flat columns.)
"""

from __future__ import annotations

import json

import mlflow.pyfunc
import pandas as pd

from complaint_router.model.router_model import ComplaintRouter


class ComplaintRouterPyfunc(mlflow.pyfunc.PythonModel):
    """Thin adapter between the MLflow scoring protocol and ComplaintRouter."""

    def load_context(self, context) -> None:  # noqa: ANN001 - MLflow signature
        self.router = ComplaintRouter.load(context.artifacts["router"])

    def predict(self, context, model_input: pd.DataFrame, params=None) -> pd.DataFrame:  # noqa: ANN001
        if "text" not in model_input.columns:
            raise ValueError("Input must contain a 'text' column")
        texts = model_input["text"].fillna("").astype(str).tolist()
        top_k = 3
        if "top_k_similar" in model_input.columns and len(model_input):
            top_k = int(model_input["top_k_similar"].fillna(3).iloc[0])
        results = self.router.predict(texts, top_k_similar=max(0, min(top_k, 10)))
        return pd.DataFrame({"result": [json.dumps(r) for r in results]})
