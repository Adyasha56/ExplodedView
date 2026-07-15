"""
Mapping strategy interface.

The mapping engine uses this contract so that the matching algorithm
(exact, fuzzy, LLM-assisted, etc.) can be swapped independently.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class MappingStrategy(Protocol):
    """
    Contract for a strategy that matches a hotspot number to BOM ref numbers.
    """

    def match(
        self,
        hotspot_number: str,
        bom_ref_numbers: list[str],
    ) -> tuple[str | None, float]:
        """
        Attempt to match a hotspot number against a list of BOM ref numbers.

        Parameters
        ----------
        hotspot_number : str
            The number extracted from the callout circle (already normalised).
        bom_ref_numbers : list[str]
            All normalised BOM ref numbers that have not yet been matched.

        Returns
        -------
        (matched_ref | None, confidence)
            matched_ref : the winning BOM ref number, or None if no match found.
            confidence  : float 0.0–1.0 representing match quality.
        """
        ...
