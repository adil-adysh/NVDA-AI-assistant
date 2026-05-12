<script>
    import { clearDisplayedContent, copyCurrentMarkdown, copyCurrentText, requestCloseHost } from '../lib/actions';
    import { appState, t } from '../lib/state.svelte';

    let isChatMode = $derived(appState.view.mode === 'chat');
    let toolbarActions = $derived(new Set(appState.display.toolbarActions));
    let showToolbar = $derived(!isChatMode && toolbarActions.size > 0);
</script>

{#if showToolbar}
    <section class="workspace-card global-toolbar-card" aria-label={t('content_actions_label', 'Content actions')}>
        <div class="toolbar global-toolbar">
            {#if toolbarActions.has('copy_text')}
                <button id="copy-text" type="button" aria-keyshortcuts="Alt+Shift+T" onclick={copyCurrentText}>{t('copy_text_button', 'Copy text')}</button>
            {/if}

            {#if toolbarActions.has('copy_markdown')}
                <button id="copy-markdown" type="button" aria-keyshortcuts="Alt+Shift+M" onclick={copyCurrentMarkdown}>{t('copy_markdown_button', 'Copy markdown')}</button>
            {/if}

            {#if toolbarActions.has('clear')}
                <button id="clear" type="button" aria-keyshortcuts="Alt+Shift+R" onclick={clearDisplayedContent}>{t('clear_button', 'Clear')}</button>
            {/if}

            {#if toolbarActions.has('close')}
                <button id="close-window" type="button" aria-keyshortcuts="Escape" onclick={requestCloseHost}>{t('close_button', 'Close')}</button>
            {/if}
        </div>
    </section>
{/if}
