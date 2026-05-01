<script>
    let { block } = $props();
</script>

{#if block?.type === 'thinking'}
    <details class="thinking-block" open={block.collapsed === false}>
        <summary>{block.summary || 'Thinking'}</summary>
        <div class="text">{block.text || ''}</div>
    </details>
{:else if block?.type === 'image'}
    <figure class="content-block image">
        <img
            src={`data:${block.mime_type || 'image/png'};base64,${block.image_base64 || ''}`}
            alt={block.alt || 'Attached image'}
            loading="lazy"
        />
        {#if block.alt}
            <figcaption>{block.alt}</figcaption>
        {/if}
    </figure>
{:else if block?.type === 'html'}
    <div class="content-block html">{@html block.html || ''}</div>
{:else}
    <div class="content-block text">{block?.text || ''}</div>
{/if}
