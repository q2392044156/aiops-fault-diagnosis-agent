"""v1.1 题包与回传文件的字段约定：复核者可见的题面字段，以及要求其填写的复核字段。"""

VISIBLE = ("candidate_id", "query", "product_version", "source_url")
REVIEW = ("review_has_answer", "review_evidence_unit_ids", "reviewer_id", "review_notes")
