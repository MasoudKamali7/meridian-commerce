"""
Meridian Commerce — Phase 3: Evaluation Metrics

Computes classification metrics by comparing ai_predicted_category against
the historical ground-truth category. Uses scikit-learn's well-tested metric
implementations rather than hand-rolled math, to avoid introducing subtle
bugs into the numbers this project's credibility depends on.

Macro F1 is reported alongside overall accuracy specifically because the
ticket categories are NOT evenly distributed (Phase 2 generated them with
explicit non-uniform weights — see PHASE2_SUMMARY.md). Overall accuracy can
look artificially strong if a classifier does well on the largest categories
(e.g. "Order Status Inquiry") while doing poorly on rare ones (e.g. "Other").
Macro F1 averages the per-category F1 scores unweighted, so every category
counts equally regardless of how many tickets it has — a more honest signal
of whether the classifier actually works across the full vocabulary, not
just the common cases.
"""

from dataclasses import dataclass, field
from typing import Optional

from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
)

from ..config import APPROVED_CATEGORIES


@dataclass
class EvaluationReport:
    n_evaluated: int
    accuracy: float
    macro_f1: float
    per_category: dict           # category -> {precision, recall, f1, support}
    confusion_matrix: list       # list of lists, rows=ground truth, cols=predicted
    labels: list                 # the label order used for the confusion matrix


def compute_metrics(ground_truth: list, predicted: list) -> EvaluationReport:
    """Both lists must be the same length and use the approved category
    vocabulary. Categories with zero support in this evaluation batch are
    still included in the confusion matrix (labeled explicitly) so the
    report doesn't silently hide "never predicted, never seen" categories."""
    if len(ground_truth) != len(predicted):
        raise ValueError("ground_truth and predicted must be the same length")
    if len(ground_truth) == 0:
        raise ValueError("Cannot compute metrics on an empty evaluation set")

    labels = APPROVED_CATEGORIES  # fixed, known order — not inferred from the data

    accuracy = accuracy_score(ground_truth, predicted)
    macro_f1 = f1_score(ground_truth, predicted, labels=labels, average="macro", zero_division=0)

    precision, recall, f1, support = precision_recall_fscore_support(
        ground_truth, predicted, labels=labels, average=None, zero_division=0
    )

    per_category = {
        label: {
            "precision": float(precision[i]),
            "recall": float(recall[i]),
            "f1": float(f1[i]),
            "support": int(support[i]),
        }
        for i, label in enumerate(labels)
    }

    cm = confusion_matrix(ground_truth, predicted, labels=labels)

    return EvaluationReport(
        n_evaluated=len(ground_truth),
        accuracy=float(accuracy),
        macro_f1=float(macro_f1),
        per_category=per_category,
        confusion_matrix=cm.tolist(),
        labels=labels,
    )
