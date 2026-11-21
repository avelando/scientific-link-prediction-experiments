"""Reconstruct plain-text abstracts from OpenAlex's inverted index.

OpenAlex does not store abstracts as text (for licensing reasons); it stores an
``abstract_inverted_index`` mapping each token to the list of positions where it
occurs. Reconstruction places every token at its positions and joins by spaces.

Edge cases handled:
    * ``None`` / empty index -> ``None`` (absent, not an empty string).
    * Positions with gaps (missing indices) -> gaps are skipped, not padded.
    * Duplicate/overlapping positions -> last writer wins deterministically by
      iterating tokens in insertion order; we instead build a position->token map,
      which is order-independent and matches OpenAlex's intended layout.
"""

from __future__ import annotations

from typing import Mapping, Sequence


def reconstruct_abstract(
    inverted_index: Mapping[str, Sequence[int]] | None,
    *,
    max_tokens: int | None = 100_000,
) -> str | None:
    """Rebuild abstract text from an OpenAlex inverted index.

    Args:
        inverted_index: mapping ``token -> [positions]`` as returned in
            ``work["abstract_inverted_index"]``. ``None`` means no abstract.
        max_tokens: safety cap on the reconstructed length (guards against
            pathological indices); ``None`` disables the cap.

    Returns:
        The reconstructed abstract, or ``None`` if the index is absent/empty.
    """
    if not inverted_index:
        return None

    position_to_token: dict[int, str] = {}
    for token, positions in inverted_index.items():
        if positions is None:
            continue
        for pos in positions:
            # Ignore non-int / negative positions defensively.
            if isinstance(pos, int) and pos >= 0:
                position_to_token[pos] = token

    if not position_to_token:
        return None

    ordered_positions = sorted(position_to_token)
    if max_tokens is not None:
        ordered_positions = ordered_positions[:max_tokens]

    text = " ".join(position_to_token[pos] for pos in ordered_positions)
    text = text.strip()
    return text or None
