"""Wiki Ingester for franchise canon knowledge.

Ingests franchise knowledge from local JSON/markdown dumps or MediaWiki API
into the CanonDB vector store. Handles entity-aware chunking with sentence
boundary detection and source authority classification.
"""

import json
import re
import logging
from pathlib import Path
from typing import Optional

from src.rag.canon_db import CanonDB

logger = logging.getLogger(__name__)

SOURCE_AUTHORITY: dict[str, float] = {
    "primary_canon": 1.0,
    "secondary_canon": 0.85,
    "reference_book": 0.7,
    "fan_maintained": 0.4,
    "ambiguous": 0.3,
}


def _slugify(text: str) -> str:
    """Convert a title to a URL-safe slug for chunk IDs."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s-]+", "_", slug)
    return slug[:80]


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences at period/question/exclamation boundaries.

    Preserves abbreviations and decimal numbers by requiring whitespace
    after sentence-ending punctuation.
    """
    # Split on sentence-ending punctuation followed by whitespace and uppercase
    # or end of string, but keep the punctuation with the sentence.
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"])", text)
    return [s.strip() for s in parts if s.strip()]


class WikiIngester:
    """Ingests franchise wiki content into the CanonDB vector store.

    Supports two input formats:
    - Local JSON dumps: files with {title, sections, categories, source_class}
    - Local markdown files: title from filename, sections split by ## headings

    Optionally supports fetching from MediaWiki API (e.g., Wookieepedia).
    """

    def __init__(self, canon_db: CanonDB):
        self.canon_db = canon_db

    def ingest_local_dump(
        self,
        dump_path: str,
        default_source_class: str = "fan_maintained",
    ) -> int:
        """Process JSON and markdown files from a local dump directory.

        JSON format expected:
            {
                "title": "Article Title",
                "sections": [{"heading": "Section", "text": "Content..."}],
                "categories": ["Category:Films"],
                "source_class": "primary_canon"  # optional
            }

        Markdown format:
            Filename becomes the title. Sections split by ## headings.

        Args:
            dump_path: Path to directory containing JSON/markdown files.
            default_source_class: Fallback source class if not specified.

        Returns:
            Total number of chunks ingested.
        """
        dump_dir = Path(dump_path)
        if not dump_dir.exists():
            raise FileNotFoundError(f"Dump path does not exist: {dump_path}")

        total_chunks = 0

        # Process JSON files
        for json_file in dump_dir.glob("*.json"):
            try:
                with open(json_file, encoding="utf-8") as f:
                    article = json.load(f)

                title = article.get("title", json_file.stem)
                sections = article.get("sections", [])
                categories = article.get("categories", [])
                source_class = article.get("source_class", None)

                if source_class is None:
                    source_class = self._classify_source(title, categories)
                    if source_class == "fan_maintained":
                        source_class = default_source_class

                # Combine sections into article text with headings
                article_text = ""
                for section in sections:
                    heading = section.get("heading", "")
                    text = section.get("text", "")
                    if heading:
                        article_text += f"## {heading}\n\n"
                    article_text += text + "\n\n"

                metadata = {
                    "source_article": title,
                    "source_section": "",
                    "entity_type": "",
                    "canon_era": "",
                    "continuity_status": "canon",
                    "source_class": source_class,
                }

                chunks = self._chunk_article(article_text, title, metadata)
                if chunks:
                    self.canon_db.add_chunks(chunks)
                    total_chunks += len(chunks)

                logger.info(
                    "Ingested %d chunks from %s (%s)",
                    len(chunks), title, source_class,
                )

            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Skipping %s: %s", json_file, e)

        # Process markdown files
        for md_file in dump_dir.glob("*.md"):
            try:
                text = md_file.read_text(encoding="utf-8")
                title = md_file.stem.replace("_", " ").replace("-", " ").title()

                metadata = {
                    "source_article": title,
                    "source_section": "",
                    "entity_type": "",
                    "canon_era": "",
                    "continuity_status": "canon",
                    "source_class": default_source_class,
                }

                chunks = self._chunk_article(text, title, metadata)
                if chunks:
                    self.canon_db.add_chunks(chunks)
                    total_chunks += len(chunks)

                logger.info(
                    "Ingested %d chunks from markdown: %s",
                    len(chunks), title,
                )

            except OSError as e:
                logger.warning("Skipping %s: %s", md_file, e)

        return total_chunks

    def ingest_from_api(
        self,
        article_titles: list[str],
        api_url: str = "https://starwars.fandom.com/api.php",
        source_class: str = "fan_maintained",
    ) -> int:
        """Fetch articles via MediaWiki API and ingest into canon DB.

        Uses the MediaWiki action=parse API to retrieve article HTML,
        then extracts text content for chunking.

        Args:
            article_titles: List of article titles to fetch.
            api_url: MediaWiki API endpoint URL.
            source_class: Source authority class for these articles.

        Returns:
            Total number of chunks ingested.
        """
        try:
            import httpx
        except ImportError:
            logger.error("httpx required for API ingestion. Install with: pip install httpx")
            return 0

        total_chunks = 0

        for title in article_titles:
            try:
                params = {
                    "action": "parse",
                    "page": title,
                    "format": "json",
                    "prop": "wikitext|categories",
                }

                response = httpx.get(api_url, params=params, timeout=30.0)
                response.raise_for_status()
                data = response.json()

                if "error" in data:
                    logger.warning(
                        "API error for '%s': %s",
                        title, data["error"].get("info", "Unknown error"),
                    )
                    continue

                parse_data = data.get("parse", {})
                wikitext = parse_data.get("wikitext", {}).get("*", "")
                categories = [
                    cat.get("*", "")
                    for cat in parse_data.get("categories", [])
                ]

                # Strip wiki markup (basic cleanup)
                clean_text = self._strip_wikitext(wikitext)

                actual_source_class = self._classify_source(title, categories)
                if actual_source_class == "fan_maintained":
                    actual_source_class = source_class

                metadata = {
                    "source_article": title,
                    "source_section": "",
                    "entity_type": "",
                    "canon_era": "",
                    "continuity_status": "canon",
                    "source_class": actual_source_class,
                }

                chunks = self._chunk_article(clean_text, title, metadata)
                if chunks:
                    self.canon_db.add_chunks(chunks)
                    total_chunks += len(chunks)

                logger.info("Ingested %d chunks from API: %s", len(chunks), title)

            except Exception as e:
                logger.warning("Failed to fetch '%s': %s", title, e)

        return total_chunks

    def _chunk_article(
        self,
        article_text: str,
        article_title: str,
        metadata: dict,
    ) -> list[dict]:
        """Entity-aware chunking at 500-700 words with 100-150 word overlap.

        Splits at sentence boundaries to avoid breaking mid-sentence.
        Attaches metadata to each chunk and generates deterministic IDs.

        Args:
            article_text: Full article text (may contain ## headings).
            article_title: Article title for chunk ID generation.
            metadata: Base metadata dict to attach to each chunk.

        Returns:
            List of chunk dicts ready for CanonDB.add_chunks().
        """
        if not article_text.strip():
            return []

        target_min_words = 500
        target_max_words = 700
        overlap_min_words = 100
        overlap_max_words = 150
        overlap_target = (overlap_min_words + overlap_max_words) // 2

        # Parse sections from headings
        sections = self._parse_sections(article_text)
        slug = _slugify(article_title)
        chunks = []
        chunk_idx = 0

        for section_heading, section_text in sections:
            sentences = _split_sentences(section_text)
            if not sentences:
                continue

            current_sentences: list[str] = []
            current_word_count = 0

            for sentence in sentences:
                sentence_words = len(sentence.split())
                current_sentences.append(sentence)
                current_word_count += sentence_words

                if current_word_count >= target_min_words:
                    # Emit chunk
                    chunk_text = " ".join(current_sentences)
                    chunk_meta = {
                        **metadata,
                        "source_section": section_heading,
                    }
                    chunks.append({
                        "id": f"{slug}_chunk_{chunk_idx:03d}",
                        "text": chunk_text,
                        "metadata": chunk_meta,
                    })
                    chunk_idx += 1

                    # Compute overlap: take trailing sentences up to overlap target
                    overlap_sentences: list[str] = []
                    overlap_words = 0
                    for s in reversed(current_sentences):
                        s_words = len(s.split())
                        if overlap_words + s_words > overlap_max_words:
                            break
                        overlap_sentences.insert(0, s)
                        overlap_words += s_words
                        if overlap_words >= overlap_target:
                            break

                    current_sentences = overlap_sentences
                    current_word_count = overlap_words

            # Emit remaining text as final chunk for this section
            if current_sentences:
                chunk_text = " ".join(current_sentences)
                # Only emit if it has meaningful content (more than just overlap)
                if len(chunk_text.split()) > overlap_target // 2 or chunk_idx == 0:
                    chunk_meta = {
                        **metadata,
                        "source_section": section_heading,
                    }
                    chunks.append({
                        "id": f"{slug}_chunk_{chunk_idx:03d}",
                        "text": chunk_text,
                        "metadata": chunk_meta,
                    })
                    chunk_idx += 1

        return chunks

    def _parse_sections(self, text: str) -> list[tuple[str, str]]:
        """Parse text into (heading, body) tuples based on ## headings.

        Args:
            text: Article text potentially containing ## headings.

        Returns:
            List of (heading, body_text) tuples. If no headings found,
            returns a single tuple with empty heading.
        """
        lines = text.split("\n")
        sections: list[tuple[str, str]] = []
        current_heading = ""
        current_lines: list[str] = []

        for line in lines:
            heading_match = re.match(r"^##\s+(.+)$", line.strip())
            if heading_match:
                # Save previous section
                if current_lines:
                    body = "\n".join(current_lines).strip()
                    if body:
                        sections.append((current_heading, body))
                current_heading = heading_match.group(1).strip()
                current_lines = []
            else:
                current_lines.append(line)

        # Save final section
        if current_lines:
            body = "\n".join(current_lines).strip()
            if body:
                sections.append((current_heading, body))

        return sections if sections else [("", text.strip())]

    def _classify_source(self, article_title: str, categories: list[str]) -> str:
        """Heuristic classification of article source authority.

        Examines article title and categories to determine the source class.

        Args:
            article_title: The article title.
            categories: List of category strings from the article.

        Returns:
            Source class string matching SOURCE_AUTHORITY keys.
        """
        combined = " ".join(categories).lower() + " " + article_title.lower()

        # Check for primary canon indicators
        primary_keywords = ["film", "television", "tv series", "movie", "theatrical"]
        if any(kw in combined for kw in primary_keywords):
            return "primary_canon"

        # Check for secondary canon indicators
        secondary_keywords = ["novel", "comic", "video game", "game"]
        if any(kw in combined for kw in secondary_keywords):
            return "secondary_canon"

        # Check for reference material
        reference_keywords = ["reference book", "encyclopedia", "sourcebook", "guide"]
        if any(kw in combined for kw in reference_keywords):
            return "reference_book"

        return "fan_maintained"

    def _strip_wikitext(self, wikitext: str) -> str:
        """Basic wikitext markup cleanup for plain text extraction.

        Args:
            wikitext: Raw MediaWiki wikitext.

        Returns:
            Cleaned plain text.
        """
        text = wikitext

        # Remove templates {{...}}
        text = re.sub(r"\{\{[^}]*\}\}", "", text)
        # Remove [[File:...]] and [[Image:...]]
        text = re.sub(r"\[\[(File|Image):[^\]]*\]\]", "", text)
        # Convert [[Link|Display]] to Display, and [[Link]] to Link
        text = re.sub(r"\[\[[^|\]]*\|([^\]]*)\]\]", r"\1", text)
        text = re.sub(r"\[\[([^\]]*)\]\]", r"\1", text)
        # Remove external links [http://... Display] -> Display
        text = re.sub(r"\[https?://[^\s\]]+ ([^\]]*)\]", r"\1", text)
        text = re.sub(r"\[https?://[^\]]*\]", "", text)
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", "", text)
        # Convert wiki headings to ## headings
        text = re.sub(r"^={2,}\s*(.+?)\s*={2,}$", r"## \1", text, flags=re.MULTILINE)
        # Remove bold/italic markup
        text = re.sub(r"'{2,3}", "", text)
        # Collapse whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()
