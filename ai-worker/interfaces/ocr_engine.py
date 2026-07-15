"""
OCR engine interface.

Any OCR implementation used by callout_reader.py or bom_extractor.py must
conform to this Protocol. Swap PaddleOCR for Tesseract or any other engine
by providing a class that satisfies this interface — no other module changes.
"""

from typing import Protocol, runtime_checkable
import numpy as np


@runtime_checkable
class OcrEngine(Protocol):
    """
    Contract for an OCR engine that operates on NumPy image arrays.
    """

    def extract_text(self, image: np.ndarray) -> list[dict]:
        """
        Run OCR on a single image crop.

        Parameters
        ----------
        image : np.ndarray
            BGR or grayscale image array (as returned by cv2.imread / crop).

        Returns
        -------
        list[dict]
            Each dict contains:
              - "text"  : str   — recognised text
              - "score" : float — confidence score 0.0–1.0
        """
        ...
