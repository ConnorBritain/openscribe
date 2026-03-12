"""
Vocabulary Management System
Handles custom vocabulary, corrections, and adaptive learning for OpenScribe
"""

import json
import re
import os
import csv
import threading
from typing import Dict, List, Optional, Tuple, Set, Any
from pathlib import Path
import difflib
from datetime import datetime
import uuid

try:
    import phonetics  # double metaphone
    PHONETICS_AVAILABLE = True
except Exception:
    PHONETICS_AVAILABLE = False

try:
    # Optional import; used only for path resolution
    from src.config import config
    CONFIG_AVAILABLE = True
except Exception:
    CONFIG_AVAILABLE = False


class VocabularyManager:
    """Manages custom vocabulary and learning from user corrections."""

    MEDICATION_MAPPING_MAX_TOKENS = 6

    MEDICATION_CONTEXT_WORDS = {
        "mg",
        "mcg",
        "milligram",
        "milligrams",
        "dose",
        "doses",
        "refill",
        "refills",
        "prescription",
        "prescriptions",
        "script",
        "scripts",
        "medication",
        "medications",
        "tablet",
        "tablets",
        "tab",
        "tabs",
        "capsule",
        "capsules",
        "prior",
        "authorization",
        "insurance",
        "approved",
        "prn",
        "bid",
        "tid",
        "qam",
        "qhs",
        "take",
        "taking",
        "on",
        "using",
        "start",
        "starting",
        "started",
        "switch",
        "switched",
    }

    MEDICATION_SHAPE_HINTS = (
        "jaro",
        "bound",
        "govi",
        "govy",
        "lutide",
        "statin",
        "sartan",
        "pril",
        "olol",
        "prazole",
        "xaban",
        "oxetine",
        "triptyline",
        "zepam",
        "gliflozin",
        "cycline",
        "mycin",
        "cillin",
        "floxacin",
    )

    MEDICATION_SALT_WORDS = {
        "hydrochloride",
        "hcl",
        "sodium",
        "potassium",
        "calcium",
        "acetate",
        "phosphate",
        "sulfate",
        "sulphate",
        "nitrate",
        "tartrate",
        "succinate",
        "fumarate",
        "maleate",
        "mesylate",
        "besylate",
        "benzoate",
        "carbonate",
        "citrate",
        "chloride",
        "bromide",
        "iodide",
        "gluconate",
        "hydrate",
        "monohydrate",
        "dihydrate",
        "trihydrate",
        "kit",
        "autoinjector",
        "injection",
        "solution",
        "tablet",
        "tablets",
        "capsule",
        "capsules",
        "extended",
        "release",
        "delayed",
        "and",
        "with",
        "w",
    }

    CONFIDENCE_RANK = {"low": 1, "medium": 2, "high": 3}
    
    def __init__(self, config_dir: str = "data"):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(exist_ok=True)
        
        # File paths
        self.vocabulary_file = self.config_dir / "user_vocabulary.json"
        self.corrections_log = self.config_dir / "corrections_log.json"
        self.learning_stats = self.config_dir / "learning_stats.json"
        self.medical_lexicon_cache = self.config_dir / "medical_lexicon.json"
        
        # In-memory storage
        self.custom_terms: Dict[str, List[str]] = {}
        self.correction_history: List[Dict] = []
        self.learning_patterns: Dict[str, int] = {}
        self.medication_mappings: Dict[str, Dict[str, Any]] = {}
        self.medication_review_queue: List[Dict[str, Any]] = []
        self.medication_rejections: Set[str] = set()
        self._med_mapping_index: Dict[int, Dict[str, Dict[str, Any]]] = {}
        self._med_mapping_lengths: List[int] = []

        # Medical lexicon structures
        self.medical_terms_set: Set[str] = set()  # lowercased canonical terms
        self.medical_canonical_map: Dict[str, str] = {}  # lower -> canonical (original case)
        self.medical_metaphone_index: Dict[str, List[str]] = {}  # metaphone -> list of canonical terms
        self._save_lock = threading.Lock()
        
        # Load existing data
        self.load_vocabulary()
        self.load_corrections()
        # Attempt to load medical lexicon from cache or source (opt-in via env)
        # Enable by setting environment variable CT_ENABLE_MEDICAL_LEXICON=1
        try:
            enable_med_lex = os.getenv("CT_ENABLE_MEDICAL_LEXICON", "0") == "1"
        except Exception:
            enable_med_lex = False
        if enable_med_lex:
            self._initialize_medical_lexicon()
    
    def load_vocabulary(self) -> None:
        """Load custom vocabulary from file."""
        try:
            # In pytest, avoid leaking real workspace vocabulary into tests that use globals
            if os.getenv("PYTEST_CURRENT_TEST") and str(self.config_dir) == "data":
                self.custom_terms = {}
                self.learning_patterns = {}
                self.medication_mappings = {}
                self.medication_review_queue = []
                self.medication_rejections = set()
                self._rebuild_medication_mapping_index()
                return

            if self.vocabulary_file.exists():
                with open(self.vocabulary_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.custom_terms = data.get('terms', {})
                    self.learning_patterns = data.get('patterns', {})
                    self.medication_mappings = data.get('medication_mappings', {})
                    self.medication_review_queue = data.get('medication_review_queue', [])
                    self.medication_rejections = set(data.get('medication_rejections', []))
            else:
                self.medication_mappings = {}
                self.medication_review_queue = []
                self.medication_rejections = set()
            self._rebuild_medication_mapping_index()
        except Exception as e:
            print(f"[VOCAB] Error loading vocabulary: {e}")
            self.custom_terms = {}
            self.learning_patterns = {}
            self.medication_mappings = {}
            self.medication_review_queue = []
            self.medication_rejections = set()
            self._rebuild_medication_mapping_index()
    
    def save_vocabulary(self) -> None:
        """Save current vocabulary to file."""
        try:
            with self._save_lock:
                # Merge with on-disk state to avoid stale-writer clobbering.
                on_disk: Dict[str, Any] = {}
                if self.vocabulary_file.exists():
                    try:
                        with open(self.vocabulary_file, 'r', encoding='utf-8') as f:
                            payload = json.load(f)
                        if isinstance(payload, dict):
                            on_disk = payload
                    except Exception:
                        on_disk = {}

                merged_mappings = self._merge_medication_mappings(
                    on_disk.get('medication_mappings', {}),
                    self.medication_mappings,
                )
                merged_reviews = self._merge_review_queue(
                    on_disk.get('medication_review_queue', []),
                    self.medication_review_queue,
                )
                merged_rejections = set(on_disk.get('medication_rejections', []) or set())
                merged_rejections.update(self.medication_rejections)

                # Keep in-memory state aligned with the merged persistent state.
                self.medication_mappings = merged_mappings
                self.medication_review_queue = merged_reviews
                self.medication_rejections = merged_rejections
                self._rebuild_medication_mapping_index()

                data = {
                    'terms': self.custom_terms,
                    'patterns': self.learning_patterns,
                    'medication_mappings': self.medication_mappings,
                    'medication_review_queue': self.medication_review_queue,
                    'medication_rejections': sorted(self.medication_rejections),
                    'last_updated': datetime.now().isoformat()
                }
                self._atomic_write_json(self.vocabulary_file, data)
        except Exception as e:
            print(f"[VOCAB] Error saving vocabulary: {e}")

    def _atomic_write_json(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(f"{path.suffix}.tmp.{os.getpid()}.{threading.get_ident()}")
        serialized = json.dumps(payload, indent=2, ensure_ascii=False)
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                f.write(serialized)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def _merge_medication_mappings(
        self,
        persisted: Any,
        current: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        merged: Dict[str, Dict[str, Any]] = {}
        if isinstance(persisted, dict):
            for observed, mapping in persisted.items():
                if isinstance(mapping, dict):
                    merged[str(observed)] = dict(mapping)

        for observed, mapping in (current or {}).items():
            if not isinstance(mapping, dict):
                continue
            observed_key = str(observed)
            existing = merged.get(observed_key)
            if existing is None:
                merged[observed_key] = dict(mapping)
                continue

            updated_existing = str(existing.get("last_updated") or existing.get("added_date") or "")
            updated_current = str(mapping.get("last_updated") or mapping.get("added_date") or "")
            # Prefer the row with the newer timestamp; union counters conservatively.
            winner = dict(mapping) if updated_current >= updated_existing else dict(existing)
            winner["occurrence_count"] = max(
                int(existing.get("occurrence_count", 0) or 0),
                int(mapping.get("occurrence_count", 0) or 0),
            )
            winner["entry_count"] = max(
                int(existing.get("entry_count", 0) or 0),
                int(mapping.get("entry_count", 0) or 0),
            )
            winner["usage_count"] = max(
                int(existing.get("usage_count", 0) or 0),
                int(mapping.get("usage_count", 0) or 0),
            )
            merged[observed_key] = winner
        return merged

    def _merge_review_queue(self, persisted: Any, current: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        by_id: Dict[str, Dict[str, Any]] = {}

        def _upsert(row: Dict[str, Any]) -> None:
            review_id = str(row.get("id") or "").strip()
            if not review_id:
                return
            existing = by_id.get(review_id)
            if existing is None:
                by_id[review_id] = dict(row)
                return

            existing_updated = str(existing.get("updated_at") or existing.get("resolved_at") or "")
            row_updated = str(row.get("updated_at") or row.get("resolved_at") or "")
            if row_updated >= existing_updated:
                winner = dict(row)
            else:
                winner = dict(existing)
            winner["occurrence_count"] = max(
                int(existing.get("occurrence_count", 0) or 0),
                int(row.get("occurrence_count", 0) or 0),
            )
            winner["entry_count"] = max(
                int(existing.get("entry_count", 0) or 0),
                int(row.get("entry_count", 0) or 0),
            )
            by_id[review_id] = winner

        if isinstance(persisted, list):
            for item in persisted:
                if isinstance(item, dict):
                    _upsert(item)

        for item in current or []:
            if isinstance(item, dict):
                _upsert(item)

        merged_rows = list(by_id.values())
        merged_rows.sort(
            key=lambda item: str(item.get("updated_at") or item.get("resolved_at") or item.get("created_at") or ""),
            reverse=True,
        )
        return merged_rows
    
    def load_corrections(self) -> None:
        """Load correction history from file."""
        try:
            if self.corrections_log.exists():
                with open(self.corrections_log, 'r', encoding='utf-8') as f:
                    self.correction_history = json.load(f)
        except Exception as e:
            print(f"[VOCAB] Error loading corrections: {e}")
            self.correction_history = []
    
    def save_corrections(self) -> None:
        """Save correction history to file."""
        try:
            with open(self.corrections_log, 'w', encoding='utf-8') as f:
                json.dump(self.correction_history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[VOCAB] Error saving corrections: {e}")

    def _normalize_lookup_phrase(self, value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").strip().lower())

    def _normalize_medication_variant(self, value: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9'\-\s]", " ", value or "")
        return self._normalize_lookup_phrase(cleaned)

    def _rebuild_medication_mapping_index(self) -> None:
        self._med_mapping_index = {}
        lengths: Set[int] = set()
        for observed, mapping in self.medication_mappings.items():
            phrase = self._normalize_medication_variant(observed)
            if not phrase:
                continue
            size = len(phrase.split())
            if size < 1 or size > self.MEDICATION_MAPPING_MAX_TOKENS:
                continue
            self._med_mapping_index.setdefault(size, {})[phrase] = mapping
            lengths.add(size)
        self._med_mapping_lengths = sorted(lengths, reverse=True)

    def _split_medication_alias_terms(self, term: str) -> List[str]:
        raw = self._normalize_lookup_phrase(term)
        if not raw:
            return []
        expanded = raw.replace("||", ";").replace("/", ";").replace(",", ";")
        aliases: List[str] = []
        for part in expanded.split(";"):
            normalized = self._normalize_lookup_phrase(part)
            if normalized and normalized != "unknown":
                aliases.append(normalized)
        return aliases

    def _derive_medication_aliases(self, term: str) -> Set[str]:
        aliases: Set[str] = set()
        for part in self._split_medication_alias_terms(term):
            tokens = re.findall(r"[a-z][a-z0-9'\-]*", part)
            if not tokens:
                continue
            while tokens and tokens[-1] in self.MEDICATION_SALT_WORDS:
                tokens.pop()
            if not tokens:
                continue
            collapsed = " ".join(tokens)
            aliases.add(collapsed)
            if len(tokens[0]) >= 4:
                aliases.add(tokens[0])
        return aliases

    def _looks_medication_like(self, token: str) -> bool:
        lower = self._normalize_lookup_phrase(token)
        if not lower:
            return False
        return any(hint in lower for hint in self.MEDICATION_SHAPE_HINTS)

    def _collect_medication_context_ranges(self, text: str) -> List[Tuple[int, int]]:
        if not text:
            return []
        ranges: List[Tuple[int, int]] = []
        words = list(re.finditer(r"[A-Za-z][A-Za-z'\-]*", text))
        lower_words = [match.group().lower() for match in words]

        for idx, match in enumerate(words):
            token = lower_words[idx]
            if token in self.MEDICATION_CONTEXT_WORDS:
                left_idx = max(0, idx - 4)
                right_idx = min(len(words) - 1, idx + 4)
                ranges.append((words[left_idx].start(), words[right_idx].end()))

        for match in re.finditer(
            r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|milligram|milligrams)\b",
            text,
            flags=re.IGNORECASE,
        ):
            ranges.append((max(0, match.start() - 25), min(len(text), match.end() + 30)))

        if not ranges:
            return []
        ranges.sort(key=lambda value: value[0])
        merged: List[Tuple[int, int]] = [ranges[0]]
        for start, end in ranges[1:]:
            prev_start, prev_end = merged[-1]
            if start <= prev_end + 6:
                merged[-1] = (prev_start, max(prev_end, end))
            else:
                merged.append((start, end))
        return merged

    def _is_span_in_ranges(self, start: int, end: int, ranges: List[Tuple[int, int]]) -> bool:
        for range_start, range_end in ranges:
            if start <= range_end and end >= range_start:
                return True
        return False

    def _preserve_phrase_case(self, original: str, replacement: str) -> str:
        if not original:
            return replacement
        if original.isupper():
            return replacement.upper()
        if original.islower():
            return replacement.lower()
        if original.istitle():
            return replacement.title()
        return replacement

    def _initialize_medical_lexicon(self) -> None:
        """Load medical lexicon from cache if available, otherwise try to build from FDA Products file.

        This is best-effort and non-fatal if resources are missing.
        """
        try:
            if self.medical_lexicon_cache.exists():
                with open(self.medical_lexicon_cache, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                terms = data.get('terms', [])
                self.medical_terms_set = set()
                self.medical_canonical_map = {}
                self.medical_metaphone_index = {}
                for term in terms:
                    self._index_medical_term_aliases(str(term))
                print(f"[VOCAB] Loaded medical lexicon cache with {len(self.medical_terms_set)} terms")
                return
        except Exception as e:
            print(f"[VOCAB] Error loading medical lexicon cache: {e}")

        # Build from FDA Products.txt if present
        possible_paths = [
            "src/Products.txt",
            "Products.txt",
        ]
        if CONFIG_AVAILABLE:
            # Also try resolved resources in packaged app
            possible_paths.append(config.resolve_resource_path("src/Products.txt"))
            possible_paths.append(config.resolve_resource_path("Products.txt"))

        source_path = None
        for p in possible_paths:
            try:
                if p and os.path.exists(p):
                    source_path = p
                    break
            except Exception:
                pass

        if source_path:
            try:
                count = self._load_medical_lexicon_from_fda_products(source_path)
                print(f"[VOCAB] Built medical lexicon from '{source_path}' with {count} unique terms")
                # Persist cache
                try:
                    with open(self.medical_lexicon_cache, 'w', encoding='utf-8') as f:
                        json.dump({
                            'terms': sorted(self.medical_canonical_map.values())
                        }, f, indent=2, ensure_ascii=False)
                except Exception as e:
                    print(f"[VOCAB] Error saving medical lexicon cache: {e}")
            except Exception as e:
                print(f"[VOCAB] Error building medical lexicon: {e}")
        else:
            # Silently skip if not available
            print("[VOCAB] FDA Products.txt not found - medical lexicon disabled")

    def _normalize_term(self, term: str) -> str:
        """Normalization for lexicon keys."""
        return re.sub(r"\s+", " ", term.strip()).lower()

    def _double_metaphone_all(self, term: str) -> List[str]:
        if not PHONETICS_AVAILABLE:
            return []
        try:
            code1, code2 = phonetics.dmetaphone(term)
            results = []
            if code1:
                results.append(code1)
            if code2 and code2 != code1:
                results.append(code2)
            return results
        except Exception:
            return []

    def _index_medical_term_aliases(self, term: str) -> None:
        aliases = self._derive_medication_aliases(term)
        for alias in aliases:
            normalized = self._normalize_lookup_phrase(alias)
            if not normalized:
                continue
            if normalized not in self.medical_canonical_map:
                self.medical_canonical_map[normalized] = normalized
            self.medical_terms_set.add(normalized)
            for mp in self._double_metaphone_all(normalized):
                if mp:
                    self.medical_metaphone_index.setdefault(mp, []).append(normalized)

    def _load_medical_lexicon_from_fda_products(self, products_path: str) -> int:
        """Parse FDA Products.txt (tab-delimited) and build a medical terms index.

        We index both brand names (DrugName) and active ingredients (ActiveIngredient).
        """
        unique_terms: Set[str] = set()

        with open(products_path, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.DictReader(f, delimiter='\t')
            for row in reader:
                drug_name = (row.get('DrugName') or '').strip()
                active_ing = (row.get('ActiveIngredient') or '').strip()

                # Add brand name
                if drug_name and drug_name.upper() != 'UNKNOWN':
                    unique_terms.add(drug_name)
                # Add active ingredients, possibly multiple separated by ';'
                if active_ing and active_ing.upper() != 'UNKNOWN':
                    # Split on separators like ';' and parentheses content
                    parts = [p.strip() for p in re.split(r"[;,+]", active_ing) if p.strip()]
                    if parts:
                        for p in parts:
                            # Remove composite descriptors like contents in parentheses
                            cleaned = re.sub(r"\([^\)]*\)", "", p).strip()
                            if cleaned:
                                unique_terms.add(cleaned)
                    else:
                        unique_terms.add(active_ing)

        # Build maps
        for term in unique_terms:
            self._index_medical_term_aliases(term)

        return len(self.medical_terms_set)
    
    def add_custom_term(self, correct_term: str, variations: Optional[List[str]] = None, 
                       category: str = "general") -> None:
        """Add a custom term with its variations."""
        if variations is None:
            variations = []
        
        # Ensure correct term is in the variations list
        if correct_term not in variations:
            variations.insert(0, correct_term)
        
        # Store with category prefix for organization
        key = f"{category}:{correct_term.lower()}"
        self.custom_terms[key] = {
            'correct': correct_term,
            'variations': variations,
            'category': category,
            'added_date': datetime.now().isoformat(),
            'usage_count': 0
        }
        
        self.save_vocabulary()
        print(f"[VOCAB] Added term: {correct_term} with {len(variations)} variations")

    def get_medication_mappings(self, search_filter: str = "", include_inactive: bool = False) -> List[Dict[str, Any]]:
        """Return medication correction mappings sorted by usage and frequency."""
        normalized_search = self._normalize_lookup_phrase(search_filter)
        records: List[Dict[str, Any]] = []
        for observed, mapping in self.medication_mappings.items():
            if not include_inactive and not mapping.get("active", True):
                continue
            canonical = str(mapping.get("canonical", "")).strip()
            if not canonical:
                continue
            if normalized_search:
                haystack = f"{observed} {canonical}".lower()
                if normalized_search not in haystack:
                    continue
            record = {
                "observed": observed,
                "canonical": canonical,
                "source": mapping.get("source", "manual"),
                "confidence": mapping.get("confidence", "manual"),
                "occurrence_count": int(mapping.get("occurrence_count", 0)),
                "entry_count": int(mapping.get("entry_count", 0)),
                "usage_count": int(mapping.get("usage_count", 0)),
                "active": bool(mapping.get("active", True)),
                "added_date": mapping.get("added_date", ""),
                "last_updated": mapping.get("last_updated", ""),
            }
            records.append(record)

        records.sort(
            key=lambda row: (
                -int(row.get("usage_count", 0)),
                -int(row.get("occurrence_count", 0)),
                row.get("observed", ""),
            )
        )
        return records

    def add_medication_mapping(
        self,
        observed: str,
        canonical: str,
        source: str = "manual",
        confidence: str = "manual",
        occurrence_count: int = 1,
        entry_count: int = 1,
        active: bool = True,
        save: bool = True,
    ) -> Dict[str, Any]:
        """Add or update a medication mapping."""
        observed_norm = self._normalize_medication_variant(observed)
        canonical_norm = self._normalize_medication_variant(canonical)
        if not observed_norm:
            raise ValueError("Observed term is required")
        if not canonical_norm:
            raise ValueError("Canonical term is required")
        observed_tokens = observed_norm.split()
        if len(observed_tokens) > self.MEDICATION_MAPPING_MAX_TOKENS:
            raise ValueError(
                f"Observed phrase can include at most {self.MEDICATION_MAPPING_MAX_TOKENS} words"
            )

        now = datetime.now().isoformat()
        existing = self.medication_mappings.get(observed_norm)
        if existing:
            existing["canonical"] = canonical_norm
            existing["source"] = source or existing.get("source", "manual")
            existing["confidence"] = confidence or existing.get("confidence", "manual")
            existing["occurrence_count"] = int(existing.get("occurrence_count", 0)) + max(1, int(occurrence_count))
            existing["entry_count"] = int(existing.get("entry_count", 0)) + max(1, int(entry_count))
            existing["active"] = bool(active)
            existing["last_updated"] = now
            mapping = existing
        else:
            mapping = {
                "canonical": canonical_norm,
                "source": source or "manual",
                "confidence": confidence or "manual",
                "occurrence_count": max(1, int(occurrence_count)),
                "entry_count": max(1, int(entry_count)),
                "usage_count": 0,
                "active": bool(active),
                "added_date": now,
                "last_updated": now,
            }
            self.medication_mappings[observed_norm] = mapping

        self._rebuild_medication_mapping_index()
        if save:
            self.save_vocabulary()
        return {
            "observed": observed_norm,
            "canonical": mapping["canonical"],
            "source": mapping.get("source", "manual"),
            "confidence": mapping.get("confidence", "manual"),
            "occurrence_count": int(mapping.get("occurrence_count", 0)),
            "entry_count": int(mapping.get("entry_count", 0)),
            "usage_count": int(mapping.get("usage_count", 0)),
            "active": bool(mapping.get("active", True)),
        }

    def delete_medication_mapping(self, observed: str) -> bool:
        observed_norm = self._normalize_medication_variant(observed)
        if observed_norm not in self.medication_mappings:
            return False
        del self.medication_mappings[observed_norm]
        self._rebuild_medication_mapping_index()
        self.save_vocabulary()
        return True

    def queue_medication_review(
        self,
        observed: str,
        suggested: str,
        confidence: str = "medium",
        evidence: str = "",
        occurrence_count: int = 1,
        entry_count: int = 1,
        sample_context: str = "",
        source: str = "analysis",
        save: bool = True,
    ) -> Dict[str, Any]:
        observed_norm = self._normalize_medication_variant(observed)
        suggested_norm = self._normalize_medication_variant(suggested)
        if not observed_norm or not suggested_norm:
            raise ValueError("Observed and suggested terms are required")
        if observed_norm in self.medication_rejections:
            return {
                "id": "",
                "observed": observed_norm,
                "suggested": suggested_norm,
                "status": "rejected",
                "skipped": True,
            }

        now = datetime.now().isoformat()
        for item in self.medication_review_queue:
            if (
                item.get("status") == "pending"
                and item.get("observed") == observed_norm
                and item.get("suggested") == suggested_norm
            ):
                item["occurrence_count"] = int(item.get("occurrence_count", 0)) + max(1, int(occurrence_count))
                item["entry_count"] = int(item.get("entry_count", 0)) + max(1, int(entry_count))
                item["updated_at"] = now
                if sample_context and not item.get("sample_context"):
                    item["sample_context"] = sample_context
                if save:
                    self.save_vocabulary()
                return item

        review_item = {
            "id": uuid.uuid4().hex,
            "observed": observed_norm,
            "suggested": suggested_norm,
            "confidence": confidence if confidence in self.CONFIDENCE_RANK else "medium",
            "evidence": evidence or "",
            "occurrence_count": max(1, int(occurrence_count)),
            "entry_count": max(1, int(entry_count)),
            "sample_context": sample_context or "",
            "source": source or "analysis",
            "status": "pending",
            "created_at": now,
            "updated_at": now,
        }
        self.medication_review_queue.append(review_item)
        if save:
            self.save_vocabulary()
        return review_item

    def get_medication_review_queue(self, status_filter: str = "pending") -> List[Dict[str, Any]]:
        status = self._normalize_lookup_phrase(status_filter or "")
        rows = []
        for item in self.medication_review_queue:
            if status and status != "all" and item.get("status") != status:
                continue
            rows.append(item)
        rows.sort(
            key=lambda item: (
                self.CONFIDENCE_RANK.get(str(item.get("confidence", "low")), 0),
                int(item.get("occurrence_count", 0)),
                int(item.get("entry_count", 0)),
            ),
            reverse=True,
        )
        return rows

    def resolve_medication_review(
        self,
        review_id: str,
        action: str,
        canonical_override: str = "",
    ) -> Optional[Dict[str, Any]]:
        if not review_id:
            return None
        normalized_action = self._normalize_lookup_phrase(action)
        if normalized_action not in {"accept", "reject", "dismiss"}:
            raise ValueError("Action must be accept, reject, or dismiss")

        target = None
        for item in self.medication_review_queue:
            if item.get("id") == review_id:
                target = item
                break
        if not target:
            return None

        now = datetime.now().isoformat()
        target["status"] = (
            "accepted" if normalized_action == "accept"
            else "rejected" if normalized_action == "reject"
            else "dismissed"
        )
        target["resolved_action"] = normalized_action
        target["resolved_at"] = now
        target["updated_at"] = now

        observed = str(target.get("observed") or "")
        if normalized_action == "accept":
            canonical = canonical_override or str(target.get("suggested") or "")
            self.add_medication_mapping(
                observed=observed,
                canonical=canonical,
                source="review_accept",
                confidence=str(target.get("confidence") or "medium"),
                occurrence_count=int(target.get("occurrence_count", 1)),
                entry_count=int(target.get("entry_count", 1)),
                save=False,
            )
        elif normalized_action == "reject" and observed:
            self.medication_rejections.add(observed)

        self.save_vocabulary()
        return target

    def import_medication_mappings_from_report(
        self,
        report_path: str,
        min_confidence: str = "medium",
        auto_import_confidence: str = "high",
        min_occurrence_count: int = 1,
        min_entry_count: int = 1,
    ) -> Dict[str, int]:
        path = Path(report_path)
        if not path.exists():
            raise FileNotFoundError(f"Report not found: {report_path}")

        min_rank = self.CONFIDENCE_RANK.get(self._normalize_lookup_phrase(min_confidence), 2)
        auto_rank = self.CONFIDENCE_RANK.get(self._normalize_lookup_phrase(auto_import_confidence), 3)

        row_re = re.compile(
            r"^\|\s*`(?P<observed>[^`]+)`\s*\|\s*`(?P<suggested>[^`]+)`\s*\|\s*`(?P<entries>\d+)`"
            r"\s*\|\s*`(?P<occurrences>\d+)`\s*\|\s*`(?P<confidence>high|medium|low)`\s*\|\s*`(?P<evidence>[^`]*)`\s*\|$",
            flags=re.IGNORECASE,
        )

        total_rows = 0
        imported = 0
        queued = 0
        skipped = 0

        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                match = row_re.match(line)
                if not match:
                    continue
                total_rows += 1
                observed = match.group("observed")
                suggested = match.group("suggested")
                confidence = match.group("confidence").lower()
                entry_count = int(match.group("entries"))
                occurrence_count = int(match.group("occurrences"))
                evidence = match.group("evidence")

                confidence_rank = self.CONFIDENCE_RANK.get(confidence, 0)
                if confidence_rank < min_rank:
                    skipped += 1
                    continue
                if occurrence_count < max(1, int(min_occurrence_count)):
                    skipped += 1
                    continue
                if entry_count < max(1, int(min_entry_count)):
                    skipped += 1
                    continue

                if confidence_rank >= auto_rank:
                    self.add_medication_mapping(
                        observed=observed,
                        canonical=suggested,
                        source="analysis_report",
                        confidence=confidence,
                        occurrence_count=occurrence_count,
                        entry_count=entry_count,
                        save=False,
                    )
                    imported += 1
                else:
                    self.queue_medication_review(
                        observed=observed,
                        suggested=suggested,
                        confidence=confidence,
                        evidence=evidence,
                        occurrence_count=occurrence_count,
                        entry_count=entry_count,
                        source="analysis_report",
                        save=False,
                    )
                    queued += 1

        self.save_vocabulary()
        return {
            "rows": total_rows,
            "imported": imported,
            "queued": queued,
            "skipped": skipped,
        }
    
    def learn_from_correction(self, original: str, corrected: str, context: str = "") -> bool:
        """Learn from a user correction."""
        if original.strip() == corrected.strip():
            return False
        
        # Log the correction
        correction_entry = {
            'original': original,
            'corrected': corrected,
            'context': context,
            'timestamp': datetime.now().isoformat(),
            'confidence': self._calculate_confidence(original, corrected)
        }
        
        self.correction_history.append(correction_entry)
        
        # Update learning patterns
        pattern_key = f"{original.lower()} -> {corrected.lower()}"
        self.learning_patterns[pattern_key] = self.learning_patterns.get(pattern_key, 0) + 1
        
        # If this correction appears frequently, add it as a custom term
        if self.learning_patterns[pattern_key] >= 2:  # After 2 corrections, make it permanent
            self._promote_to_custom_term(original, corrected)
        
        self.save_corrections()
        self.save_vocabulary()
        
        print(f"[VOCAB] Learned correction: '{original}' → '{corrected}' (count: {self.learning_patterns[pattern_key]})")
        return True
    
    def _calculate_confidence(self, original: str, corrected: str) -> float:
        """Calculate confidence score for a correction based on similarity."""
        similarity = difflib.SequenceMatcher(None, original.lower(), corrected.lower()).ratio()
        return round(similarity, 2)
    
    def _promote_to_custom_term(self, original: str, corrected: str) -> None:
        """Promote a frequently corrected term to custom vocabulary."""
        # Determine category based on context or content
        category = self._categorize_term(corrected)
        
        # Check if we already have this term
        existing_key = None
        for key, term_data in self.custom_terms.items():
            if term_data['correct'].lower() == corrected.lower():
                existing_key = key
                break
        
        if existing_key:
            # Add to existing variations
            if original not in self.custom_terms[existing_key]['variations']:
                self.custom_terms[existing_key]['variations'].append(original)
        else:
            # Create new term
            self.add_custom_term(corrected, [original], category)
    
    def _categorize_term(self, term: str) -> str:
        """Attempt to categorize a term based on patterns."""
        term_lower = term.lower()
        
        # Technical/medication patterns
        if any(suffix in term_lower for suffix in ['mycin', 'cillin', 'phen', 'zole', 'pine']):
            return "medication"
        
        # Professional titles
        if term.startswith(('Dr.', 'Doctor', 'Mr.', 'Mrs.', 'Ms.', 'Prof.', 'Professor')):
            return "names"
        
        # Technical procedures/conditions (common suffixes and specific terms)
        technical_patterns = ['itis', 'osis', 'emia', 'pathy', 'gram', 'scopy', 'monia', 'thorax', 'tension']
        if any(suffix in term_lower for suffix in technical_patterns):
            return "technical_terms"
        
        return "general"
    
    def apply_corrections(self, text: str) -> Tuple[str, List[Dict]]:
        """Apply vocabulary corrections to text and return corrected text + correction info."""
        corrected_text = text
        applied_corrections = []
        
        for key, term_data in self.custom_terms.items():
            correct_term = term_data['correct']
            variations = term_data['variations']
            
            for variation in variations:
                if variation.lower() in corrected_text.lower():
                    # Use regex for whole word replacement
                    pattern = r'\b' + re.escape(variation) + r'\b'
                    matches = list(re.finditer(pattern, corrected_text, re.IGNORECASE))
                    
                    for match in reversed(matches):  # Reverse to maintain positions
                        # Replace while preserving original case pattern
                        replacement = self._preserve_case(match.group(), correct_term)
                        corrected_text = corrected_text[:match.start()] + replacement + corrected_text[match.end():]
                        
                        applied_corrections.append({
                            'original': match.group(),
                            'corrected': replacement,
                            'position': match.start(),
                            'category': term_data['category']
                        })
                        
                        # Update usage count
                        self.custom_terms[key]['usage_count'] += 1
        
        if applied_corrections:
            self.save_vocabulary()  # Save updated usage counts
        
        # After custom-term corrections, try medical lexicon corrections for remaining tokens
        med_corrected, med_corrections = self.apply_medical_corrections(corrected_text)
        applied_corrections.extend(med_corrections)
        return med_corrected, applied_corrections

    def apply_medical_corrections(self, text: str) -> Tuple[str, List[Dict]]:
        """Apply medication-only corrections in high-likelihood medication contexts."""
        has_mapping_data = bool(self.medication_mappings)
        has_lexicon_data = bool(self.medical_terms_set)
        if not has_mapping_data and not has_lexicon_data:
            return text, []

        context_ranges = self._collect_medication_context_ranges(text)
        if not context_ranges:
            return text, []

        text_out = text
        corrections: List[Dict] = []

        if has_mapping_data:
            mapped_text, mapping_corrections = self._apply_medication_mapping_corrections(
                text_out,
                context_ranges,
            )
            text_out = mapped_text
            corrections.extend(mapping_corrections)

        if has_lexicon_data:
            lexicon_text, lexicon_corrections = self._apply_lexicon_corrections_in_context(
                text_out,
                context_ranges,
            )
            text_out = lexicon_text
            corrections.extend(lexicon_corrections)

        if corrections:
            self.save_vocabulary()
        return text_out, corrections

    def _apply_medication_mapping_corrections(
        self,
        text: str,
        context_ranges: List[Tuple[int, int]],
    ) -> Tuple[str, List[Dict[str, Any]]]:
        if not self.medication_mappings:
            return text, []

        tokens = list(re.finditer(r"[A-Za-z][A-Za-z'\-]*", text))
        replacements: List[Tuple[int, int, str]] = []
        corrections: List[Dict[str, Any]] = []
        i = 0
        while i < len(tokens):
            matched = False
            for n in self._med_mapping_lengths:
                if i + n > len(tokens):
                    continue
                start = tokens[i].start()
                end = tokens[i + n - 1].end()
                if not self._is_span_in_ranges(start, end, context_ranges):
                    continue
                phrase = " ".join(
                    self._normalize_medication_variant(tokens[i + offset].group())
                    for offset in range(n)
                ).strip()
                if not phrase:
                    continue
                mapping = self._med_mapping_index.get(n, {}).get(phrase)
                if not mapping:
                    continue
                if not mapping.get("active", True):
                    continue
                canonical = str(mapping.get("canonical", "")).strip()
                if not canonical:
                    continue

                original_text = text[start:end]
                replacement = self._preserve_phrase_case(original_text, canonical)
                if original_text.lower() == replacement.lower():
                    matched = True
                    i += n
                    break

                replacements.append((start, end, replacement))
                corrections.append(
                    {
                        "original": original_text,
                        "corrected": replacement,
                        "position": start,
                        "category": "medication",
                        "source": "mapping",
                    }
                )
                mapping["usage_count"] = int(mapping.get("usage_count", 0)) + 1
                mapping["last_used"] = datetime.now().isoformat()
                matched = True
                i += n
                break

            if not matched:
                i += 1

        if not replacements:
            return text, []

        text_out = text
        replacements.sort(key=lambda row: row[0], reverse=True)
        for start, end, replacement in replacements:
            text_out = text_out[:start] + replacement + text_out[end:]
        return text_out, corrections

    def _apply_lexicon_corrections_in_context(
        self,
        text: str,
        context_ranges: List[Tuple[int, int]],
    ) -> Tuple[str, List[Dict[str, Any]]]:
        tokens = list(re.finditer(r"[A-Za-z][A-Za-z'\-]*", text))
        if not tokens:
            return text, []

        replacements: List[Tuple[int, int, str]] = []
        corrections: List[Dict[str, Any]] = []

        def similarity(left: str, right: str) -> float:
            return difflib.SequenceMatcher(None, left.lower(), right.lower()).ratio()

        for token in tokens:
            start = token.start()
            end = token.end()
            if not self._is_span_in_ranges(start, end, context_ranges):
                continue

            original = token.group()
            normalized = self._normalize_medication_variant(original)
            if not normalized:
                continue
            if normalized in self.medication_rejections:
                continue
            if normalized in self.medication_mappings:
                # Mapping pass already handles explicit entries.
                continue

            if normalized in self.medical_terms_set:
                continue

            best_candidate = None
            best_score = 0.0

            if PHONETICS_AVAILABLE:
                metaphones = self._double_metaphone_all(normalized)
                candidate_pool: List[str] = []
                for mp in metaphones:
                    candidate_pool.extend(self.medical_metaphone_index.get(mp, []))
                seen = set()
                for candidate in candidate_pool:
                    if candidate in seen:
                        continue
                    seen.add(candidate)
                    score = similarity(normalized, candidate)
                    if score > best_score:
                        best_score = score
                        best_candidate = candidate

            if not best_candidate:
                close = difflib.get_close_matches(
                    normalized,
                    list(self.medical_terms_set),
                    n=1,
                    cutoff=0.0,
                )
                if close:
                    candidate = close[0]
                    score = similarity(normalized, candidate)
                    if score > best_score:
                        best_score = score
                        best_candidate = candidate

            if not best_candidate:
                continue

            med_shaped = self._looks_medication_like(normalized)
            threshold = 0.86
            if med_shaped:
                threshold = 0.70
            if best_score < threshold:
                continue

            replacement = self._preserve_phrase_case(original, best_candidate)
            if original.lower() == replacement.lower():
                continue

            replacements.append((start, end, replacement))
            corrections.append(
                {
                    "original": original,
                    "corrected": replacement,
                    "position": start,
                    "category": "medication",
                    "source": "lexicon",
                    "confidence": round(best_score, 2),
                }
            )

        if not replacements:
            return text, []

        text_out = text
        replacements.sort(key=lambda row: row[0], reverse=True)
        for start, end, replacement in replacements:
            text_out = text_out[:start] + replacement + text_out[end:]
        return text_out, corrections
    
    def _preserve_case(self, original: str, replacement: str) -> str:
        """Preserve the case pattern of the original when replacing."""
        if original.isupper():
            return replacement.upper()
        elif original.islower():
            return replacement.lower()
        elif original.istitle():
            return replacement.title()
        else:
            return replacement
    
    def suggest_corrections(self, text: str, max_suggestions: int = 3) -> List[Dict]:
        """Suggest possible corrections for text based on learned patterns."""
        suggestions = []
        words = text.split()
        
        for word in words:
            # Find close matches in our vocabulary
            best_matches = difflib.get_close_matches(
                word.lower(), 
                [term_data['correct'].lower() for term_data in self.custom_terms.values()],
                n=max_suggestions,
                cutoff=0.6
            )
            
            for match in best_matches:
                # Find the original term data
                for term_data in self.custom_terms.values():
                    if term_data['correct'].lower() == match:
                        suggestions.append({
                            'original': word,
                            'suggested': term_data['correct'],
                            'confidence': difflib.SequenceMatcher(None, word.lower(), match).ratio(),
                            'category': term_data['category'],
                            'usage_count': term_data['usage_count']
                        })
                        break
        
        # Sort by confidence and usage
        suggestions.sort(key=lambda x: (x['confidence'], x['usage_count']), reverse=True)
        return suggestions[:max_suggestions]
    
    def get_vocabulary_stats(self) -> Dict:
        """Get statistics about the vocabulary system."""
        categories = {}
        total_usage = 0
        
        for term_data in self.custom_terms.values():
            category = term_data['category']
            categories[category] = categories.get(category, 0) + 1
            total_usage += term_data['usage_count']
        
        return {
            'total_terms': len(self.custom_terms),
            'categories': categories,
            'total_corrections': len(self.correction_history),
            'total_usage': total_usage,
            'learning_patterns': len(self.learning_patterns)
        }
    
    def export_vocabulary(self, filepath: str) -> bool:
        """Export vocabulary to a shareable file."""
        try:
            export_data = {
                'vocabulary_export': {
                    'terms': self.custom_terms,
                    'export_date': datetime.now().isoformat(),
                    'stats': self.get_vocabulary_stats()
                }
            }
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            print(f"[VOCAB] Exported vocabulary to {filepath}")
            return True
        except Exception as e:
            print(f"[VOCAB] Error exporting vocabulary: {e}")
            return False
    
    def import_vocabulary(self, filepath: str, merge: bool = True) -> bool:
        """Import vocabulary from a file."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            imported_terms = data.get('vocabulary_export', {}).get('terms', {})
            
            if merge:
                # Merge with existing vocabulary
                self.custom_terms.update(imported_terms)
            else:
                # Replace existing vocabulary
                self.custom_terms = imported_terms
            
            self.save_vocabulary()
            print(f"[VOCAB] Imported {len(imported_terms)} terms from {filepath}")
            return True
        except Exception as e:
            print(f"[VOCAB] Error importing vocabulary: {e}")
            return False


# Global instance
_vocabulary_manager = None

def get_vocabulary_manager() -> VocabularyManager:
    """Get the global vocabulary manager instance."""
    global _vocabulary_manager
    if _vocabulary_manager is None:
        _vocabulary_manager = VocabularyManager()
    return _vocabulary_manager 
