<script>
    import { copyMessageMarkdown, copyMessageTable, copyMessageText } from '../lib/actions.js';
    import { formatRoleLabel, hasRenderedTables, normalizeContentBlocks } from '../lib/content.js';
    import { t } from '../lib/state.svelte.js';
    import ContentBlock from './ContentBlock.svelte';

    let { message } = $props();

    let role = $derived(String(message?.role || 'user').trim().toLowerCase() || 'user');
    let roleLabel = $derived(formatRoleLabel(role));
    let headingTag = $derived(role === 'assistant' ? 'h5' : 'h6');
    let showTableCopy = $derived(hasRenderedTables(message?.content));
</script>

<article class={`chat-message ${role}`} aria-label={roleLabel}>
    <div class="chat-message-header">
        <div class="chat-message-title-group">
            <svelte:element this={headingTag} class="role">{roleLabel}</svelte:element>
            <p class="message-subtitle">{role === 'assistant' ? 'Response' : 'Prompt'}</p>
        </div>

        {#if role === 'assistant'}
            <div class="chat-message-actions" aria-label="Message actions">
                <button type="button" onclick={() => copyMessageText(message)}>{t('copy_response_button', 'Copy response')}</button>
                <button type="button" onclick={() => copyMessageMarkdown(message)}>{t('copy_response_markdown_button', 'Copy response markdown')}</button>
                {#if showTableCopy}
                    <button type="button" onclick={() => copyMessageTable(message)}>{t('copy_table_button', 'Copy table')}</button>
                {/if}
            </div>
        {/if}
    </div>

    <div class="text">
        {#each normalizeContentBlocks(message?.content) as block, index (`${message?.id || role}-${index}`)}
            <ContentBlock {block} />
        {/each}
    </div>
</article>
