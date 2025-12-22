import logging
import re
from typing import Dict, List, Optional, Tuple
import unicodedata

logger = logging.getLogger(__name__)


def _sanitize_bibtex_text(text: str) -> str:
    if not text:
        return text
    
    try:
        # Normalize unicode characters
        text = unicodedata.normalize('NFKD', text)
        
        # Replace common problematic characters
        replacements = {
            '"': "''",  # Smart quotes to regular quotes
            '"': "''",
            ''': "'",
            ''': "'",
            '–': '--',  # En dash
            '—': '---',  # Em dash
            '…': '...',
            '\u0080': '',  # Remove control characters
            '\u0081': '',
            '\u008f': '',
            '\u0090': '',
            '\u009d': '',
        }
        
        for old, new in replacements.items():
            text = text.replace(old, new)
        
        # Remove any remaining non-ASCII control characters
        text = ''.join(char for char in text if ord(char) >= 32 or char in '\n\t')
        
        # Encode to ASCII, ignore errors
        text = text.encode('ascii', 'ignore').decode('ascii')
        
        return text
    except Exception as e:
        logger.warning(f"Error sanitizing text: {e}")
        # Fallback: just remove non-ASCII
        return ''.join(char for char in text if ord(char) < 128)


def generate_bibtex(
    reference_data: Dict,
    is_complete: bool = True
) -> Tuple[str, bool]:

    try:
        ref_type = reference_data.get('reference_type', 'other')
        authors = reference_data.get('parsed_authors', [])
        year = reference_data.get('parsed_year')
        title = reference_data.get('parsed_title', '')
        journal = reference_data.get('parsed_journal', '')
        
        # Generate citation key (e.g., smith2023machine)
        citation_key = _generate_citation_key(authors, year, title)
        
        # Map reference_type to BibTeX entry type
        bibtex_type = _map_to_bibtex_type(ref_type)
        
        # Build BibTeX entry
        bibtex_lines = [f"@{bibtex_type}{{{citation_key},"]
        is_partial = False
        
        # Author field
        if authors and len(authors) > 0:
            # Sanitize each author name
            clean_authors = [_sanitize_bibtex_text(author) for author in authors]
            author_string = " and ".join(clean_authors)
            bibtex_lines.append(f"  author = {{{author_string}}},")
        else:
            bibtex_lines.append(f"  author = {{MISSING_AUTHOR}},")
            is_partial = True
        
        # Title field
        if title:
            clean_title = _sanitize_bibtex_text(title)
            bibtex_lines.append(f"  title = {{{clean_title}}},")
        else:
            bibtex_lines.append(f"  title = {{MISSING_TITLE}},")
            is_partial = True
        
        # Journal/Booktitle field
        if bibtex_type == 'article':
            if journal:
                clean_journal = _sanitize_bibtex_text(journal)
                bibtex_lines.append(f"  journal = {{{clean_journal}}},")
            else:
                bibtex_lines.append(f"  journal = {{MISSING_JOURNAL}},")
                is_partial = True
        elif bibtex_type == 'inproceedings':
            if journal:  # journal field bisa jadi conference name
                clean_journal = _sanitize_bibtex_text(journal)
                bibtex_lines.append(f"  booktitle = {{{clean_journal}}},")
            else:
                bibtex_lines.append(f"  booktitle = {{MISSING_CONFERENCE}},")
                is_partial = True
        elif bibtex_type == 'book':
            if journal:  # journal field bisa jadi publisher
                clean_journal = _sanitize_bibtex_text(journal)
                bibtex_lines.append(f"  publisher = {{{clean_journal}}},")
            else:
                bibtex_lines.append(f"  publisher = {{MISSING_PUBLISHER}},")
                is_partial = True
        
        # Year field
        if year:
            bibtex_lines.append(f"  year = {{{year}}},")
        else:
            bibtex_lines.append(f"  year = {{MISSING_YEAR}},")
            is_partial = True
        
        # Optional fields: Volume, Number, Pages
        # Extract dari reference_data jika ada
        parsed_volume = reference_data.get('parsed_volume')
        parsed_issue = reference_data.get('parsed_issue')
        parsed_pages = reference_data.get('parsed_pages')
        
        # Untuk journal article, tambahkan volume/number/pages jika ada
        if bibtex_type == 'article':
            if parsed_volume:
                bibtex_lines.append(f"  volume = {{{parsed_volume}}},")
            elif not is_complete:
                bibtex_lines.append(f"  volume = {{MISSING}},")
                is_partial = True
            
            if parsed_issue:
                bibtex_lines.append(f"  number = {{{parsed_issue}}},")
            elif not is_complete:
                bibtex_lines.append(f"  number = {{MISSING}},")
                is_partial = True
            
            if parsed_pages:
                # Format pages dengan double dash untuk BibTeX
                clean_pages = parsed_pages.replace('-', '--')
                bibtex_lines.append(f"  pages = {{{clean_pages}}},")
            elif not is_complete:
                bibtex_lines.append(f"  pages = {{MISSING}},")
                is_partial = True
        
        # Remove trailing comma dari line terakhir
        if bibtex_lines[-1].endswith(','):
            bibtex_lines[-1] = bibtex_lines[-1][:-1]
        
        # Close BibTeX entry
        bibtex_lines.append("}")
        
        bibtex_string = "\n".join(bibtex_lines)
        
        logger.info(f"Generated BibTeX for '{citation_key}' (partial={is_partial})")
        return bibtex_string, is_partial
        
    except Exception as e:
        logger.error(f"Error generating BibTeX: {e}", exc_info=True)
        return f"% Error generating BibTeX: {e}", True


def generate_correct_format_example(
    authors: List[str],
    year: int,
    title: str,
    journal: str,
    style: str,
    volume: Optional[str] = "10",
    issue: Optional[str] = "2",
    pages: Optional[str] = "1-10"
) -> str:

    try:
        # Ambil author pertama untuk contoh
        first_author = authors[0] if authors else "Smith, J."
        
        # Parse nama (handle berbagai format)
        author_last, author_init = _parse_author_name(first_author)
        
        style_upper = style.upper()
        
        if style_upper == "APA":
            # APA: Author, A. A. (Year). Title of article. Journal Name, volume(issue), pages.
            return f"{author_last}, {author_init} ({year}). {title}. {journal}, {volume}({issue}), {pages}."
        
        elif style_upper == "IEEE":
            # IEEE: [1] A. A. Author, "Title of article," Journal Name, vol. X, no. Y, pp. Z-Z, Year.
            return f'[1] {author_init} {author_last}, "{title}," {journal}, vol. {volume}, no. {issue}, pp. {pages}, {year}.'
        
        elif style_upper == "MLA":
            # MLA: Author, First. "Title of Article." Journal Name, vol. X, no. Y, Year, pp. Z-Z.
            return f'{author_last}, {author_init} "{title}." {journal}, vol. {volume}, no. {issue}, {year}, pp. {pages}.'
        
        elif style_upper == "HARVARD":
            # Harvard: Author, A. (Year) 'Title of article', Journal Name, volume(issue), pp. Z-Z.
            return f"{author_last}, {author_init} ({year}) '{title}', {journal}, {volume}({issue}), pp. {pages}."
        
        elif style_upper == "CHICAGO":
            # Chicago: Author, First. Year. "Title of Article." Journal Name volume (issue): pages.
            return f'{author_last}, {author_init} {year}. "{title}." {journal} {volume} ({issue}): {pages}.'
        
        else:
            # Default fallback ke APA
            return f"{author_last}, {author_init} ({year}). {title}. {journal}, {volume}({issue}), {pages}."
    
    except Exception as e:
        logger.error(f"Error generating format example: {e}", exc_info=True)
        return f"Error generating example format: {e}"


def _generate_citation_key(authors: List[str], year: Optional[int], title: str) -> str:

    try:
        # Get first author's last name
        if authors and len(authors) > 0:
            first_author = authors[0]
            # Extract last name (ambil kata pertama sebelum koma atau spasi)
            last_name = re.split(r'[,\s]+', first_author.strip())[0]
            last_name = re.sub(r'[^a-zA-Z]', '', last_name).lower()
        else:
            last_name = "unknown"
        
        # Get year
        year_str = str(year) if year else "2024"
        
        # Get first word of title
        if title:
            # Remove special characters, ambil kata pertama
            title_clean = re.sub(r'[^a-zA-Z\s]', '', title)
            first_word = title_clean.strip().split()[0].lower() if title_clean.strip() else "article"
        else:
            first_word = "article"
        
        citation_key = f"{last_name}{year_str}{first_word}"
        
        # Limit panjang key maksimal 30 karakter
        if len(citation_key) > 30:
            citation_key = citation_key[:30]
        
        return citation_key
    
    except Exception as e:
        logger.warning(f"Error generating citation key: {e}")
        return "unknown2024article"


def _map_to_bibtex_type(reference_type: str) -> str:
    
    mapping = {
        'journal': 'article',
        'conference': 'inproceedings',
        'book': 'book',
        'book series': 'book',
        'preprint': 'article',
        'website': 'misc',
        'report': 'techreport',
        'other': 'misc'
    }
    
    return mapping.get(reference_type.lower(), 'misc')


def _parse_author_name(author_string: str) -> Tuple[str, str]:

    try:
        # Handle format: "Last, F. M."
        if ',' in author_string:
            parts = author_string.split(',')
            last_name = parts[0].strip()
            initials = parts[1].strip() if len(parts) > 1 else "A."
        else:
            # Handle format: "F. M. Last" atau "First Middle Last"
            parts = author_string.strip().split()
            if len(parts) >= 2:
                last_name = parts[-1]
                # Ambil initial dari nama depan
                first_initials = [p[0] + '.' for p in parts[:-1] if p]
                initials = ' '.join(first_initials)
            else:
                last_name = parts[0] if parts else "Unknown"
                initials = "A."
        
        return last_name, initials
    
    except Exception as e:
        logger.warning(f"Error parsing author name '{author_string}': {e}")
        return "Unknown", "A."
