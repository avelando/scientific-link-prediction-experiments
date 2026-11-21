"""Reconstruct plain-text abstracts from OpenAlex's inverted index.

OpenAlex stores abstracts as an ``abstract_inverted_index`` mapping each token to
the positions where it occurs. Reconstruction places every token at its positions
and joins by spaces.

The reconstruction is diagnostic rather than silent: malformed indices (two tokens
claiming the same position, negative/non-integer positions, pathologically large
indices) are counted and optionally rejected, instead of being masked by a
last-writer-wins overwrite.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class AbstractDiagnostics:
    n_tokens_placed: int
    n_position_collisions: int   # positions claimed by >1 token
    n_invalid_positions: int     # negative / non-integer positions skipped
    truncated: bool              # input exceeded the position cap


class MalformedAbstractError(ValueError):
    """Raised in strict mode when the inverted index is malformed."""


def reconstruct_with_diagnostics(
    inverted_index: Mapping[str, Sequence[int]] | None,
    *,
    max_positions: int = 100_000,
    strict: bool = False,
) -> tuple[str | None, AbstractDiagnostics]:
    """Rebuild abstract text and report integrity diagnostics.

    Args:
        inverted_index: ``token -> [positions]`` mapping, or ``None``.
        max_positions: hard cap on positions consumed (memory guard); the scan
            stops once this many valid positions are placed and marks ``truncated``.
        strict: if True, raise :class:`MalformedAbstractError` on any collision or
            invalid position.

    Returns:
        ``(text_or_None, diagnostics)``.
    """
    diag_zero = AbstractDiagnostics(0, 0, 0, False)
    if not inverted_index:
        return None, diag_zero

    position_to_token: dict[int, str] = {}
    collisions = 0
    invalid = 0
    truncated = False

    for token, positions in inverted_index.items():
        if positions is None:
            continue
        for pos in positions:
            if not isinstance(pos, int) or isinstance(pos, bool) or pos < 0:
                invalid += 1
                continue
            if pos in position_to_token and position_to_token[pos] != token:
                collisions += 1
            position_to_token[pos] = token
            if len(position_to_token) >= max_positions:
                truncated = True
                break
        if truncated:
            break

    if strict and (collisions or invalid):
        raise MalformedAbstractError(
            f"malformed inverted index: collisions={collisions}, invalid={invalid}"
        )

    if not position_to_token:
        return None, AbstractDiagnostics(0, collisions, invalid, truncated)

    ordered = sorted(position_to_token)
    text = " ".join(position_to_token[p] for p in ordered).strip()
    diag = AbstractDiagnostics(
        n_tokens_placed=len(ordered),
        n_position_collisions=collisions,
        n_invalid_positions=invalid,
        truncated=truncated,
    )
    return (text or None), diag


def reconstruct_abstract(
    inverted_index: Mapping[str, Sequence[int]] | None,
    *,
    max_tokens: int | None = 100_000,
    strict: bool = False,
) -> str | None:
    """Rebuild abstract text from an OpenAlex inverted index.

    Thin wrapper over :func:`reconstruct_with_diagnostics` preserving the original
    signature. ``max_tokens`` caps the positions consumed (``None`` -> large cap).
    """
    cap = max_tokens if max_tokens is not None else 10_000_000
    text, _ = reconstruct_with_diagnostics(inverted_index, max_positions=cap, strict=strict)
    return text
