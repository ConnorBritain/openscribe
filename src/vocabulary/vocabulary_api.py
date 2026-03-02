"""
Vocabulary API for Frontend-Backend Communication
Provides functions that can be called from the main app to handle vocabulary operations
"""

from pathlib import Path
from typing import Callable, Dict, List, Optional, Any
from .vocabulary_manager import get_vocabulary_manager
from .medication_autolearn import (
    MedicationAutoLearnService,
    get_global_medication_autolearn_service,
)


CommandHandler = Callable[[Dict[str, Any]], Dict[str, Any]]


class VocabularyAPI:
    """API interface for vocabulary management operations."""
    
    def __init__(self):
        self.vocab_manager = get_vocabulary_manager()
        self._medication_autolearn_service: Optional[MedicationAutoLearnService] = None
        self._command_handlers = self._build_command_handlers()

    def set_medication_autolearn_service(self, service: Optional[MedicationAutoLearnService]) -> None:
        """Inject a specific auto-learn service instance (primarily for tests)."""
        self._medication_autolearn_service = service

    def _get_medication_autolearn_service(self) -> MedicationAutoLearnService:
        if self._medication_autolearn_service is not None:
            return self._medication_autolearn_service

        service = get_global_medication_autolearn_service()
        if service is not None:
            self._medication_autolearn_service = service
            return service

        raise RuntimeError(
            "Medication auto-learn service is not initialized. "
            "Start the application backend before calling this API."
        )
    
    def add_term(self, correct_term: str, variations: List[str], category: str = "general") -> Dict[str, Any]:
        """Add a new custom term."""
        try:
            self.vocab_manager.add_custom_term(correct_term, variations, category)
            return {
                "success": True,
                "message": f"Added term '{correct_term}' with {len(variations)} variations"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_vocabulary_list(self, search_filter: str = "", category_filter: str = "") -> Dict[str, Any]:
        """Get the current vocabulary list with optional filtering."""
        try:
            terms = []
            for key, term_data in self.vocab_manager.custom_terms.items():
                # Apply filters
                if search_filter and search_filter.lower() not in term_data['correct'].lower():
                    continue
                if category_filter and term_data['category'] != category_filter:
                    continue
                
                terms.append({
                    'key': key,
                    'correct': term_data['correct'],
                    'variations': term_data['variations'],
                    'category': term_data['category'],
                    'usage_count': term_data['usage_count'],
                    'added_date': term_data.get('added_date', '')
                })
            
            # Sort by usage count (most used first), then alphabetically
            terms.sort(key=lambda x: (-x['usage_count'], x['correct'].lower()))
            
            return {
                "success": True,
                "terms": terms,
                "total_count": len(terms)
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_vocabulary_stats(self) -> Dict[str, Any]:
        """Get vocabulary statistics."""
        try:
            stats = self.vocab_manager.get_vocabulary_stats()
            return {
                "success": True,
                "stats": stats
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def edit_term(self, term_key: str, category: str = None, additional_variations: List[str] = None, remove_variations: List[str] = None) -> Dict[str, Any]:
        """Edit an existing vocabulary term by adding/removing variations or changing category."""
        try:
            if term_key not in self.vocab_manager.custom_terms:
                return {
                    "success": False,
                    "error": "Term not found"
                }
            
            term_data = self.vocab_manager.custom_terms[term_key]
            term_name = term_data['correct']
            changes_made = []
            
            # Update category if provided
            if category and category != term_data['category']:
                old_category = term_data['category']
                term_data['category'] = category
                changes_made.append(f"category changed from '{old_category}' to '{category}'")
            
            # Remove variations if specified
            if remove_variations:
                removed_variations = []
                for variation in remove_variations:
                    if variation in term_data['variations']:
                        term_data['variations'].remove(variation)
                        removed_variations.append(variation)
                
                if removed_variations:
                    changes_made.append(f"removed {len(removed_variations)} variations: {', '.join(removed_variations)}")
            
            # Add new variations if provided
            if additional_variations:
                # Filter out empty variations and duplicates
                new_variations = [v.strip() for v in additional_variations if v.strip()]
                existing_variations = set(v.lower() for v in term_data['variations'])
                
                added_variations = []
                for variation in new_variations:
                    if variation.lower() not in existing_variations:
                        term_data['variations'].append(variation)
                        existing_variations.add(variation.lower())
                        added_variations.append(variation)
                
                if added_variations:
                    changes_made.append(f"added {len(added_variations)} new variations: {', '.join(added_variations)}")
            
            if changes_made:
                self.vocab_manager.save_vocabulary()
                return {
                    "success": True,
                    "message": f"Updated term '{term_name}': {'; '.join(changes_made)}"
                }
            else:
                return {
                    "success": True,
                    "message": f"No changes made to term '{term_name}'"
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def delete_term(self, term_key: str) -> Dict[str, Any]:
        """Delete a vocabulary term."""
        try:
            if term_key in self.vocab_manager.custom_terms:
                term_name = self.vocab_manager.custom_terms[term_key]['correct']
                del self.vocab_manager.custom_terms[term_key]
                self.vocab_manager.save_vocabulary()
                return {
                    "success": True,
                    "message": f"Deleted term '{term_name}'"
                }
            else:
                return {
                    "success": False,
                    "error": "Term not found"
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def import_template(self, template_name: str) -> Dict[str, Any]:
        """Import a vocabulary template."""
        try:
            template_path = Path(f"data/vocabulary_templates/{template_name}.json")
            
            if not template_path.exists():
                return {
                    "success": False,
                    "error": f"Template '{template_name}' not found"
                }
            
            success = self.vocab_manager.import_vocabulary(str(template_path), merge=True)
            
            if success:
                return {
                    "success": True,
                    "message": f"Successfully imported '{template_name}' template"
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to import template"
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def export_vocabulary(self, filepath: str) -> Dict[str, Any]:
        """Export vocabulary to a file."""
        try:
            success = self.vocab_manager.export_vocabulary(filepath)
            
            if success:
                return {
                    "success": True,
                    "message": f"Vocabulary exported to {filepath}"
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to export vocabulary"
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def clear_vocabulary(self) -> Dict[str, Any]:
        """Clear all vocabulary terms."""
        try:
            term_count = len(self.vocab_manager.custom_terms)
            self.vocab_manager.custom_terms = {}
            self.vocab_manager.learning_patterns = {}
            self.vocab_manager.save_vocabulary()
            
            return {
                "success": True,
                "message": f"Cleared {term_count} vocabulary terms"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def learn_correction(self, original: str, corrected: str, context: str = "") -> Dict[str, Any]:
        """Learn from a user correction."""
        try:
            learned = self.vocab_manager.learn_from_correction(original, corrected, context)
            
            if learned:
                return {
                    "success": True,
                    "message": f"Learned correction: '{original}' → '{corrected}'"
                }
            else:
                return {
                    "success": True,
                    "message": "No correction needed (terms are identical)"
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_suggestions(self, text: str, max_suggestions: int = 3) -> Dict[str, Any]:
        """Get correction suggestions for text."""
        try:
            suggestions = self.vocab_manager.suggest_corrections(text, max_suggestions)
            
            return {
                "success": True,
                "suggestions": suggestions
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    @staticmethod
    def _as_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off"}:
            return False
        return default

    def get_medication_mappings(
        self,
        search_filter: str = "",
        include_inactive: bool = False,
    ) -> Dict[str, Any]:
        """Return medication mappings."""
        try:
            mappings = self.vocab_manager.get_medication_mappings(
                search_filter=search_filter,
                include_inactive=self._as_bool(include_inactive, default=False),
            )
            return {
                "success": True,
                "mappings": mappings,
                "total_count": len(mappings),
                "active_count": sum(1 for row in mappings if row.get("active", True)),
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def add_medication_mapping(
        self,
        observed: str,
        canonical: str,
        source: str = "manual",
        confidence: str = "manual",
        occurrence_count: int = 1,
        entry_count: int = 1,
        active: bool = True,
    ) -> Dict[str, Any]:
        """Add/update a medication mapping."""
        try:
            mapping = self.vocab_manager.add_medication_mapping(
                observed=observed,
                canonical=canonical,
                source=source or "manual",
                confidence=confidence or "manual",
                occurrence_count=max(1, int(occurrence_count)),
                entry_count=max(1, int(entry_count)),
                active=self._as_bool(active, default=True),
                save=True,
            )
            return {
                "success": True,
                "message": f"Saved medication mapping: '{mapping['observed']}' -> '{mapping['canonical']}'",
                "mapping": mapping,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def delete_medication_mapping(self, observed: str) -> Dict[str, Any]:
        """Delete a medication mapping."""
        try:
            deleted = self.vocab_manager.delete_medication_mapping(observed)
            if not deleted:
                return {
                    "success": False,
                    "error": "Medication mapping not found",
                }
            return {
                "success": True,
                "message": f"Deleted medication mapping for '{observed}'",
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def get_medication_review_queue(self, status_filter: str = "pending") -> Dict[str, Any]:
        """Return medication review queue rows."""
        try:
            queue = self.vocab_manager.get_medication_review_queue(status_filter=status_filter or "pending")
            return {
                "success": True,
                "reviews": queue,
                "total_count": len(queue),
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def resolve_medication_review(
        self,
        review_id: str,
        action: str,
        canonical_override: str = "",
    ) -> Dict[str, Any]:
        """Accept/reject/dismiss a queued medication suggestion."""
        try:
            resolved = self.vocab_manager.resolve_medication_review(
                review_id=review_id,
                action=action,
                canonical_override=canonical_override or "",
            )
            if not resolved:
                return {
                    "success": False,
                    "error": "Review item not found",
                }
            return {
                "success": True,
                "message": f"Review item marked as {resolved.get('status', action)}",
                "review": resolved,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def import_medication_report(
        self,
        report_path: str,
        min_confidence: str = "medium",
        auto_import_confidence: str = "high",
        min_occurrence_count: int = 1,
        min_entry_count: int = 1,
    ) -> Dict[str, Any]:
        """Import medication mappings/review items from a markdown analysis report."""
        try:
            result = self.vocab_manager.import_medication_mappings_from_report(
                report_path=report_path,
                min_confidence=min_confidence or "medium",
                auto_import_confidence=auto_import_confidence or "high",
                min_occurrence_count=max(1, int(min_occurrence_count)),
                min_entry_count=max(1, int(min_entry_count)),
            )
            return {
                "success": True,
                "message": (
                    f"Processed {result.get('rows', 0)} rows "
                    f"(imported {result.get('imported', 0)}, queued {result.get('queued', 0)}, skipped {result.get('skipped', 0)})."
                ),
                "result": result,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def queue_medication_review(
        self,
        observed: str,
        suggested: str,
        confidence: str = "medium",
        evidence: str = "",
        occurrence_count: int = 1,
        entry_count: int = 1,
        sample_context: str = "",
        source: str = "manual",
    ) -> Dict[str, Any]:
        """Create/update a manual medication review queue item."""
        try:
            review = self.vocab_manager.queue_medication_review(
                observed=observed,
                suggested=suggested,
                confidence=confidence or "medium",
                evidence=evidence or "",
                occurrence_count=max(1, int(occurrence_count)),
                entry_count=max(1, int(entry_count)),
                sample_context=sample_context or "",
                source=source or "manual",
                save=True,
            )
            return {
                "success": True,
                "message": "Medication review suggestion queued",
                "review": review,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def get_medication_autolearn_status(self) -> Dict[str, Any]:
        """Return medication auto-learn service status and last run summary."""
        try:
            service = self._get_medication_autolearn_service()
            status_payload = service.get_status()
            return {
                "success": True,
                "status": status_payload,
                "lastSummary": status_payload.get("lastSummary"),
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def run_medication_autolearn_now(self) -> Dict[str, Any]:
        """Trigger an immediate medication auto-learn run."""
        try:
            service = self._get_medication_autolearn_service()
            summary = service.run_now()
            status_payload = service.get_status()
            return {
                "success": True,
                "summary": summary,
                "status": status_payload,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def _build_command_handlers(self) -> Dict[str, CommandHandler]:
        return {
            "add_term": lambda kwargs: self.add_term(
                kwargs.get("correct_term", ""),
                kwargs.get("variations", []),
                kwargs.get("category", "general"),
            ),
            "get_list": lambda kwargs: self.get_vocabulary_list(
                kwargs.get("search", ""),
                kwargs.get("category", ""),
            ),
            "get_stats": lambda kwargs: self.get_vocabulary_stats(),
            "edit_term": lambda kwargs: self.edit_term(
                kwargs.get("term_key", ""),
                kwargs.get("category"),
                kwargs.get("additional_variations", []),
                kwargs.get("remove_variations", []),
            ),
            "delete_term": lambda kwargs: self.delete_term(kwargs.get("term_key", "")),
            "import_template": lambda kwargs: self.import_template(kwargs.get("template_name", "")),
            "export": lambda kwargs: self.export_vocabulary(kwargs.get("filepath", "")),
            "clear_all": lambda kwargs: self.clear_vocabulary(),
            "learn_correction": lambda kwargs: self.learn_correction(
                kwargs.get("original", ""),
                kwargs.get("corrected", ""),
                kwargs.get("context", ""),
            ),
            "get_suggestions": lambda kwargs: self.get_suggestions(
                kwargs.get("text", ""),
                kwargs.get("max_suggestions", 3),
            ),
            "get_medication_mappings": lambda kwargs: self.get_medication_mappings(
                kwargs.get("search", ""),
                kwargs.get("include_inactive", False),
            ),
            "add_medication_mapping": lambda kwargs: self.add_medication_mapping(
                kwargs.get("observed", ""),
                kwargs.get("canonical", ""),
                kwargs.get("source", "manual"),
                kwargs.get("confidence", "manual"),
                kwargs.get("occurrence_count", 1),
                kwargs.get("entry_count", 1),
                kwargs.get("active", True),
            ),
            "delete_medication_mapping": lambda kwargs: self.delete_medication_mapping(
                kwargs.get("observed", "")
            ),
            "get_medication_review_queue": lambda kwargs: self.get_medication_review_queue(
                kwargs.get("status", "pending")
            ),
            "resolve_medication_review": lambda kwargs: self.resolve_medication_review(
                kwargs.get("review_id", ""),
                kwargs.get("action", ""),
                kwargs.get("canonical_override", ""),
            ),
            "import_medication_report": lambda kwargs: self.import_medication_report(
                kwargs.get("report_path", ""),
                kwargs.get("min_confidence", "medium"),
                kwargs.get("auto_import_confidence", "high"),
                kwargs.get("min_occurrence_count", 1),
                kwargs.get("min_entry_count", 1),
            ),
            "queue_medication_review": lambda kwargs: self.queue_medication_review(
                kwargs.get("observed", ""),
                kwargs.get("suggested", ""),
                kwargs.get("confidence", "medium"),
                kwargs.get("evidence", ""),
                kwargs.get("occurrence_count", 1),
                kwargs.get("entry_count", 1),
                kwargs.get("sample_context", ""),
                kwargs.get("source", "manual"),
            ),
            "get_medication_autolearn_status": lambda kwargs: self.get_medication_autolearn_status(),
            "run_medication_autolearn_now": lambda kwargs: self.run_medication_autolearn_now(),
        }

    def handle_command(self, command: str, **kwargs: Any) -> Dict[str, Any]:
        """Handle a vocabulary command using instance-bound dispatch."""
        handler = self._command_handlers.get(command)
        if handler is None:
            return {
                "success": False,
                "error": f"Unknown vocabulary command: {command}",
            }
        return handler(kwargs)


def handle_vocabulary_command(
    command: str,
    *,
    api: Optional[VocabularyAPI] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Compatibility wrapper for callers that still use module-level command dispatch."""
    router = api or VocabularyAPI()
    return router.handle_command(command, **kwargs)
