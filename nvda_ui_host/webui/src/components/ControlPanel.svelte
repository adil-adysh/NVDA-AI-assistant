<script>
    import { submitModelSelection, submitProviderSelection, submitThinkModeToggle } from '../lib/actions.js';
    import { appState, t } from '../lib/state.svelte.js';

    function providerValue(provider) {
        return typeof provider === 'string' ? provider : provider.id || provider.value || '';
    }

    function providerLabel(provider) {
        if (typeof provider === 'string') {
            return provider;
        }

        return provider.label || providerValue(provider);
    }

    function handleProviderChange(event) {
        submitProviderSelection(event.currentTarget.value);
    }

    function handleModelSelectChange(event) {
        appState.control.selectedModel = event.currentTarget.value;
        submitModelSelection(appState.control.selectedModel);
    }

    function handleModelInputChange() {
        submitModelSelection(appState.control.selectedModel);
    }
</script>

<div class="session-controls" aria-label="Session controls">
    <label class="field-group" for="provider-select">
        <span id="provider-label">{t('provider_label', 'Provider')}</span>
        <select id="provider-select" bind:value={appState.control.selectedProvider} onchange={handleProviderChange}>
            {#each appState.control.availableProviders as provider (providerValue(provider))}
                <option value={providerValue(provider)}>{providerLabel(provider)}</option>
            {/each}
        </select>
    </label>

    <label class="field-group" for="model-input">
        <span id="model-label">{t('model_label', 'Model')}</span>
        <div class="model-picker">
            <select id="model-select" bind:value={appState.control.selectedModel} onchange={handleModelSelectChange}>
                {#if appState.control.availableModels.length === 0}
                    <option value={appState.control.selectedModel}>{appState.control.selectedModel}</option>
                {/if}

                {#each appState.control.availableModels as model (`${model}`)}
                    <option value={String(model)}>{String(model)}</option>
                {/each}
            </select>

            <input
                id="model-input"
                list="model-options"
                type="text"
                bind:value={appState.control.selectedModel}
                onchange={handleModelInputChange}
                onblur={handleModelInputChange}
            />
        </div>

        <datalist id="model-options">
            {#each appState.control.availableModels as model (`option-${model}`)}
                <option value={String(model)}></option>
            {/each}
        </datalist>
    </label>

    <label class="toggle-group" for="think-toggle">
        <input id="think-toggle" type="checkbox" bind:checked={appState.control.thinkEnabled} onchange={(event) => submitThinkModeToggle(event.currentTarget.checked)} />
        <span id="think-mode-label">{t('think_mode_label', 'Think mode')}</span>
    </label>
</div>
