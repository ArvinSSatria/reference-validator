import logging
import re
import pandas as pd
import difflib
import pickle
import os
from functools import lru_cache
from pathlib import Path
from config import Config

logger = logging.getLogger(__name__)

# Global database Scopus
SCOPUS_DATA = {
    "by_title": {},
    "by_cleaned_title": {}
}

# Search statistics untuk monitoring
SCOPUS_SEARCH_STATS = {
    'total_searches': 0,
    'cache_hits': 0,
    'matches_found': 0,
    'top_queries': {}
}

# Common journal abbreviations mapping (sama seperti Scimago)
COMMON_ABBREVIATIONS = {
    "j.": "journal",
    "jrnl.": "journal",
    "proc.": "proceedings",
    "proceedings": "proceedings",
    "trans.": "transactions",
    "int.": "international",
    "intl.": "international",
    "comp.": "computing",
    "comput.": "computing",
    "computer": "computing",
    "computation": "computing",
    "computational": "computing",
    "evol.": "evolutionary",
    "intell.": "intelligence",
    "sci.": "science",
    "sciences": "science",
    "tech.": "technology",
    "technol.": "technology",
    "softw.": "software",
    "softw": "software",
    "res.": "research",
    "rev.": "review",
    "lett.": "letters",
    "bull.": "bulletin",
    "ann.": "annals",
    "eur.": "european",
    "amer.": "american",
    "acad.": "academy",
    "soc.": "society",
    "assoc.": "association",
    "appl.": "applied",
    "theor.": "theoretical",
    "pract.": "practice",
    "practice": "practice",
    "exp.": "experience",
    "experience": "experience",
    "inf.": "information",
    "information": "information",
    "syst.": "systems",
    "system": "systems",
    "mach.": "machine",
    "learn.": "learning",
    "eng.": "engineering",
    "med.": "medicine",
    "phys.": "physics",
    "chem.": "chemistry",
    "biol.": "biology",
    "math.": "mathematics",
    "stat.": "statistics",
    "educ.": "education",
    "psych.": "psychology",
    "geol.": "geology",
    "astron.": "astronomy",
    "econ.": "economics",
    "mgmt.": "management",
    "admin.": "administration"
}

def expand_abbreviations(text):
    if not text:
        return ""
    
    words = text.lower().split()
    expanded = []
    
    for word in words:
        word_clean = word.rstrip('.')
        if word in COMMON_ABBREVIATIONS:
            expanded.append(COMMON_ABBREVIATIONS[word])
        elif word_clean in COMMON_ABBREVIATIONS:
            expanded.append(COMMON_ABBREVIATIONS[word_clean])
        else:
            expanded.append(word)
    
    return ' '.join(expanded)


def clean_scopus_title(title):
    if not isinstance(title, str):
        return ""

    expanded = expand_abbreviations(title)
    
    s = expanded.lower()
    
    # Remove parenthetical content
    s = re.sub(r'\([^)]*\)', '', s)
    s = re.sub(r'[^a-z0-9]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    
    # Remove common generic suffixes
    generic_suffixes = ['journal', 'proceedings', 'magazine', 'bulletin', 'letters']
    words = s.split()
    
    if len(words) > 2 and words[-1] in generic_suffixes:
        words = words[:-1]
        s = ' '.join(words)
    
    # Normalize word variants
    word_normalizations = {
        'computation': 'computing',
        'computational': 'computing',
        'computer': 'computing',
        'informatics': 'information',
        'informatic': 'information',
    }
    
    words = s.split()
    normalized_words = []
    for word in words:
        normalized_words.append(word_normalizations.get(word, word))
    
    return ' '.join(normalized_words)


def load_scopus_data():
    global SCOPUS_DATA
    
    # Setup paths - menggunakan file scopus
    csv_file = Path("scopus 2025.csv")
    cache_file = csv_file.with_suffix('.scopus.pkl')
    
    # Try loading from cache first
    if cache_file.exists() and csv_file.exists():
        try:
            cache_mtime = cache_file.stat().st_mtime
            csv_mtime = csv_file.stat().st_mtime
            
            if cache_mtime > csv_mtime:
                with open(cache_file, 'rb') as f:
                    SCOPUS_DATA = pickle.load(f)
                logger.info(f"✅ Scopus dataset loaded from cache: {len(SCOPUS_DATA['by_title'])} journals (fast mode)")
                return
        except Exception as e:
            logger.warning(f"⚠️ Scopus cache load failed, rebuilding from CSV: {e}")
    
    # Load from CSV
    try:
        logger.info("📥 Loading Scopus data from CSV...")
        df = pd.read_csv(csv_file, sep=';', encoding='utf-8')
        required_cols = ['Sourcerecord ID', 'Source Title', 'Active or Inactive', 'Source Type']
        
        if all(col in df.columns for col in required_cols):
            # Filter hanya yang Active
            df = df[df['Active or Inactive'].str.strip().str.lower() == 'active']
            df.dropna(subset=['Source Title', 'Sourcerecord ID'], inplace=True)
            
            for _, row in df.iterrows():
                title = str(row['Source Title']).strip()
                source_id = str(row['Sourcerecord ID'])
                source_type = str(row['Source Type']).strip().lower()
                
                # Ambil publisher untuk membantu disambiguasi
                publisher = str(row.get('Publisher', '')).strip() if 'Publisher' in row else ''

                journal_info = {
                    'id': source_id,
                    'title': title,
                    'type': source_type,
                    'status': 'active',
                    'publisher': publisher
                }

                # Untuk by_title, jika ada duplikat nama, simpan sebagai list
                title_lower = title.lower()
                if title_lower in SCOPUS_DATA["by_title"]:
                    # Ada duplikat - convert ke list jika belum
                    existing = SCOPUS_DATA["by_title"][title_lower]
                    if not isinstance(existing, list):
                        SCOPUS_DATA["by_title"][title_lower] = [existing]
                    SCOPUS_DATA["by_title"][title_lower].append(journal_info)
                else:
                    SCOPUS_DATA["by_title"][title_lower] = journal_info
                
                cleaned_title = clean_scopus_title(title)
                
                # Untuk cleaned title juga handle duplikat
                if cleaned_title in SCOPUS_DATA["by_cleaned_title"]:
                    existing = SCOPUS_DATA["by_cleaned_title"][cleaned_title]
                    if not isinstance(existing, list):
                        SCOPUS_DATA["by_cleaned_title"][cleaned_title] = [existing]
                    SCOPUS_DATA["by_cleaned_title"][cleaned_title].append(journal_info)
                else:
                    SCOPUS_DATA["by_cleaned_title"][cleaned_title] = journal_info
                
            logger.info(f"✅ Scopus dataset loaded from CSV: {len(SCOPUS_DATA['by_title'])} journals")
            
            # Save to cache
            try:
                with open(cache_file, 'wb') as f:
                    pickle.dump(SCOPUS_DATA, f)
                logger.info(f"💾 Scopus cache saved to {cache_file.name} for faster future loads")
            except Exception as e:
                logger.warning(f"⚠️ Scopus cache save failed (non-critical): {e}")
                
        else:
            logger.error(f"❌ Required columns not found in Scopus CSV file")
    except Exception as e:
        logger.error(f"❌ Error loading Scopus database: {e}")


@lru_cache(maxsize=1000)
def search_journal_in_scopus(journal_name):
    # Update statistics
    SCOPUS_SEARCH_STATS['total_searches'] += 1
    if journal_name in SCOPUS_SEARCH_STATS['top_queries']:
        SCOPUS_SEARCH_STATS['top_queries'][journal_name] += 1
    else:
        SCOPUS_SEARCH_STATS['top_queries'][journal_name] = 1
    
    if not journal_name or not SCOPUS_DATA["by_cleaned_title"]:
        return False, None

    cleaned_journal_name = clean_scopus_title(journal_name)
    expanded_query = cleaned_journal_name

    # Layer 1: Exact match
    if expanded_query in SCOPUS_DATA["by_cleaned_title"]:
        SCOPUS_SEARCH_STATS['matches_found'] += 1
        logger.debug(f"✅ SCOPUS LAYER 1 (EXACT): '{journal_name}'")
        result = SCOPUS_DATA["by_cleaned_title"][expanded_query]
        # Handle multiple matches
        result = select_best_match_from_list(result)
        return True, result
    
    query_words = set(expanded_query.split())
    query_words_list = expanded_query.split()
    if len(query_words) == 0:
        return False, None

    stopwords = {'of', 'the', 'and', 'for', 'in', 'on', 'a', 'an', 'to'}
    important_query_words = query_words - stopwords
    
    # Layer 2: Exact word match
    for title_db, info in SCOPUS_DATA["by_cleaned_title"].items():
        db_words = set(title_db.split())
        db_words_list = title_db.split()
        important_db_words = db_words - stopwords

        if not important_query_words.issubset(important_db_words):
            continue

        if len(query_words) > len(db_words):
            continue
        
        important_overlap = len(important_query_words & important_db_words)
        important_db_count = len(important_db_words)
        
        if important_db_count > 0:
            coverage_ratio = important_overlap / important_db_count
            if len(important_query_words) < len(important_db_words):
                if coverage_ratio < 0.80:
                    continue
        
        try:
            positions = []
            for qword in query_words_list:
                if qword in db_words_list:
                    positions.append(db_words_list.index(qword))
                else:
                    raise ValueError("Word not found")
            
            if positions != sorted(positions):
                continue
                
        except (ValueError, IndexError):
            continue
        
        SCOPUS_SEARCH_STATS['matches_found'] += 1
        logger.debug(f"✅ SCOPUS LAYER 2 (EXACT WORD MATCH): '{journal_name}' → '{title_db}'")
        # Handle multiple matches
        result = select_best_match_from_list(info)
        return True, result
    
    # Layer 3: Fuzzy match (typo tolerance)
    best_match_info = None
    best_match_title = None
    highest_score = 0.0
    
    query_len = len(expanded_query)
    if query_len <= 10:
        min_threshold = 0.95
    elif query_len <= 20:
        min_threshold = 0.92
    else:
        min_threshold = 0.90
    
    for title_db, info in SCOPUS_DATA["by_cleaned_title"].items():
        db_words = set(title_db.split())
        db_words_list = title_db.split()
        if not db_words:
            continue
    
        seq_ratio = difflib.SequenceMatcher(None, expanded_query, title_db).ratio()
        
        if seq_ratio >= min_threshold and seq_ratio > highest_score:
            common_words = query_words.intersection(db_words)
            overlap_ratio = len(common_words) / len(query_words) if query_words else 0
            
            if overlap_ratio < 0.85:
                continue
            
            stopwords_check = {'of', 'the', 'and', 'for', 'in', 'on', 'a', 'an', 'to'}
            important_query = query_words - stopwords_check
            important_db = db_words - stopwords_check
            
            missing_important = important_query - important_db
            if len(missing_important) > 0:
                if seq_ratio < 0.95:
                    continue

            try:
                positions = []
                for qword in query_words_list:
                    if qword in db_words_list:
                        positions.append(db_words_list.index(qword))
                
                if len(positions) >= 2:
                    if positions != sorted(positions):
                        continue
                        
            except (ValueError, IndexError):
                pass
            
            highest_score = seq_ratio
            best_match_info = info
            best_match_title = title_db
    
    if best_match_info:
        SCOPUS_SEARCH_STATS['matches_found'] += 1
        logger.debug(f"✅ SCOPUS LAYER 3 (FUZZY - TYPO): '{journal_name}' → '{best_match_title}' (score={highest_score:.3f})")
        # Handle multiple matches
        result = select_best_match_from_list(best_match_info)
        return True, result
    else:
        logger.debug(f"❌ SCOPUS NO MATCH: '{journal_name}' → best_score={highest_score:.3f}, threshold={min_threshold:.2f}")
    
    return False, None


def get_scopus_search_statistics():
    total = max(1, SCOPUS_SEARCH_STATS['total_searches'])
    cache_info = search_journal_in_scopus.cache_info()
    
    return {
        'total_searches': SCOPUS_SEARCH_STATS['total_searches'],
        'cache_hits': cache_info.hits,
        'cache_misses': cache_info.misses,
        'cache_hit_rate': cache_info.hits / max(1, cache_info.hits + cache_info.misses),
        'match_rate': SCOPUS_SEARCH_STATS['matches_found'] / total,
        'top_10_queries': sorted(
            SCOPUS_SEARCH_STATS['top_queries'].items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:10]
    }


def select_best_match_from_list(matches):
    """
    Jika ada multiple matches (misalnya Microbiology dengan negara berbeda),
    pilih yang paling relevan. Untuk saat ini, kita pilih yang pertama,
    tapi bisa ditingkatkan dengan scoring berdasarkan publisher, dll.
    
    Args:
        matches: Single dict or list of dicts
    
    Returns:
        Single dict (best match)
    """
    if isinstance(matches, list):
        if len(matches) == 1:
            return matches[0]
        # Jika ada multiple, log warning dan return yang pertama
        titles = [m.get('title', 'Unknown') for m in matches]
        logger.debug(f"⚠️ Multiple matches found: {titles}")
        logger.debug(f"   Returning first match: {matches[0].get('title')}")
        return matches[0]
    else:
        return matches

# Load data saat module di-import
load_scopus_data()
