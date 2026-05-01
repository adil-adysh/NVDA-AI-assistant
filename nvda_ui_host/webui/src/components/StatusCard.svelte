<script>
    import { appState } from '../lib/state.svelte.js';

    let { registerStatus = () => {} } = $props();
    let statusElement = $state(null);

    $effect(() => {
        registerStatus(statusElement);
    });
</script>

<section class="workspace-card status-card" aria-labelledby="status-heading">
    <h2 id="status-heading" class="section-title">Status</h2>
    <div id="status" bind:this={statusElement} role="status" aria-live="polite" tabindex="-1">{appState.statusMessage}</div>
</section>
