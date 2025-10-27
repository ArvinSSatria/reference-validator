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

# Global database Scimago
SCIMAGO_DATA = {
    "by_title": {},
    "by_cleaned_title": {}
}

# Search statistics untuk monitoring
SEARCH_STATS = {
    'total_searches': 0,
    'cache_hits': 0,
    'matches_found': 0,
    'top_queries': {}
}

# Common journal abbreviations mapping
COMMON_ABBREVIATIONS = {
    "j.": "journal",
    "jrnl.": "journal",
    "proc.": "proceedings",
    "proceedings": "proceedings",
    "trans.": "transactions",
    "int.": "international",
    "intl.": "international",
    "comp.": "computing",
    "comput.": "computing",  # FIXED: 'computer' → 'computing'
    "evol.": "evolutionary",  # ADDED: untuk 'Evol. Intell.' dan 'Swarm Evol. Comput.'
    "intell.": "intelligence",  # ADDED: untuk 'Evol. Intell.'
    "sci.": "science",
    "tech.": "technology",
    "technol.": "technology",  # ADDED: untuk 'Inf. Softw. Technol.'
    "softw.": "software",  # ADDED: untuk 'IEEE Trans. Softw. Eng.'
    "softw": "software",   # ADDED: untuk 'Softw' setelah punctuation removal
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
    "pract.": "practical",
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
        # Try with and without trailing dot
        word_clean = word.rstrip('.')
        if word in COMMON_ABBREVIATIONS:
            expanded.append(COMMON_ABBREVIATIONS[word])
        elif word_clean in COMMON_ABBREVIATIONS:
            expanded.append(COMMON_ABBREVIATIONS[word_clean])
        else:
            expanded.append(word)
    
    return ' '.join(expanded)


def clean_scimago_title(title):
    if not isinstance(title, str):
        return ""

    expanded = expand_abbreviations(title)
    
    s = expanded.lower()
    s = re.sub(r'[^a-z0-9]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    
    # Remove common generic suffixes that don't help matching
    # (e.g., "Applied Soft Computing Journal" → "Applied Soft Computing")
    generic_suffixes = ['journal', 'proceedings', 'magazine', 'bulletin', 'letters']
    words = s.split()
    
    # Only remove if it's the last word and there are more than 2 words
    if len(words) > 2 and words[-1] in generic_suffixes:
        words = words[:-1]
        s = ' '.join(words)
    
    # Normalize word variants to common form (for better matching)
    # Example: "computing" and "computation" → "computing"
    word_normalizations = {
        'computation': 'computing',
        'computational': 'computing',
        'computer': 'computing',  # Already handled but ensure consistency
    }
    
    words = s.split()
    normalized_words = []
    for word in words:
        normalized_words.append(word_normalizations.get(word, word))
    
    return ' '.join(normalized_words)


def load_scimago_data():
    global SCIMAGO_DATA
    
    # Setup paths
    csv_file = Path(Config.SCIMAGO_FILE_PATH)
    cache_file = csv_file.with_suffix('.pkl')
    
    # Try loading from cache first
    if cache_file.exists() and csv_file.exists():
        try:
            cache_mtime = cache_file.stat().st_mtime
            csv_mtime = csv_file.stat().st_mtime
            
            # Cache is valid if newer than CSV
            if cache_mtime > csv_mtime:
                with open(cache_file, 'rb') as f:
                    SCIMAGO_DATA = pickle.load(f)
                logger.info(f"✅ Dataset loaded from cache: {len(SCIMAGO_DATA['by_title'])} journals (fast mode)")
                return
        except Exception as e:
            logger.warning(f"⚠️ Cache load failed, rebuilding from CSV: {e}")
    
    # Load from CSV (slower)
    try:
        logger.info("📥 Loading Scimago data from CSV...")
        df = pd.read_csv(csv_file, sep=';', encoding='utf-8')
        required_cols = ['Sourceid', 'Title', 'Type', 'SJR Best Quartile']
        
        if all(col in df.columns for col in required_cols):
            df.dropna(subset=required_cols, inplace=True)
            
            for _, row in df.iterrows():
                title = row['Title'].strip()
                source_id = row['Sourceid']
                quartile = row['SJR Best Quartile']
                source_type = row['Type'].strip().lower()

                journal_info = {
                    'id': source_id,
                    'title': title,  # ADDED: Store original title
                    'quartile': quartile,
                    'type': source_type
                }

                SCIMAGO_DATA["by_title"][title.lower()] = journal_info
                cleaned_title = clean_scimago_title(title)
                SCIMAGO_DATA["by_cleaned_title"][cleaned_title] = journal_info
                
            logger.info(f"✅ Dataset loaded from CSV: {len(SCIMAGO_DATA['by_title'])} journals")
            
            # Save to cache for next time
            try:
                with open(cache_file, 'wb') as f:
                    pickle.dump(SCIMAGO_DATA, f)
                logger.info(f"💾 Cache saved to {cache_file.name} for faster future loads")
            except Exception as e:
                logger.warning(f"⚠️ Cache save failed (non-critical): {e}")
                
        else:
            logger.error(f"❌ Required columns not found in CSV file")
    except Exception as e:
        logger.error(f"❌ Error loading Scimago database: {e}")


@lru_cache(maxsize=1000)
def search_journal_in_scimago(journal_name):
    # Update statistics
    SEARCH_STATS['total_searches'] += 1
    if journal_name in SEARCH_STATS['top_queries']:
        SEARCH_STATS['top_queries'][journal_name] += 1
    else:
        SEARCH_STATS['top_queries'][journal_name] = 1
    
    if not journal_name or not SCIMAGO_DATA["by_cleaned_title"]:
        return False, None

    cleaned_journal_name = clean_scimago_title(journal_name)
    # Note: clean_scimago_title() already calls expand_abbreviations() internally
    # So we use cleaned_journal_name directly, not expand_abbreviations(cleaned_journal_name)
    expanded_query = cleaned_journal_name

    if expanded_query in SCIMAGO_DATA["by_cleaned_title"]:
        SEARCH_STATS['matches_found'] += 1
        logger.debug(f"✅ LAYER 1 (EXACT): '{journal_name}'")
        return True, SCIMAGO_DATA["by_cleaned_title"][expanded_query]
    
    query_words = set(expanded_query.split())
    query_words_list = expanded_query.split()  # Preserve order
    if len(query_words) == 0:
        return False, None

    stopwords = {'of', 'the', 'and', 'for', 'in', 'on', 'a', 'an', 'to'}
    
    # Kata-kata penting (non-stopword) yang HARUS ada
    important_query_words = query_words - stopwords
    
    for title_db, info in SCIMAGO_DATA["by_cleaned_title"].items():
        db_words = set(title_db.split())
        db_words_list = title_db.split()
        important_db_words = db_words - stopwords

        if not important_query_words.issubset(important_db_words):
            continue  # Skip - ada kata yang tidak match

        if len(query_words) > len(db_words):
            continue
        
        try:
            positions = []
            for qword in query_words_list:
                if qword in db_words_list:
                    # Cari posisi pertama kata ini di database title
                    positions.append(db_words_list.index(qword))
                else:
                    # Kata tidak ditemukan
                    raise ValueError("Word not found")
            
            # VALIDASI: Posisi harus monoton increasing (urutan benar)
            if positions != sorted(positions):
                continue  # Skip - urutan salah
                
        except (ValueError, IndexError):
            continue
        
        if len(query_words) < len(db_words):
            important_overlap = len(important_query_words & important_db_words)
            important_db_count = len(important_db_words)
            
            if important_db_count > 0:
                ratio = important_overlap / important_db_count
                if ratio < 0.70:
                    continue  # Subset terlalu kecil, skip
        
        # Jika semua validasi passed, ini adalah match yang valid
        SEARCH_STATS['matches_found'] += 1
        logger.debug(f"✅ LAYER 2 (EXACT WORD MATCH): '{journal_name}' → '{title_db}'")
        return True, info
    
    best_match_info = None
    best_match_title = None
    highest_score = 0.0
    
    query_len = len(expanded_query)
    if query_len <= 10:
        min_threshold = 0.95  # Sangat ketat untuk query pendek
    elif query_len <= 20:
        min_threshold = 0.92  # Ketat untuk query sedang
    else:
        min_threshold = 0.90  # Agak fleksibel untuk query panjang
    
    for title_db, info in SCIMAGO_DATA["by_cleaned_title"].items():
        db_words = set(title_db.split())
        db_words_list = title_db.split()
        if not db_words:
            continue
    
        seq_ratio = difflib.SequenceMatcher(None, expanded_query, title_db).ratio()
        
        if seq_ratio >= min_threshold and seq_ratio > highest_score:
            common_words = query_words.intersection(db_words)
            overlap_ratio = len(common_words) / len(query_words) if query_words else 0
            
            if overlap_ratio < 0.85:
                continue  # Overlap terlalu rendah
            
            # VALIDASI CRITICAL: Cek apakah ada kata penting yang BERBEDA
            # Mencegah "information" match ke "food" meskipun similarity tinggi
            stopwords_check = {'of', 'the', 'and', 'for', 'in', 'on', 'a', 'an', 'to'}
            important_query = query_words - stopwords_check
            important_db = db_words - stopwords_check
            
            # Jika ada kata penting di query yang TIDAK ada di DB, ini BUKAN typo!
            # Contoh: "Annual Review of Information..." vs "Annual Review of Food..."
            # "information" tidak ada dalam DB, sehingga ini bukan typo biasa
            missing_important = important_query - important_db
            if len(missing_important) > 0:
                # Ada kata penting yang hilang - hanya accept jika SEMUA kata yang hilang
                # adalah typo minor (edit distance kecil)
                # Untuk kasus "information" vs "food", ini akan gagal karena beda total
                # Hanya accept jika similarity SANGAT tinggi (>0.95) yang berarti pure typo
                if seq_ratio < 0.95:
                    continue  # Bukan typo, ada kata yang memang berbeda, skip

            try:
                positions = []
                for qword in query_words_list:
                    if qword in db_words_list:
                        positions.append(db_words_list.index(qword))
                    else:

                        pass
                
                if len(positions) >= 2:
                    if positions != sorted(positions):
                        continue
                        
            except (ValueError, IndexError):
                pass
            
            highest_score = seq_ratio
            best_match_info = info
            best_match_title = title_db
    
    if best_match_info:
        SEARCH_STATS['matches_found'] += 1
        logger.debug(f"✅ LAYER 3 (FUZZY - TYPO): '{journal_name}' → '{best_match_title}' (score={highest_score:.3f})")
        return True, best_match_info
    else:
        logger.debug(f"❌ NO MATCH: '{journal_name}' → best_score={highest_score:.3f}, threshold={min_threshold:.2f}")
    
    return False, None


def get_search_statistics():
    total = max(1, SEARCH_STATS['total_searches'])
    cache_info = search_journal_in_scimago.cache_info()
    
    return {
        'total_searches': SEARCH_STATS['total_searches'],
        'cache_hits': cache_info.hits,
        'cache_misses': cache_info.misses,
        'cache_hit_rate': cache_info.hits / max(1, cache_info.hits + cache_info.misses),
        'match_rate': SEARCH_STATS['matches_found'] / total,
        'top_10_queries': sorted(
            SEARCH_STATS['top_queries'].items(), 
            key=lambda x: x[1], 
            reverse=True
        )[:10]
    }

load_scimago_data()