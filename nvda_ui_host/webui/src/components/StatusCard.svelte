<script>
    import { appState, t } from '../lib/state.svelte';

    let { registerStatus = () => {} } = $props();
    let statusElement = $state(null);

    $effect(() => {
        registerStatus(statusElement);
    });
</script>

<section class="workspace-card status-card" aria-labelledby="status-heading">
    <h2 id="status-heading" class="section-title">{t('status_heading', 'Status')}</h2>
    <div id="status" bind:this={statusElement} role="status" aria-live="polite" tabindex="-1">{appState.statusMessage}</div>
</section>
