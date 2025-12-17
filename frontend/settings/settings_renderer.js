console.log('Settings renderer script loaded.');

// --- DOM Elements ---
const sidebarLinks = {
    wakewords: document.getElementById('nav-wakewords'),
    asr: document.getElementById('nav-asr'),
    vocabulary: document.getElementById('nav-vocabulary'),
};
const sections = {
    wakewords: document.getElementById('section-wakewords'),
    asr: document.getElementById('section-asr'),
    vocabulary: document.getElementById('section-vocabulary'),
};

const ASR_MODELS = [
    { id: 'mlx-community/whisper-large-v3-turbo', name: 'Whisper (large-v3-turbo) – Recommended' },
    { id: 'mlx-community/parakeet-tdt-0.6b-v2', name: 'Parakeet-TDT-0.6B-v2 – Requires parakeet-mlx' },
    { id: 'mlx-community/parakeet-tdt-0.6b-v3', name: 'Parakeet-TDT-0.6B-v3 – Latest MLX build' },
    { id: 'mlx-community/Voxtral-Mini-3B-2507-bf16', name: 'Voxtral Mini 3B (bf16) – MLX Audio' }
];

// ASR Model Elements
const asrModelSelect = document.getElementById('asr-model-select');
const saveAsrModelButton = document.getElementById('save-asr-model-button');
const asrModelStatus = document.getElementById('asr-model-status');
// Wake Words Elements (Updated)
const wakeWordsDictateInput = document.getElementById('wake-words-dictate-input');
const wakeWordEnabledToggle = document.getElementById('wake-word-enabled-toggle');
const filterFillerToggle = document.getElementById('filter-filler-toggle');
const fillerWordsInput = document.getElementById('filler-words-input');
const autoStopToggle = document.getElementById('auto-stop-toggle');
const saveDictationButton = document.getElementById('save-dictation-button');
const wakeWordsStatus = document.getElementById('wake-words-status');
// Vocabulary Elements
const newTermCorrect = document.getElementById('new-term-correct');
const newTermVariations = document.getElementById('new-term-variations');
const newTermCategory = document.getElementById('new-term-category');
const addTermButton = document.getElementById('add-term-button');
const templateSelect = document.getElementById('template-select');
const importTemplateButton = document.getElementById('import-template-button');
const vocabSearch = document.getElementById('vocab-search');
const vocabularyList = document.getElementById('vocabulary-list');
const vocabStats = document.getElementById('vocab-stats');
const statsText = document.getElementById('stats-text');
const vocabularyStatus = document.getElementById('vocabulary-status');


// --- Navigation ---
function showSection(sectionId) {
    // Hide all sections
    Object.values(sections).forEach(section => section.style.display = 'none');
    // Deactivate all sidebar links
    Object.values(sidebarLinks).forEach(link => link.classList.remove('active'));

    // Show the target section
    if (sections[sectionId]) {
        sections[sectionId].style.display = 'block';
    }
    // Activate the target sidebar link
    if (sidebarLinks[sectionId]) {
        sidebarLinks[sectionId].classList.add('active');
    }
}

Object.keys(sidebarLinks).forEach(key => {
    if (sidebarLinks[key]) {
        sidebarLinks[key].addEventListener('click', () => showSection(key));
    }
});

// --- Model Population ---
function populateAsrModelDropdown(selectedAsrModel) {
    if (!asrModelSelect) {
        return;
    }

    asrModelSelect.innerHTML = '';
    ASR_MODELS.forEach(model => {
        const option = document.createElement('option');
        option.value = model.id;
        option.textContent = model.name;
        asrModelSelect.appendChild(option);
    });

    const modelToSelect = selectedAsrModel || (ASR_MODELS.length > 0 ? ASR_MODELS[0].id : '');
    if (modelToSelect) {
        asrModelSelect.value = modelToSelect;
    }
}


// --- Load Settings ---
async function loadAndPopulateSettings() {
    console.log('DEBUG: Settings DOM loaded. Requesting settings...');
    try {
        const settings = await window.settingsAPI.loadSettings();

        console.log('DEBUG: Settings loaded from main:', settings);

        // Populate wake words
        if (settings.wakeWords && typeof settings.wakeWords === 'object') {
            wakeWordsDictateInput.value = (settings.wakeWords.dictate || []).join(', ');
        } else {
            console.warn('Wake words setting missing or invalid. Resetting to defaults.');
            wakeWordsDictateInput.value = '';
        }
        if (wakeWordEnabledToggle) {
            wakeWordEnabledToggle.checked = settings.wakeWordEnabled !== false;
        }

        // Populate filler-word controls
        if (filterFillerToggle) {
            filterFillerToggle.checked = settings.filterFillerWords !== false;
        }
        if (fillerWordsInput) {
            const fillerWords = Array.isArray(settings.fillerWords) && settings.fillerWords.length > 0
                ? settings.fillerWords
                : ['um', 'uh', 'ah', 'er', 'hmm', 'mm', 'mhm'];
            fillerWordsInput.value = fillerWords.join(', ');
        }
        if (autoStopToggle) {
            autoStopToggle.checked = settings.autoStopOnSilence !== false;
        }

        // Populate ASR model dropdown
        populateAsrModelDropdown(settings.selectedAsrModel);
    } catch (error) {
        console.error('ERROR: Error loading settings:', error);
        if (wakeWordsStatus) {
            wakeWordsStatus.textContent = 'Error loading settings. Please retry.';
            wakeWordsStatus.style.color = 'red';
        }
    }
}

// --- Save Settings ---

// Save ASR Model
if (saveAsrModelButton) {
    saveAsrModelButton.addEventListener('click', async () => {
        if (!asrModelSelect) {
            return;
        }
        const selectedAsrModel = asrModelSelect.value;
        if (!selectedAsrModel) {
            asrModelStatus.textContent = 'Select an ASR model first.';
            asrModelStatus.style.color = 'red';
            return;
        }

        try {
            saveAsrModelButton.disabled = true;
            asrModelSelect.disabled = true;
            asrModelStatus.textContent = 'Preparing model assets…';
            asrModelStatus.style.color = '#ffb400';

            const ensureResult = await window.settingsAPI.ensureModel(selectedAsrModel);
            if (!ensureResult || ensureResult.success === false) {
                const errorMessage = ensureResult?.error || 'Model preparation failed.';
                throw new Error(errorMessage);
            }

            window.settingsAPI.saveSettings({ selectedAsrModel });
            asrModelStatus.textContent = 'ASR model downloaded and saved!';
            asrModelStatus.style.color = 'green';
            setTimeout(() => { asrModelStatus.textContent = ''; }, 3500);
        } catch (error) {
            console.error('Failed to prepare ASR model', error);
            asrModelStatus.textContent = `Model setup failed: ${error?.message || error}`;
            asrModelStatus.style.color = 'red';
        } finally {
            saveAsrModelButton.disabled = false;
            asrModelSelect.disabled = false;
        }
    });
}

// Helper function to parse comma-separated string into array
const parseWakeWords = (inputString) => {
    return inputString.split(',')
                      .map(word => word.trim())
                      .filter(word => word.length > 0);
};

if (saveDictationButton) {
    saveDictationButton.addEventListener('click', () => {
        const wakeWordsData = {
            dictate: parseWakeWords(wakeWordsDictateInput.value)
        };

        const fillerWords = parseWakeWords(fillerWordsInput.value);
        const payload = {
            wakeWords: wakeWordsData,
            filterFillerWords: !!filterFillerToggle.checked,
            fillerWords,
            autoStopOnSilence: autoStopToggle ? !!autoStopToggle.checked : true,
            wakeWordEnabled: wakeWordEnabledToggle ? !!wakeWordEnabledToggle.checked : true
        };

        console.log('DEBUG: Saving dictation settings:', payload);
        window.settingsAPI.saveSettings(payload);
        wakeWordsStatus.textContent = 'Dictation settings saved!';
        wakeWordsStatus.style.color = 'green';
        setTimeout(() => { wakeWordsStatus.textContent = ''; }, 3000);
    });
}

// --- Vocabulary Management ---
let currentVocabularyTerms = [];

async function loadVocabularyData() {
    console.log('loadVocabularyData called');
    try {
        // Call vocabulary API to get current vocabulary and stats
        console.log('Making vocabulary API calls...');
        const [termsResult, statsResult] = await Promise.all([
            window.settingsAPI.callVocabularyAPI('get_list'),
            window.settingsAPI.callVocabularyAPI('get_stats')
        ]);
        
        console.log('Terms result:', termsResult);
        console.log('Stats result:', statsResult);
        
        if (termsResult.success) {
            console.log('Setting currentVocabularyTerms and calling displayVocabularyList');
            currentVocabularyTerms = termsResult.terms;
            displayVocabularyList(currentVocabularyTerms);
        } else {
            console.error('Terms result was not successful:', termsResult);
        }
        
        if (statsResult.success) {
            console.log('Calling displayVocabularyStats');
            displayVocabularyStats(statsResult.stats);
        } else {
            console.error('Stats result was not successful:', statsResult);
        }
    } catch (error) {
        console.error('Error loading vocabulary data:', error);
        const vocabularyStatusElement = document.getElementById('vocabulary-status');
        if (vocabularyStatusElement) {
            vocabularyStatusElement.textContent = 'Error loading vocabulary data';
            vocabularyStatusElement.style.color = 'red';
        }
    }
}

function displayVocabularyStats(stats) {
    console.log('displayVocabularyStats called with:', stats);
    const statsTextElement = document.getElementById('stats-text');
    if (!statsTextElement) {
        console.error('stats-text element not found');
        return;
    }
    console.log('stats-text element found:', statsTextElement);
    
    const totalTerms = stats.total_terms || 0;
    const totalUsage = stats.total_usage || 0;
    const categories = stats.categories || {};
    
    const categoryText = Object.entries(categories)
        .map(([cat, count]) => `${cat}: ${count}`)
        .join(', ');
    
    const finalText = `${totalTerms} terms, ${totalUsage} total uses. Categories: ${categoryText}`;
    console.log('Setting stats text to:', finalText);
    statsTextElement.textContent = finalText;
}

function displayVocabularyList(terms) {
  console.log('displayVocabularyList called with:', terms);
  const vocabularyListElement = document.getElementById('vocabulary-list');
  if (!vocabularyListElement) {
    console.error('vocabulary-list element not found');
    return;
  }
  console.log('vocabulary-list element found:', vocabularyListElement);
  
  if (!terms || terms.length === 0) {
    console.log('No terms to display');
    vocabularyListElement.innerHTML = '<div style="text-align: center; padding: 40px; color: #666;">No vocabulary terms yet. Add some terms above!</div>';
    return;
  }

  console.log('Clearing existing content and displaying', terms.length, 'terms');
  vocabularyListElement.innerHTML = ''; // Clear existing content

  terms.forEach(term => {
    // Create term container
    const termDiv = document.createElement('div');
    termDiv.style.cssText = 'border-bottom: 1px solid #eee; padding: 15px; display: flex; justify-content: space-between; align-items: center;';

    // Create term info section
    const infoDiv = document.createElement('div');
    infoDiv.innerHTML = `
      <strong style="font-size: 1.1em;">${term.correct}</strong> 
      <span style="color: #666; font-size: 0.9em;">(${term.category})</span>
      <br>
      <small style="color: #888; margin-top: 5px; display: block;">
        Variations: ${term.variations.slice(1).join(', ') || 'None'} 
        • Used ${term.usage_count} times
      </small>
    `;

    // Create button container
    const buttonContainer = document.createElement('div');
    buttonContainer.style.cssText = 'display: flex; gap: 8px;';

    // Create edit button
    const editButton = document.createElement('button');
    editButton.textContent = 'Edit';
    editButton.style.cssText = 'background: #28a745; color: white; border: none; padding: 8px 12px; border-radius: 4px; cursor: pointer; font-size: 0.9em;';
    editButton.addEventListener('click', () => editVocabularyTerm(term));

    // Create delete button with proper event listener
    const deleteButton = document.createElement('button');
    deleteButton.textContent = 'Delete';
    deleteButton.style.cssText = 'background: #dc3545; color: white; border: none; padding: 8px 12px; border-radius: 4px; cursor: pointer; font-size: 0.9em;';
    deleteButton.addEventListener('click', () => deleteVocabularyTerm(term.key));

    // Add hover effects
    editButton.addEventListener('mouseenter', () => {
      editButton.style.background = '#218838';
    });
    editButton.addEventListener('mouseleave', () => {
      editButton.style.background = '#28a745';
    });

    deleteButton.addEventListener('mouseenter', () => {
      deleteButton.style.background = '#c82333';
    });
    deleteButton.addEventListener('mouseleave', () => {
      deleteButton.style.background = '#dc3545';
    });

    buttonContainer.appendChild(editButton);
    buttonContainer.appendChild(deleteButton);

    termDiv.appendChild(infoDiv);
    termDiv.appendChild(buttonContainer);
    vocabularyListElement.appendChild(termDiv);
  });

  // Add a subtle spacer at the end for better visual breathing room
  const spacer = document.createElement('div');
  spacer.style.cssText = 'height: 20px;';
  vocabularyListElement.appendChild(spacer);
}

function filterVocabularyList() {
    const searchTerm = vocabSearch.value.toLowerCase();
    const filteredTerms = currentVocabularyTerms.filter(term => 
        term.correct.toLowerCase().includes(searchTerm) ||
        term.variations.some(variation => variation.toLowerCase().includes(searchTerm))
    );
    displayVocabularyList(filteredTerms);
}

async function deleteVocabularyTerm(termKey) {
    if (!confirm('Are you sure you want to delete this vocabulary term?')) {
        return;
    }
    
    try {
        const result = await window.settingsAPI.callVocabularyAPI('delete_term', { term_key: termKey });
        
        if (result.success) {
            vocabularyStatus.textContent = result.message;
            vocabularyStatus.style.color = 'green';
            loadVocabularyData(); // Reload the list
        } else {
            vocabularyStatus.textContent = result.error;
            vocabularyStatus.style.color = 'red';
        }
    } catch (error) {
        vocabularyStatus.textContent = 'Error deleting term';
        vocabularyStatus.style.color = 'red';
    }
    
    setTimeout(() => { vocabularyStatus.textContent = ''; }, 3000);
}

// Edit Term Functionality
let currentEditingTerm = null;
let variationsToDelete = [];

function editVocabularyTerm(term) {
  currentEditingTerm = term;
  variationsToDelete = []; // Reset deletions
  currentEditingVariations = []; // Reset new variations
  const modal = document.getElementById('edit-term-modal');
  const correctInput = document.getElementById('edit-term-correct');
  const categorySelect = document.getElementById('edit-term-category');
  const variationsList = document.getElementById('edit-variations-list');
  const newVariationInput = document.getElementById('edit-new-variation-input');

  // Populate modal with current term data
  correctInput.value = term.correct;
  categorySelect.value = term.category;

  // Display current variations (excluding the correct term itself) with delete buttons
  displayEditableVariations(term.variations.slice(1), variationsList);

  // Clear the new variation input
  if (newVariationInput) {
    newVariationInput.value = '';
  }

  // Show the modal
  modal.style.display = 'flex';
}

let currentEditingVariations = [];

function displayEditableVariations(variations, container) {
  const allVariations = [...variations, ...currentEditingVariations];
  
  if (allVariations.length === 0) {
    container.innerHTML = '<span style="color: #666; font-style: italic;">No variations yet</span>';
    return;
  }

  container.innerHTML = '';
  
  allVariations.forEach((variation, index) => {
    if (variationsToDelete.includes(variation)) {
      return; // Skip deleted variations
    }

    const variationSpan = document.createElement('span');
    variationSpan.style.cssText = 'display: inline-flex; align-items: center; background: #e9ecef; padding: 6px 8px 6px 12px; margin: 3px; border-radius: 4px; font-size: 13px; position: relative; cursor: pointer; transition: all 0.2s ease;';
    
    // Add indicator for newly added variations
    if (currentEditingVariations.includes(variation)) {
      variationSpan.style.background = '#d4edda';
      variationSpan.style.border = '1px solid #c3e6cb';
    }
    
    // Create text content
    const textSpan = document.createElement('span');
    textSpan.textContent = variation;
    
    // Create delete button space
    const deleteSpace = document.createElement('span');
    deleteSpace.style.cssText = 'width: 16px; height: 16px; position: relative; flex-shrink: 0;';
    
    const deleteBtn = document.createElement('button');
    deleteBtn.innerHTML = '×';
    deleteBtn.style.cssText = 'position: absolute; top: 0; left: 0; width: 16px; height: 16px; background: rgba(108, 117, 125, 0.7); color: white; border: none; border-radius: 50%; font-size: 11px; cursor: pointer; line-height: 1; display: flex; align-items: center; justify-content: center; opacity: 0; transition: all 0.2s ease; font-weight: bold;';
    deleteBtn.title = 'Remove this variation';

    // Hover effect for delete button
    deleteBtn.addEventListener('mouseenter', () => {
      deleteBtn.style.background = 'rgba(220, 53, 69, 0.9)';
      deleteBtn.style.transform = 'scale(1.1)';
    });

    deleteBtn.addEventListener('mouseleave', () => {
      deleteBtn.style.background = 'rgba(108, 117, 125, 0.7)';
      deleteBtn.style.transform = 'scale(1)';
    });
    
    // Show/hide delete button on hover
    variationSpan.addEventListener('mouseenter', () => {
      deleteBtn.style.opacity = '1';
    });
    
    variationSpan.addEventListener('mouseleave', () => {
      deleteBtn.style.opacity = '0';
    });
    
    deleteBtn.addEventListener('click', () => {
      if (currentEditingVariations.includes(variation)) {
        // Remove from newly added variations
        currentEditingVariations = currentEditingVariations.filter(v => v !== variation);
      } else {
        // Mark original variation for deletion
        variationsToDelete.push(variation);
      }
      displayEditableVariations(currentEditingTerm.variations.slice(1), container);
    });
    
    // Append elements in correct order
    deleteSpace.appendChild(deleteBtn);
    variationSpan.appendChild(textSpan);
    variationSpan.appendChild(deleteSpace);
    container.appendChild(variationSpan);
  });

  // Show message if all variations are marked for deletion
  if (allVariations.every(v => variationsToDelete.includes(v) || currentEditingVariations.includes(v))) {
    container.innerHTML = '<span style="color: #888; font-style: italic;">All variations will be removed</span>';
  }
}

function addNewVariation() {
  const newVariationInput = document.getElementById('edit-new-variation-input');
  const variationsList = document.getElementById('edit-variations-list');
  
  if (!newVariationInput || !currentEditingTerm) return;
  
  const newVariation = newVariationInput.value.trim();
  if (!newVariation) return;
  
  // Check for duplicates
  const allExistingVariations = [
    ...currentEditingTerm.variations,
    ...currentEditingVariations
  ];
  
  if (allExistingVariations.some(v => v.toLowerCase() === newVariation.toLowerCase())) {
    alert('This variation already exists!');
    return;
  }
  
  // Add to current editing variations
  currentEditingVariations.push(newVariation);
  
  // Clear input and refresh display
  newVariationInput.value = '';
  displayEditableVariations(currentEditingTerm.variations.slice(1), variationsList);
}

async function saveEditedTerm() {
  if (!currentEditingTerm) return;

  const categorySelect = document.getElementById('edit-term-category');
  const modal = document.getElementById('edit-term-modal');

  const newCategory = categorySelect.value;

  try {
    const result = await window.settingsAPI.callVocabularyAPI('edit_term', {
      term_key: currentEditingTerm.key,
      category: newCategory,
      additional_variations: currentEditingVariations,
      remove_variations: variationsToDelete
    });

    if (result.success) {
      vocabularyStatus.textContent = result.message;
      vocabularyStatus.style.color = 'green';
      
      // Close modal and reload vocabulary
      modal.style.display = 'none';
      currentEditingTerm = null;
      variationsToDelete = [];
      currentEditingVariations = [];
      loadVocabularyData();
    } else {
      vocabularyStatus.textContent = result.error;
      vocabularyStatus.style.color = 'red';
    }
  } catch (error) {
    vocabularyStatus.textContent = 'Error updating term';
    vocabularyStatus.style.color = 'red';
  }

  setTimeout(() => { vocabularyStatus.textContent = ''; }, 3000);
}

function cancelEdit() {
  const modal = document.getElementById('edit-term-modal');
  modal.style.display = 'none';
  currentEditingTerm = null;
  variationsToDelete = [];
  currentEditingVariations = [];
}

// Modal event listeners
document.addEventListener('DOMContentLoaded', () => {
  const saveEditButton = document.getElementById('save-edit-button');
  const cancelEditButton = document.getElementById('cancel-edit-button');
  const addVariationButton = document.getElementById('add-variation-button');
  const newVariationInput = document.getElementById('edit-new-variation-input');
  const modal = document.getElementById('edit-term-modal');

  if (saveEditButton) {
    saveEditButton.addEventListener('click', saveEditedTerm);
  }

  if (cancelEditButton) {
    cancelEditButton.addEventListener('click', cancelEdit);
  }

  if (addVariationButton) {
    addVariationButton.addEventListener('click', addNewVariation);
  }

  if (newVariationInput) {
    newVariationInput.addEventListener('keypress', (e) => {
      if (e.key === 'Enter') {
        addNewVariation();
      }
    });
  }

  // Close modal when clicking outside
  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        cancelEdit();
      }
    });
  }
});

// Make functions available globally
window.deleteVocabularyTerm = deleteVocabularyTerm;
window.editVocabularyTerm = editVocabularyTerm;

// Vocabulary Event Listeners
if (addTermButton) {
    addTermButton.addEventListener('click', async () => {
        const correct = newTermCorrect.value.trim();
        const variationsText = newTermVariations.value.trim();
        const category = newTermCategory.value;
        
        if (!correct) {
            vocabularyStatus.textContent = 'Please enter a correct term';
            vocabularyStatus.style.color = 'red';
            return;
        }
        
        const variations = variationsText ? 
            variationsText.split(',').map(v => v.trim()).filter(v => v) : 
            [];
        
        try {
            const result = await window.settingsAPI.callVocabularyAPI('add_term', {
                correct_term: correct,
                variations: variations,
                category: category
            });
            
            if (result.success) {
                vocabularyStatus.textContent = result.message;
                vocabularyStatus.style.color = 'green';
                
                // Clear form
                newTermCorrect.value = '';
                newTermVariations.value = '';
                newTermCategory.value = 'general';
                
                // Reload vocabulary
                loadVocabularyData();
            } else {
                vocabularyStatus.textContent = result.error;
                vocabularyStatus.style.color = 'red';
            }
        } catch (error) {
            vocabularyStatus.textContent = 'Error adding term';
            vocabularyStatus.style.color = 'red';
        }
        
        setTimeout(() => { vocabularyStatus.textContent = ''; }, 3000);
    });
}

if (vocabSearch) {
    vocabSearch.addEventListener('input', filterVocabularyList);
}

// --- Initialization ---
window.addEventListener('DOMContentLoaded', () => {
    loadAndPopulateSettings();
    loadVocabularyData(); // Load vocabulary data
    showSection('wakewords'); // Show the first section by default

    // Listen for navigation requests from main process (e.g., direct vocabulary access)
    window.settingsAPI.onNavigateToSection((event, section) => {
        if (section === 'vocabulary') {
            console.log('Navigating to vocabulary section via tray menu');
            showSection('vocabulary'); // Use 'vocabulary' not 'section-vocabulary'
            // The showSection function already handles sidebar activation, but let's be explicit
            setTimeout(() => {
                console.log('Loading vocabulary data after navigation...');
                loadVocabularyData();
            }, 100);
        }
    });
});
