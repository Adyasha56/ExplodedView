"""
PDF text extractor interface.

Any direct PDF text extraction strategy (PyMuPDF, pdfplumber, etc.) used by
callout_reader.py must conform to this Protocol. Swap implementations without
touching any downstream module.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class PdfTextExtractor(Protocol):
    """
    Contract for extracting text from a region of a PDF page.
    """

    def extract_text_in_rect(
        self,
        page,
        x: float,
        y: float,
        width: float,
        height: float,
    ) -> str | None:
        """
        Extract text found within a bounding rectangle on a PDF page.

        Parameters
        ----------
        page :
            A page object from the underlying PDF library (e.g. fitz.Page).
        x, y : float
            Top-left corner of the rectangle in PDF user-space units (points).
        width, height : float
            Dimensions of the rectangle in PDF user-space units.

        Returns
        -------
        str | None
            Extracted text, stripped of leading/trailing whitespace.
            Returns None if no text is found in the region.
        """
        ...
