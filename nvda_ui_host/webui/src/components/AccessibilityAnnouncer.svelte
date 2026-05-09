<script>
    import { appState } from '../lib/state.svelte.js';
</script>

<div class="sr-only">
    <div aria-live="assertive" aria-atomic="true">
        {#key appState.accessibility.statusAnnouncement?.id}
            <div>{appState.accessibility.statusAnnouncement?.message || ''}</div>
        {/key}
    </div>

    <div role="status" aria-live="polite" aria-atomic="true">
        {#key appState.accessibility.responseAnnouncement?.id}
            <div>{appState.accessibility.responseAnnouncement?.message || ''}</div>
        {/key}
    </div>
</div>
