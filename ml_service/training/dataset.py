from __future__ import annotations

import pandas as pd

from ml_service_listing.domain.models import Listing
from ml_service_listing.features.extractor import extract_features
from ml_service_listing.features.transformers import to_feature_row


def build_dataset(
    listings: list[Listing],
    labels: list[float] | None = None,
) -> pd.DataFrame:
    rows = [to_feature_row(extract_features(listing)) for listing in listings]
    df = pd.DataFrame(rows)
    if labels is not None:
        df["trust_score"] = labels
    return df
