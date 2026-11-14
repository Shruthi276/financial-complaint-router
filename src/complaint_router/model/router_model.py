"""ComplaintRouter model: predicts the category, the priority flag, explains the
prediction and finds similar past complaints.

- TF-IDF (1-2 word grams) turns text into vectors.
- A linear classifier predicts the category (fast to train and easy to explain).
- A separate logistic regression predicts priority. Its threshold is tuned for
  recall, and severe cases (foreclosure, eviction, ...) are always escalated.
- Similar complaints = cosine similarity in the same TF-IDF space.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import joblib
import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.naive_bayes import ComplementNB

from complaint_router.categories import CATEGORY_BY_KEY, ESCALATION_KEYWORDS, urgent_keywords_in
from complaint_router.text_cleaning import normalize_text

SUPPORTED_MODELS = ("logreg", "sgd", "cnb")


@dataclass
class RouterConfig:
    """Model settings (same names as the `train` block in params.yaml)."""

    model_type: str = "logreg"
    max_features: int = 50000
    ngram_max: int = 2
    min_df: int = 3
    C: float = 4.0
    alpha: float = 1e-4
    max_iter: int = 1000
    priority_C: float = 2.0
    priority_target_recall: float = 0.80
    similar_index_size: int = 15000
    low_confidence_threshold: float = 0.50
    seed: int = 42
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_params(cls, train: dict[str, Any], evaluate: dict[str, Any] | None = None) -> RouterConfig:
        known = {k: v for k, v in train.items() if k in cls.__dataclass_fields__}
        cfg = cls(**known)
        if evaluate and "low_confidence_threshold" in evaluate:
            cfg.low_confidence_threshold = float(evaluate["low_confidence_threshold"])
        return cfg


class ComplaintRouter:
    """Trainable, serialisable complaint router."""

    def __init__(self, config: RouterConfig | None = None) -> None:
        self.config = config or RouterConfig()
        if self.config.model_type not in SUPPORTED_MODELS:
            raise ValueError(f"model_type must be one of {SUPPORTED_MODELS}, got {self.config.model_type!r}")
        self.vectorizer: TfidfVectorizer | None = None
        self.classifier: Any = None
        self.priority_model: LogisticRegression | None = None
        self.priority_threshold: float = 0.5
        self.classes_: np.ndarray | None = None
        self._class_weights: np.ndarray | None = None  # (n_classes, n_features) for explanations
        self._index_matrix: sparse.csr_matrix | None = None
        self._index_meta: pd.DataFrame | None = None
        self._vocab_terms: np.ndarray | None = None

    def _build_classifier(self) -> Any:
        cfg = self.config
        if cfg.model_type == "logreg":
            return LogisticRegression(C=cfg.C, max_iter=cfg.max_iter, solver="saga", random_state=cfg.seed)
        if cfg.model_type == "sgd":
            return SGDClassifier(loss="modified_huber", alpha=cfg.alpha, max_iter=cfg.max_iter,
                                 class_weight="balanced", random_state=cfg.seed)
        return ComplementNB(alpha=max(cfg.alpha, 1e-3) * 1000)  # alpha≈0.1 for NB smoothing

    def fit(self, texts: pd.Series, categories: pd.Series, priorities: pd.Series,
            metadata: pd.DataFrame | None = None) -> ComplaintRouter:
        """Train everything. `texts` must already be cleaned; `metadata` (optional)
        holds extra columns shown for similar complaints."""
        X = self.fit_vectorizer(texts)
        self.fit_category(X, categories)
        self.fit_priority(X, priorities)
        self.build_index(X, texts, categories, priorities, metadata)
        return self

    # Separate steps so train.py can log each one as its own MLflow run.
    def fit_vectorizer(self, texts: pd.Series) -> sparse.csr_matrix:
        """Fit the TF-IDF vocabulary and return the training matrix."""
        if len(texts) == 0:
            raise ValueError("Cannot fit ComplaintRouter on an empty dataset")
        cfg = self.config
        self.vectorizer = TfidfVectorizer(
            ngram_range=(1, cfg.ngram_max), min_df=cfg.min_df, max_features=cfg.max_features,
            sublinear_tf=True, strip_accents="unicode", dtype=np.float32,
        )
        X = self.vectorizer.fit_transform(texts)
        self._vocab_terms = self.vectorizer.get_feature_names_out()
        return X

    def fit_category(self, X: sparse.csr_matrix, categories: pd.Series) -> None:
        """Fit the routing-category classifier."""
        self.classifier = self._build_classifier()
        self.classifier.fit(X, categories)
        self.classes_ = self.classifier.classes_
        self._class_weights = self._extract_class_weights()

    def fit_priority(self, X: sparse.csr_matrix, priorities: pd.Series) -> None:
        """Fit the (class-balanced) high-priority classifier."""
        cfg = self.config
        self.priority_model = LogisticRegression(C=cfg.priority_C, class_weight="balanced",
                                                 max_iter=cfg.max_iter, random_state=cfg.seed)
        self.priority_model.fit(X, np.asarray(priorities).astype(int))

    def _extract_class_weights(self) -> np.ndarray:
        """Per-class term weights used to explain a prediction."""
        clf = self.classifier
        if hasattr(clf, "coef_"):
            return np.asarray(clf.coef_, dtype=np.float32)
        # ComplementNB: centre log-probabilities so weights are relative across classes.
        logp = np.asarray(clf.feature_log_prob_, dtype=np.float32)
        return -(logp - logp.mean(axis=0, keepdims=True))

    def build_index(self, X: sparse.csr_matrix, texts: pd.Series, categories: pd.Series,
                    priorities: pd.Series, metadata: pd.DataFrame | None = None) -> None:
        """Keep a random subset of training complaints for similar-case retrieval."""
        n = X.shape[0]
        size = min(self.config.similar_index_size, n)
        rng = np.random.default_rng(self.config.seed)
        rows = np.sort(rng.choice(n, size=size, replace=False))
        self._index_matrix = X[rows].tocsr()
        meta = pd.DataFrame({
            "category": np.asarray(categories)[rows],
            "priority": np.asarray(priorities)[rows].astype(int),
            "snippet": [t[:280] for t in np.asarray(texts)[rows]],
        })
        if metadata is not None:
            for col in ("complaint_id", "issue", "date_received", "company_response"):
                if col in metadata.columns:
                    meta[col] = np.asarray(metadata[col])[rows]
        self._index_meta = meta.reset_index(drop=True)

    def tune_priority_threshold(self, texts: pd.Series, priorities: pd.Series) -> float:
        """Pick the highest threshold that still reaches the target recall on validation data."""
        self._check_fitted()
        scores = self.priority_model.predict_proba(self.vectorizer.transform(texts))[:, 1]
        y = np.asarray(priorities).astype(int)
        positives = y.sum()
        threshold = 0.5
        if positives > 0:
            for t in np.round(np.arange(0.95, 0.04, -0.01), 2):
                recall = ((scores >= t) & (y == 1)).sum() / positives
                if recall >= self.config.priority_target_recall:
                    threshold = float(t)
                    break
        self.priority_threshold = threshold
        return threshold

    def _check_fitted(self) -> None:
        if self.vectorizer is None or self.classifier is None or self.priority_model is None:
            raise RuntimeError("ComplaintRouter is not fitted")

    def predict_proba(self, texts: list[str] | pd.Series) -> np.ndarray:
        """Category probabilities for already-normalised texts."""
        self._check_fitted()
        return self.classifier.predict_proba(self.vectorizer.transform(texts))

    def top_terms_per_class(self, n: int = 15) -> dict[str, list[str]]:
        """Most indicative terms of each class (global feature importance)."""
        self._check_fitted()
        return {str(c): [str(self._vocab_terms[j]) for j in np.argsort(self._class_weights[i])[::-1][:n]]
                for i, c in enumerate(self.classes_)}

    def oov_rate(self, text: str) -> float:
        """Share of tokens not in the training vocabulary (a drift signal)."""
        self._check_fitted()
        tokens = text.split()
        if not tokens:
            return 1.0
        vocab = self.vectorizer.vocabulary_
        return float(sum(1 for t in tokens if t not in vocab) / len(tokens))

    def predict(self, raw_texts: list[str], top_k_similar: int = 3, top_terms: int = 8) -> list[dict[str, Any]]:
        """Full routing decision for raw (un-normalised) complaint texts."""
        self._check_fitted()
        clean = [normalize_text(t) for t in raw_texts]
        X = self.vectorizer.transform(clean)
        proba = self.classifier.predict_proba(X)
        prio = self.priority_model.predict_proba(X)[:, 1]
        sims = (X @ self._index_matrix.T).tocsr() if top_k_similar > 0 else None

        results = []
        for i, raw in enumerate(raw_texts):
            order = np.argsort(proba[i])[::-1]
            best = int(order[0])
            category = str(self.classes_[best])
            confidence = float(proba[i, best])
            keywords = urgent_keywords_in(raw)
            high = self.priority_decision(float(prio[i]), keywords)
            cat = CATEGORY_BY_KEY.get(category)
            results.append({
                "category": category,
                "category_label": cat.label if cat else category,
                "team": cat.team if cat else "General Complaints Team",
                "confidence": round(confidence, 4),
                "low_confidence": confidence < self.config.low_confidence_threshold,
                "alternatives": [
                    {"category": str(self.classes_[j]),
                     "category_label": CATEGORY_BY_KEY[str(self.classes_[j])].label
                     if str(self.classes_[j]) in CATEGORY_BY_KEY else str(self.classes_[j]),
                     "probability": round(float(proba[i, j]), 4)}
                    for j in order[:3]
                ],
                "priority": "high" if high else "normal",
                "priority_score": round(float(prio[i]), 4),
                "priority_threshold": round(self.priority_threshold, 4),
                "priority_reasons": self._priority_reasons(high, float(prio[i]), keywords),
                "explanation": self._explain(X[i], best, top_terms),
                "similar_complaints": self._similar(sims[i], top_k_similar) if sims is not None else [],
                "text_stats": {"n_chars": len(clean[i]), "n_tokens": len(clean[i].split()),
                               "oov_rate": round(self.oov_rate(clean[i]), 4)},
            })
        return results

    def priority_decision(self, score: float, keywords: list[str]) -> bool:
        """Final urgency flag = model score above threshold OR a severe escalation keyword."""
        return score >= self.priority_threshold or any(k in ESCALATION_KEYWORDS for k in keywords)

    def _priority_reasons(self, high: bool, score: float, keywords: list[str]) -> list[str]:
        reasons = []
        severe = [k for k in keywords if k in ESCALATION_KEYWORDS]
        signals = [k for k in keywords if k not in ESCALATION_KEYWORDS]
        if severe:
            reasons.append("Severe situation, always escalated: " + ", ".join(severe))
        if signals:
            reasons.append("Urgency signals mentioned: " + ", ".join(signals[:6]))
        side = "above" if score >= self.priority_threshold else "below"
        reasons.append(f"Model urgency score {score:.2f} is {side} the escalation threshold "
                       f"{self.priority_threshold:.2f}")
        return reasons

    def _explain(self, x_row: sparse.csr_matrix, class_idx: int, top_terms: int) -> list[dict[str, Any]]:
        """Top terms pushing the text towards the predicted class."""
        x_row = x_row.tocsr()
        if x_row.nnz == 0:
            return []
        idx = x_row.indices
        contrib = x_row.data * self._class_weights[class_idx, idx]
        top = np.argsort(contrib)[::-1][:top_terms]
        return [{"term": str(self._vocab_terms[idx[j]]), "weight": round(float(contrib[j]), 4)}
                for j in top if contrib[j] > 0]

    def _similar(self, sim_row: sparse.csr_matrix, k: int) -> list[dict[str, Any]]:
        sim_row = sim_row.tocsr()
        if sim_row.nnz == 0:
            return []
        order = np.argsort(sim_row.data)[::-1][:k]
        out = []
        for j in order:
            meta = self._index_meta.iloc[int(sim_row.indices[j])].to_dict()
            cat = CATEGORY_BY_KEY.get(meta.get("category", ""))
            out.append({
                "complaint_id": str(meta.get("complaint_id", "")),
                "similarity": round(float(sim_row.data[j]), 4),
                "category": meta.get("category"),
                "category_label": cat.label if cat else meta.get("category"),
                "priority": "high" if int(meta.get("priority", 0)) else "normal",
                "issue": meta.get("issue", ""),
                "date_received": meta.get("date_received", ""),
                "company_response": meta.get("company_response", ""),
                "snippet": meta.get("snippet", ""),
            })
        return out

    def save(self, path: str) -> None:
        """Serialise the whole router to a single joblib file."""
        self._check_fitted()
        joblib.dump({"config": asdict(self.config), "state": {
            "vectorizer": self.vectorizer, "classifier": self.classifier,
            "priority_model": self.priority_model, "priority_threshold": self.priority_threshold,
            "classes_": self.classes_, "class_weights": self._class_weights,
            "index_matrix": self._index_matrix, "index_meta": self._index_meta,
            "vocab_terms": self._vocab_terms,
        }}, path, compress=3)

    @classmethod
    def load(cls, path: str) -> ComplaintRouter:
        """Load a model saved with save()."""
        payload = joblib.load(path)
        router = cls(RouterConfig(**payload["config"]))
        s = payload["state"]
        router.vectorizer, router.classifier = s["vectorizer"], s["classifier"]
        router.priority_model, router.priority_threshold = s["priority_model"], s["priority_threshold"]
        router.classes_, router._class_weights = s["classes_"], s["class_weights"]
        router._index_matrix, router._index_meta = s["index_matrix"], s["index_meta"]
        router._vocab_terms = s["vocab_terms"]
        return router
