<script>
    import { deleteConversation, openConversation, startNewConversation } from '../lib/actions.js';
    import { appState, t } from '../lib/state.svelte.js';

    let { collapsed = false, onToggle = () => {} } = $props();

    let activeConversation = $derived(
        appState.chat.conversations.find(conversation => conversation.id === appState.chat.conversationId) ?? null
    );

    let hasConversationHistory = $derived(appState.chat.conversations.length > 0);

    let conversationHistoryHeading = $state('');
    $effect(() => {
        conversationHistoryHeading = t('conversation_history_heading', 'Recent conversations');
    });

    function conversationTitle(conversation) {
        const title = typeof conversation?.title === 'string' ? conversation.title.trim() : '';
        return title || t('new_conversation_button', 'New conversation');
    }

    function conversationPreview(conversation) {
        const preview = typeof conversation?.preview === 'string' ? conversation.preview.trim() : '';
        const title = conversationTitle(conversation);
        if (!preview || preview === title) {
            return '';
        }
        return preview;
    }

    function toggleSidebar() {
        onToggle();
    }
</script>

<aside
    class:collapsed
    class="conversation-rail"
    role="navigation"
    aria-label={conversationHistoryHeading}
>
    <div class="conversation-rail-header">
        <div class="conversation-rail-heading">
            <button
                type="button"
                class="conversation-rail-toggle"
                aria-expanded={!collapsed}
                aria-controls="conversation-list"
                onclick={toggleSidebar}
            >
                {collapsed
                    ? t('expand_conversation_sidebar_button', 'Show conversations')
                    : t('collapse_conversation_sidebar_button', 'Hide conversations')}
            </button>
            {#if !collapsed}
                <h3>{conversationHistoryHeading}</h3>
            {/if}
        </div>
        <button type="button" class="conversation-new-button" onclick={startNewConversation}>
            {t('new_conversation_button', 'New conversation')}
        </button>
    </div>

    {#if collapsed}
        {#if activeConversation}
            <div class="conversation-sidebar-current">
                <span class="conversation-sidebar-label">{t('current_conversation_label', 'Current conversation')}</span>
                <button
                    type="button"
                    class="conversation-active-pill"
                    aria-pressed="true"
                    onclick={() => openConversation(activeConversation.id)}
                >
                    <span class="conversation-title">{conversationTitle(activeConversation)}</span>
                </button>
            </div>
        {/if}
    {:else if !hasConversationHistory}
        <p class="conversation-empty-state">{t('empty_conversations_state', 'No stored conversations yet.')}</p>
    {:else}
        <ul id="conversation-list" class="conversation-list">
            {#each appState.chat.conversations as conversation (conversation.id)}
                <li class:active={conversation.id === appState.chat.conversationId} class="conversation-card">
                    <button
                        type="button"
                        class="conversation-select"
                        aria-pressed={conversation.id === appState.chat.conversationId}
                        aria-current={conversation.id === appState.chat.conversationId ? 'true' : undefined}
                        onclick={() => openConversation(conversation.id)}
                    >
                        <span class="conversation-title">{conversationTitle(conversation)}</span>
                        {#if conversationPreview(conversation)}
                            <span class="conversation-preview">{conversationPreview(conversation)}</span>
                        {/if}
                    </button>
                    <button
                        type="button"
                        class="conversation-delete"
                        aria-label={`${t('delete_conversation_button', 'Delete')}: ${conversationTitle(conversation)}`}
                        onclick={() => deleteConversation(conversation.id)}
                    >
                        {t('delete_conversation_button', 'Delete')}
                    </button>
                </li>
            {/each}
        </ul>
    {/if}
</aside>
