<script>
    import { submitModelSelection, submitProviderSelection, submitThinkModeToggle } from '../lib/actions';
    import { appState, t } from '../lib/state.svelte';

    const DEFERRED_COMMIT_KEYS = new Set(['ArrowDown', 'ArrowUp', 'Home', 'End', 'PageDown', 'PageUp']);

    function providerValue(provider) {
        return typeof provider === 'string' ? provider : provider.id || provider.value || '';
    }

    function providerLabel(provider) {
        if (typeof provider === 'string') {
            return provider;
        }

        return provider.label || providerValue(provider);
    }

    let providerSelectionPendingCommit = $state(false);
    let modelSelectionPendingCommit = $state(false);

    function commitProviderSelection(provider) {
        providerSelectionPendingCommit = false;
        submitProviderSelection(provider);
    }

    function commitModelSelection(model) {
        modelSelectionPendingCommit = false;
        submitModelSelection(model);
    }

    function handleProviderChange(event) {
        if (providerSelectionPendingCommit) {
            return;
        }

        commitProviderSelection(event.currentTarget.value);
    }

    function handleModelInputChange() {
        if (modelSelectionPendingCommit) {
            return;
        }

        commitModelSelection(appState.control.modelDraft);
    }

    function handleProviderKeydown(event) {
        if (DEFERRED_COMMIT_KEYS.has(event.key)) {
            providerSelectionPendingCommit = true;
        }
    }

    function handleModelKeydown(event) {
        if (DEFERRED_COMMIT_KEYS.has(event.key)) {
            modelSelectionPendingCommit = true;
        }
    }

    function handleProviderBlur() {
        if (!providerSelectionPendingCommit) {
            return;
        }

        commitProviderSelection(appState.control.providerDraft);
    }

    function handleModelBlur() {
        if (!modelSelectionPendingCommit) {
            return;
        }

        commitModelSelection(appState.control.modelDraft);
    }

    let controlsDisabled = $derived(Boolean(appState.control.pendingChange));
</script>

<div class="session-controls" aria-label={t('session_controls_label', 'Session controls')} aria-busy={controlsDisabled}>
    <label class="field-group" for="provider-select">
        <span id="provider-label">{t('provider_label', 'Provider')}</span>
        <select
            id="provider-select"
            bind:value={appState.control.providerDraft}
            onchange={handleProviderChange}
            onkeydown={handleProviderKeydown}
            onblur={handleProviderBlur}
            disabled={controlsDisabled}
        >
            {#each appState.control.availableProviders as provider (providerValue(provider))}
                <option value={providerValue(provider)}>{providerLabel(provider)}</option>
            {/each}
        </select>
    </label>

    <label class="field-group" for="model-select">
        <span id="model-label">{t('model_label', 'Model')}</span>
        <select
            id="model-select"
            bind:value={appState.control.modelDraft}
            onchange={handleModelInputChange}
            onkeydown={handleModelKeydown}
            onblur={handleModelBlur}
            disabled={controlsDisabled}
        >
            {#if appState.control.availableModels.length === 0}
                <option value={appState.control.modelDraft}>{appState.control.modelDraft}</option>
            {/if}

            {#each appState.control.availableModels as model (`option-${model}`)}
                <option value={String(model)}>{String(model)}</option>
            {/each}
        </select>
    </label>

    <label class="toggle-group" for="think-toggle">
        <input id="think-toggle" type="checkbox" bind:checked={appState.control.thinkDraft} onchange={(event) => submitThinkModeToggle(event.currentTarget.checked)} disabled={controlsDisabled} />
        <span id="think-mode-label">{t('think_mode_label', 'Think mode')}</span>
    </label>
</div>
