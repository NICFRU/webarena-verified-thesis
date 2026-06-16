"""Warning filters for cleaner H/k experiment logs."""

from __future__ import annotations

import warnings


def suppress_third_party_warnings() -> None:
    """Suppress noisy dependency warnings that do not affect experiment results."""

    warnings.filterwarnings(
        "ignore",
        message=r".*PEP 484 type hint typing\.Mapping.*deprecated by PEP 585.*",
        category=Warning,
        module=r"beartype\..*",
    )
