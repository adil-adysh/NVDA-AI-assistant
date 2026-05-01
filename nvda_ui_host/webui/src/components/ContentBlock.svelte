<script>
    let { block } = $props();
</script>

{#if block?.type === 'thinking'}
    <details class="thinking-block" open={block.collapsed === false}>
        <summary>{block.summary || 'Thinking'}</summary>
        <div class="text">{block.text || ''}</div>
    </details>
{:else if block?.type === 'html'}
    <div class="content-block html">{@html block.html || ''}</div>
{:else}
    <div class="content-block text">{block?.text || ''}</div>
{/if}
