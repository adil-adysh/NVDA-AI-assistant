<script>
    import { copyMessageMarkdown, copyMessageTable, copyMessageText } from '../lib/actions';
    import { formatRoleLabel, hasRenderedTables, normalizeContentBlocks } from '../lib/content';
    import { t } from '../lib/state.svelte';
    import ContentBlock from './ContentBlock.svelte';

    let { message } = $props();

    let role = $derived(String(message?.role || 'user').trim().toLowerCase() || 'user');
    let roleLabel = $derived(formatRoleLabel(role));
    let headingTag = $derived(role === 'assistant' ? 'h5' : 'h6');
    let showTableCopy = $derived(hasRenderedTables(message?.content));
    let isStreaming = $derived(message?.streaming === true);
</script>

<article class={`chat-message ${role}`} aria-label={roleLabel} aria-busy={isStreaming}>
    <div class="chat-message-header">
        <div class="chat-message-title-group">
            <svelte:element this={headingTag} class="role">{roleLabel}</svelte:element>
            <p class="message-subtitle">
                {#if role === 'assistant' && isStreaming}
                    {t('response_streaming_subtitle', 'Response in progress')}
                {:else}
                    {role === 'assistant' ? t('response_subtitle', 'Response') : t('prompt_subtitle', 'Prompt')}
                {/if}
            </p>
        </div>

    </div>

    <div class="text">
        {#each normalizeContentBlocks(message?.content) as block, index (`${message?.id || role}-${index}`)}
            <ContentBlock {block} />
        {/each}
    </div>

    {#if role === 'assistant'}
        <div class="chat-message-actions" aria-label={t('message_actions_label', 'Message actions')}>
            <button type="button" onclick={() => copyMessageText(message)}>{t('copy_response_button', 'Copy response')}</button>
            <button type="button" onclick={() => copyMessageMarkdown(message)}>{t('copy_response_markdown_button', 'Copy response markdown')}</button>
            {#if showTableCopy}
                <button type="button" onclick={() => copyMessageTable(message)}>{t('copy_table_button', 'Copy table')}</button>
            {/if}
        </div>
    {/if}
</article>
