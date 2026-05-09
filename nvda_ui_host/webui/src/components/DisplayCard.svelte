<script>
    import { invokeResultAction } from '../lib/actions.js';
    import { appState, t } from '../lib/state.svelte.js';
    import ContentBlock from './ContentBlock.svelte';
    import MessageItem from './MessageItem.svelte';

    let { registerContent = () => {}, registerFirstAction = () => {} } = $props();
    let contentElement = $state(null);
    let firstActionElement = $state(null);

    $effect(() => {
        registerContent(contentElement);
    });

    $effect(() => {
        registerFirstAction(firstActionElement);
    });

    let isChatMode = $derived(appState.view.mode === 'chat');
</script>

<section class="workspace-card content-card" aria-labelledby="content-heading">
    <div class="section-header">
        <h2 id="content-heading" class="section-title">{t('content_heading', 'Content')}</h2>
    </div>

    <div id="content" bind:this={contentElement} role="main" tabindex="-1">
        {#if isChatMode}
            {#if appState.chat.messages.length === 0}
                {t('no_chat_messages', 'No chat messages available.')}
            {:else}
                <div
                    class="chat-transcript"
                    role="region"
                    aria-labelledby="content-heading"
                >
                    {#each appState.chat.messages as message (message.id || `${message.role}-${message.content}`)}
                        <MessageItem {message} />
                    {/each}
                </div>
            {/if}
        {:else}
            {#each appState.display.blocks as block, index (`display-${index}`)}
                <ContentBlock {block} />
            {/each}

            {#if appState.display.actions.length > 0}
                <div class="result-actions" aria-label={t('result_actions_label', 'Result actions')}>
                    <button
                        bind:this={firstActionElement}
                        type="button"
                        onclick={() => invokeResultAction(appState.display.actions[0])}
                    >
                        {appState.display.actions[0].label || appState.display.actions[0].id || t('result_action_fallback_label', 'Action')}
                    </button>

                    {#each appState.display.actions.slice(1) as action, index (action.id || `action-${index + 1}`)}
                        <button type="button" onclick={() => invokeResultAction(action)}>
                            {action.label || action.id || t('result_action_fallback_label', 'Action')}
                        </button>
                    {/each}
                </div>
            {/if}
        {/if}
    </div>
</section>
