import logging
from os import PathLike
from pathlib import Path
from typing import Callable, Iterable, Mapping, NamedTuple, Optional

from cartridges import shared

PathSegment = str | PathLike | Path
PathSegments = Iterable[PathSegment]
Candidate = PathSegments


class LocationSubPath(NamedTuple):
    segment: PathSegment
    is_directory: bool = False


class UnresolvableLocationError(Exception):
    def __init__(self, optional: Optional[bool] = False):
        self.optional = optional


class Location:
    """
    Class representing a filesystem location

    * A location may have multiple candidate roots
    * The path in the schema is always favored
    * From the candidate root, multiple subpaths should exist for it to be valid
    * When resolved, the schema is updated with the picked chosen
    """

    # The variable is the name of the source
    CACHE_INVALID_SUBTITLE = _("Select the {} cache directory.")
    # The variable is the name of the source
    CONFIG_INVALID_SUBTITLE = _("Select the {} configuration directory.")
    # The variable is the name of the source
    DATA_INVALID_SUBTITLE = _("Select the {} data directory.")

    schema_key: str
    candidates: Iterable[Candidate] | Callable[[], Iterable[Candidate]]
    paths: Mapping[str, LocationSubPath]
    invalid_subtitle: str

    root: Optional[Path] = None

    def __init__(
        self,
        schema_key: str,
        candidates: Iterable[Candidate] | Callable[[], Iterable[Candidate]],
        paths: Mapping[str, LocationSubPath],
        invalid_subtitle: str,
        optional: Optional[bool] = False,
    ) -> None:
        super().__init__()
        self.schema_key = schema_key
        self.candidates = candidates
        self.paths = paths
        self.invalid_subtitle = invalid_subtitle
        self.optional = optional

    def check_candidate(self, candidate: Path) -> bool:
        """Check if a candidate root has the necessary files and directories"""
        for segment, is_directory in self.paths.values():
            path = Path(candidate) / segment
            if is_directory:
                if not path.is_dir():
                    return False
            else:
                if not path.is_file():
                    return False
        return True

    def resolve(self) -> None:
        """Choose a root path from the candidates for the location.
        If none fits, raise an UnresolvableLocationError"""

        if self.root is not None:
            return

        # Get the schema candidate (an unset location is blank and must
        # fall through to the declared candidates: Path("") is Path(".")
        # and would wrongly resolve — and be written back — as the cwd)
        schema_candidate = shared.schema.get_string(self.schema_key)
        if isinstance(schema_candidate, str) and not schema_candidate.strip():
            schema_candidate = None

        # Candidates may be a zero-arg callable returning the roots, so
        # registry-derived roots are resolved lazily at scan time
        candidates = (
            self.candidates() if callable(self.candidates) else self.candidates
        )

        # Find the first matching candidate
        ordered = (
            [schema_candidate] if schema_candidate is not None else []
        )
        for candidate in (*ordered, *candidates):
            if isinstance(candidate, str) and not candidate.strip():
                continue
            candidate = Path(candidate).expanduser()
            if not self.check_candidate(candidate):
                continue
            self.root = candidate
            break
        else:
            # No good candidate found
            raise UnresolvableLocationError(self.optional)

        # Update the schema with the found candidate
        value = str(candidate)
        shared.schema.set_string(self.schema_key, value)
        logging.debug("Resolved value for schema key %s: %s", self.schema_key, value)

    def __getitem__(self, key: str) -> Optional[Path]:
        """Get the computed path from its key for the location"""
        try:
            self.resolve()
        except UnresolvableLocationError as error:
            if error.optional:
                return None
            raise UnresolvableLocationError from error

        if self.root:
            return self.root / self.paths[key].segment
        return None
