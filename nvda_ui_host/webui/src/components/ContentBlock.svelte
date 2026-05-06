<script>
    import { sanitizeHtml } from '../lib/content.js';
    import { t } from '../lib/state.svelte.js';

    let { block } = $props();
    let sanitizedHtml = $derived(block?.type === 'html' ? sanitizeHtml(block.html || '') : '');
</script>

{#if block?.type === 'thinking'}
    <details class="thinking-block" open={block.collapsed === false}>
        <summary>{block.summary || t('thinking_label', 'Thinking')}</summary>
        <div class="text">{block.text || ''}</div>
    </details>
{:else if block?.type === 'image'}
    <figure class="content-block image">
        <img
            src={`data:${block.mime_type || 'image/png'};base64,${block.image_base64 || ''}`}
            alt={block.alt || t('image_attachment_alt', 'Attached image')}
            loading="lazy"
        />
        {#if block.alt}
            <figcaption>{block.alt}</figcaption>
        {/if}
    </figure>
{:else if block?.type === 'html'}
    <div class="content-block html">{@html sanitizedHtml}</div>
{:else}
    <div class="content-block text">{block?.text || ''}</div>
{/if}
