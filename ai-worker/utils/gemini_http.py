"""
Gemini REST API HTTP helper.

Wraps requests.post with up to 2 retries on 429 (rate limit), using
exponential backoff. Both callers (strategy_e_recovery, llm_resolver)
share this so retry logic lives in one place.

Free-tier quotas produce 429s under sustained load; a simple backoff
recovers the vast majority without user-visible failures.
"""

import time

import requests

# Seconds to wait before retry 2 and retry 3 respectively.
_RETRY_DELAYS = (5, 15)


def gemini_post(
    url: str,
    payload: dict,
    timeout: int,
    logger,
) -> requests.Response:
    """
    POST to a Gemini generateContent endpoint.

    Retries up to 2 times on HTTP 429 (Too Many Requests) before raising.
    All other HTTP errors and network errors are raised immediately.

    Returns the successful Response object with raise_for_status() already called.
    """
    delay_iter = iter(_RETRY_DELAYS)
    attempt = 0

    while True:
        attempt += 1
        response = requests.post(url, json=payload, timeout=timeout)

        if response.status_code != 429:
            response.raise_for_status()
            return response

        try:
            delay = next(delay_iter)
        except StopIteration:
            # All retries exhausted — raise the 429 so callers can log it
            response.raise_for_status()

        logger.warning(
            "Gemini 429 Too Many Requests (attempt %d) — retrying in %ds",
            attempt, delay,
        )
        time.sleep(delay)
