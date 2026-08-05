"""The MCP server: three tools over the retrieval that already exists.

A protocol wrapper, deliberately thin. No retrieval logic lives here — every
question about ranking, expansion or citation is answered in
`imat_rag.index.search`, and this module only decides what a host agent is
allowed to ask for.

`coverage` is a tool rather than a resource because it is the answer to a
question the agent must ask *before* trusting an empty search: a course with
no material returns nothing, and nothing must not be read as "not in the
literature".
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from contextlib import redirect_stdout
from typing import Any

from imat_rag.config import Paths
from imat_rag.coverage import CourseCoverage
from imat_rag.coverage import coverage as report_coverage
from imat_rag.index.embed import EmbedConfig, Encoder, load_encoder
from imat_rag.index.search import Hit, Neighbourhood
from imat_rag.index.search import fetch as fetch_chunk
from imat_rag.index.search import search as run_search

SERVER_NAME = "imat-rag"

INSTRUCTIONS = """\
Retrieval over the reading list of the MIA master's degree. It returns
passages from the course books, cited to book, section and page; it never
writes the answer.

Call `coverage` before concluding that something is absent: several courses
have no material indexed at all, and an empty `search` result for one of them
says nothing about the literature. Call `fetch` with a `chunk_id` from a
search result to read the sections either side of it.\
"""


def build_server(
    paths: Paths,
    *,
    encoder: Encoder | None = None,
    config: EmbedConfig | None = None,
    loader: Callable[[EmbedConfig], Encoder] | None = None,
) -> Any:
    """Assemble the server. The encoder is injected, or loaded once on demand.

    Lazily, and exactly once: BGE-M3 is ~2.2 GB, so loading it per call would
    make the server unusable, and loading it at startup would make `coverage`
    — which needs no model at all — wait for a download.
    """
    # Lazy: mcp pulls a web stack, and every other command must stay instant.
    # pylint: disable=import-outside-toplevel
    from mcp.server.mcpserver import MCPServer

    settings = config or EmbedConfig()
    load = loader or load_encoder
    held: dict[str, Encoder] = {}
    if encoder is not None:
        held["encoder"] = encoder

    def encoder_for_queries() -> Encoder:
        if "encoder" not in held:
            # Under stdio, stdout is the JSON-RPC wire. Anything the model
            # stack prints while loading — progress bars, download notices —
            # would be read as a malformed message, so it goes to stderr.
            with redirect_stdout(sys.stderr):
                held["encoder"] = load(settings)
        return held["encoder"]

    server = MCPServer(name=SERVER_NAME, instructions=INSTRUCTIONS)

    @server.tool()
    def search(query: str, course: str = "", k: int = 8) -> list[Hit]:
        """Find passages answering a question, cited to book, section and page.

        `course` scopes the search to one subject code (DRL, GI, IAP, IM, MD,
        MGP, MP, IAG, EE). Queries may be in Spanish or English regardless of
        the language of the books. An empty result means this corpus does not
        contain the answer — check `coverage` before concluding more.
        """
        return run_search(
            paths,
            query,
            limit=k,
            course=course,
            encoder=encoder_for_queries(),
            config=settings,
        )

    @server.tool()
    def fetch(chunk_id: str) -> Neighbourhood:
        """Read a passage again together with the sections either side of it.

        Takes a `chunk_id` from a search result. Use it to follow a derivation
        or argument past the edges of the passage that matched.
        """
        found = fetch_chunk(paths, chunk_id)
        if found is None:
            raise ValueError(
                f"no chunk {chunk_id!r} in this corpus — "
                "chunk_id must come from a search result"
            )
        return found

    @server.tool()
    def coverage() -> list[CourseCoverage]:
        """Report what each course has indexed, and what it does not.

        A course with `indexed: false` has no material at all, so questions
        about it cannot be answered from this corpus.
        """
        return report_coverage(paths)

    return server


def serve(paths: Paths, transport: str = "stdio") -> None:
    """Run the server until the host disconnects."""
    build_server(paths).run(transport=transport)
