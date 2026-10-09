import numpy as np
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score


def _ratio(numerator, denominator):
    return float(numerator / denominator) if denominator else None


def classification_metrics(labels, predictions, scores=None):
    y = np.asarray(labels, dtype=np.int8)
    p = np.asarray(predictions, dtype=np.int8)
    tp = int(np.sum((y == 1) & (p == 1)))
    fp = int(np.sum((y == 0) & (p == 1)))
    fn = int(np.sum((y == 1) & (p == 0)))
    tn = int(np.sum((y == 0) & (p == 0)))
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    f1 = _ratio(2 * tp, 2 * tp + fp + fn)
    fpr = _ratio(fp, fp + tn)
    ap = auc = None
    if scores is not None:
        s = np.asarray(scores, dtype=np.float64)
        if np.any(y == 1):
            ap = float(average_precision_score(y, s))
        if np.any(y == 1) and np.any(y == 0):
            auc = float(roc_auc_score(y, s))
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision, "recall": recall, "f1": f1,
        "average_precision": ap, "roc_auc": auc, "fpr": fpr,
        "positive_support": int(np.sum(y == 1)),
        "negative_support": int(np.sum(y == 0)),
    }


def select_threshold(labels, scores, max_fpr=0.01):
    """Select the best observed cutoff without relaxing the false-positive budget."""
    y = np.asarray(labels, dtype=np.int8)
    s = np.asarray(scores, dtype=np.float64)
    if len(y) != len(s) or not len(y):
        raise ValueError("labels and scores must be non-empty and equally sized")
    if not np.all(np.isfinite(s)):
        raise ValueError("scores must be finite")

    order = np.argsort(-s, kind="stable")
    y_sorted, s_sorted = y[order], s[order]
    positives = int(np.sum(y == 1))
    negatives = int(np.sum(y == 0))
    tp = fp = 0
    curve = []
    best = None
    index = 0
    while index < len(y):
        threshold = float(s_sorted[index])
        stop = index
        while stop < len(y) and s_sorted[stop] == threshold:
            tp += int(y_sorted[stop] == 1)
            fp += int(y_sorted[stop] == 0)
            stop += 1
        fn, tn = positives - tp, negatives - fp
        row = {"threshold": threshold, "alerts": tp + fp,
               "tp": tp, "fp": fp, "fn": fn, "tn": tn,
               "precision": _ratio(tp, tp + fp), "recall": _ratio(tp, positives),
               "f1": _ratio(2 * tp, 2 * tp + fp + fn), "fpr": _ratio(fp, negatives)}
        curve.append(row)
        feasible = row["alerts"] > 0 and row["fpr"] is not None and row["fpr"] <= max_fpr
        if feasible:
            rank = (row["f1"] if row["f1"] is not None else -1,
                    row["recall"] if row["recall"] is not None else -1,
                    threshold)
            if best is None or rank > best[0]:
                best = (rank, row)
        index = stop

    if best is None:
        threshold = None
        predictions = np.zeros(len(y), dtype=np.int8)
        result = classification_metrics(y, predictions, s)
        result.update({"threshold": threshold, "useful": False,
                       "status": "no useful feasible threshold"})
    else:
        threshold = best[1]["threshold"]
        predictions = (s >= threshold).astype(np.int8)
        result = classification_metrics(y, predictions, s)
        result.update({"threshold": threshold, "useful": True, "status": "selected"})
    return result, curve


def pr_curve(labels, scores):
    y = np.asarray(labels, dtype=np.int8)
    s = np.asarray(scores, dtype=np.float64)
    precision, recall, thresholds = precision_recall_curve(y, s)
    rows = []
    for index, threshold in enumerate(thresholds):
        rows.append({"threshold": float(threshold), "precision": float(precision[index]),
                     "recall": float(recall[index])})
    rows.append({"threshold": None, "precision": float(precision[-1]),
                 "recall": float(recall[-1])})
    return rows
